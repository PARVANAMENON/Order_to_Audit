"""Sales views: orders, invoices, dispatch, credit notes, and PDF generation."""

from __future__ import annotations

import io
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.masters.models import Customer, Item, ItemType, PriceList, Unit
from apps.masters.services import UnitConversionError
from apps.sales.models import (
    Invoice,
    Order,
    OrderStatus,
)
from apps.sales.services import (
    approve_order,
    post_credit_note,
    post_dispatch,
    post_invoice,
    reject_order,
    submit_order,
)

VIEW_ROLES = (Role.ADMIN, Role.AUDITOR, Role.OWNER, Role.SALESMAN)
ADMIN_ROLES = (Role.ADMIN,)
SALESMAN_ROLES = (Role.SALESMAN, Role.ADMIN)


@role_required(Role.SALESMAN, Role.ADMIN)
def pwa_order_view(request: HttpRequest) -> HttpResponse:
    """Mobile-first offline order capture shell for salesmen.

    Customers are scoped to the assigned salesman; item/price data is embedded
    so the page can keep working when the device drops connectivity.
    """
    customers = Customer.objects.filter(is_active=True)
    if request.user.role == Role.SALESMAN:
        customers = customers.filter(assigned_salesman=request.user)

    items = Item.objects.filter(is_active=True, item_type=ItemType.FINISHED).select_related(
        "base_unit"
    )
    latest_prices: dict[int, Decimal] = {}
    for price in PriceList.objects.filter(is_active=True, customer__isnull=True).order_by(
        "effective_from"
    ):
        latest_prices[price.item_id] = price.rate

    return render(
        request,
        "sales/pwa.html",
        {
            "customers_json": [
                {"id": c.id, "name": c.name, "state": c.state} for c in customers
            ],
            "items_json": [
                {
                    "id": i.id,
                    "sku": i.sku,
                    "name": i.name,
                    "unit_id": i.base_unit_id,
                    "price": str(latest_prices.get(i.id, "0.00")),
                }
                for i in items
            ],
            "units_json": [{"id": u.id, "code": u.code} for u in Unit.objects.all()],
        },
    )


def pwa_manifest_view(request: HttpRequest) -> JsonResponse:
    """Web app manifest for installing the salesman order shell."""
    return JsonResponse(
        {
            "name": "Order-to-Audit Salesman",
            "short_name": "OTA Sales",
            "start_url": "/sales/pwa/",
            "scope": "/sales/",
            "display": "standalone",
            "background_color": "#f6f7fb",
            "theme_color": "#0f172a",
            "icons": [
                {
                    "src": "/static/sales/icon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any maskable",
                }
            ],
        }
    )


def pwa_service_worker_view(request: HttpRequest) -> HttpResponse:
    """Serve the service worker at /sales/ so it can control the PWA scope."""
    sw = """
const CACHE = 'ota-sales-pwa-v1';
const SHELL = '/sales/pwa/';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.add(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.pathname !== SHELL) return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(SHELL, copy));
        return response;
      })
      .catch(() => caches.match(SHELL))
  );
});
"""
    response = HttpResponse(sw, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/sales/"
    return response


@role_required(*VIEW_ROLES)
def order_list_view(request: HttpRequest) -> HttpResponse:
    orders = Order.objects.select_related("customer", "salesman")
    if request.user.role == Role.SALESMAN and not request.user.is_superuser:
        orders = orders.filter(salesman=request.user)
    return render(request, "sales/order_list.html", {"orders": orders})


@role_required(*SALESMAN_ROLES)
def order_create_view(request: HttpRequest) -> HttpResponse:
    """Salesman creates a new order."""
    customers = Customer.objects.filter(is_active=True)
    if request.user.role == Role.SALESMAN:
        customers = customers.filter(assigned_salesman=request.user)
    items = Item.objects.filter(is_active=True, item_type=ItemType.FINISHED).select_related(
        "base_unit"
    )
    units = Unit.objects.all()

    if request.method == "POST":
        cust = get_object_or_404(Customer, pk=request.POST.get("customer_id"))
        notes = request.POST.get("notes", "")
        item_ids = request.POST.getlist("item_id")
        qtys = request.POST.getlist("qty")
        unit_ids = request.POST.getlist("unit_id")
        prices = request.POST.getlist("unit_price")

        try:
            lines = []
            for i, item_id in enumerate(item_ids):
                if not item_id:
                    continue
                item = get_object_or_404(Item, pk=item_id)
                unit = get_object_or_404(Unit, pk=unit_ids[i])
                lines.append(
                    {
                        "item": item,
                        "qty": qtys[i],
                        "unit": unit,
                        "unit_price": prices[i],
                    }
                )
            if not lines:
                raise ValidationError("Add at least one line.")
            order = submit_order(
                customer=cust,
                salesman=request.user,
                lines=lines,
                notes=notes,
            )
            messages.success(request, f"Order ORD-{order.id} submitted.")
            return redirect("sales:order-detail", pk=order.id)
        except (ValidationError, ValueError, TypeError) as exc:
            messages.error(request, str(exc))

    prices_map = {
        p.item_id: str(p.rate)
        for p in PriceList.objects.filter(is_active=True, customer__isnull=True)
    }
    return render(
        request,
        "sales/order_create.html",
        {
            "customers": customers,
            "items": items,
            "units": units,
            "prices_map": prices_map,
            "today": timezone.localdate().isoformat(),
        },
    )


@role_required(*VIEW_ROLES)
def order_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(
        Order.objects.select_related("customer", "salesman", "approved_by"), pk=pk
    )
    if request.user.role == Role.SALESMAN and order.salesman_id != request.user.id:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    lines = order.lines.select_related("item", "unit").all()
    shortages = []
    for line in lines:
        if line.item.item_type == ItemType.FINISHED:
            from apps.inventory.services import balance
            from apps.masters.services import convert_quantity
            avail = balance(line.item)
            req = convert_quantity(line.effective_qty, line.unit, line.item.base_unit)
            if avail < req:
                shortages.append(
                    {"sku": line.item.sku, "shortage": req - avail, "available": avail}
                )
    can_adjust = order.status == OrderStatus.SUBMITTED and (
        request.user.role == Role.ADMIN or request.user.is_superuser
    )
    return render(
        request,
        "sales/order_detail.html",
        {
            "order": order,
            "lines": lines,
            "shortages": shortages,
            "can_adjust": can_adjust,
        },
    )


@role_required(*ADMIN_ROLES)
def order_approve_view(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(Order, pk=pk)
    if request.method == "POST":
        try:
            line_adjs = {}
            for line in order.lines.all():
                adj = request.POST.get(f"adj_qty_{line.id}", "").strip()
                if adj:
                    line_adjs[line.id] = adj
            _, shortages = approve_order(
                order, user=request.user, line_adjustments=line_adjs or None
            )
            if shortages:
                for s in shortages:
                    messages.warning(
                        request,
                        f"Stock shortage for {s['sku']}: need {s['required']}, "
                        f"available {s['available']}, shortage {s['shortage']}",
                    )
            messages.success(request, f"Order ORD-{order.id} approved.")
        except (ValidationError, UnitConversionError, ValueError) as exc:
            messages.error(request, str(exc))
    return redirect("sales:order-detail", pk=pk)


@role_required(*ADMIN_ROLES)
def order_reject_view(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(Order, pk=pk)
    if request.method == "POST":
        reason = request.POST.get("rejection_reason", "")
        try:
            reject_order(order, user=request.user, reason=reason)
            messages.success(request, f"Order ORD-{order.id} rejected.")
        except (ValidationError, ValueError) as exc:
            messages.error(request, str(exc))
    return redirect("sales:order-detail", pk=pk)


@role_required(*ADMIN_ROLES)
def invoice_create_view(request: HttpRequest, order_pk: int) -> HttpResponse:
    order = get_object_or_404(Order, pk=order_pk)
    if request.method == "POST":
        try:
            invoice = post_invoice(order, user=request.user)
            messages.success(request, f"Invoice {invoice.fy_number} created.")
            return redirect("sales:invoice-detail", pk=invoice.id)
        except (ValidationError, ValueError) as exc:
            messages.error(request, str(exc))
    return redirect("sales:order-detail", pk=order_pk)


@role_required(Role.ADMIN, Role.AUDITOR, Role.OWNER, Role.SALESMAN)
def invoice_list_view(request: HttpRequest) -> HttpResponse:
    invoices = Invoice.objects.select_related("customer", "order__salesman", "created_by")
    if request.user.role == Role.SALESMAN:
        invoices = invoices.filter(order__salesman=request.user)
    return render(request, "sales/invoice_list.html", {"invoices": invoices})


@role_required(Role.ADMIN, Role.AUDITOR, Role.OWNER, Role.SALESMAN)
def invoice_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    invoice = get_object_or_404(
        Invoice.objects.select_related("customer", "order", "created_by"), pk=pk
    )
    lines = invoice.lines.select_related("item", "unit").all()
    dispatches = invoice.dispatches.select_related("dispatched_by").all()
    credit_notes = invoice.credit_notes.select_related("created_by").all()
    return render(
        request,
        "sales/invoice_detail.html",
        {
            "invoice": invoice,
            "lines": lines,
            "dispatches": dispatches,
            "credit_notes": credit_notes,
        },
    )


@role_required(*ADMIN_ROLES)
def dispatch_view(request: HttpRequest, invoice_pk: int) -> HttpResponse:
    invoice = get_object_or_404(Invoice, pk=invoice_pk)
    if request.method == "POST":
        try:
            d = post_dispatch(invoice, user=request.user)
            messages.success(request, f"Dispatch DISP-{d.id} posted.")
        except (ValidationError, UnitConversionError, ValueError) as exc:
            messages.error(request, str(exc))
    return redirect("sales:invoice-detail", pk=invoice_pk)


@role_required(*ADMIN_ROLES)
def credit_note_view(request: HttpRequest, invoice_pk: int) -> HttpResponse:
    invoice = get_object_or_404(Invoice, pk=invoice_pk)
    if request.method == "POST":
        reason = request.POST.get("reason", "")
        reverses_stock = request.POST.get("reverses_stock") == "1"
        try:
            cn = post_credit_note(
                invoice, user=request.user, reason=reason, reverses_stock=reverses_stock
            )
            messages.success(request, f"Credit note {cn.cn_number} created.")
        except (ValidationError, ValueError) as exc:
            messages.error(request, str(exc))
    return redirect("sales:invoice-detail", pk=invoice_pk)


@role_required(Role.ADMIN, Role.AUDITOR, Role.OWNER, Role.SALESMAN)
def invoice_pdf_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Generate a simple PDF invoice using ReportLab."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas as rl_canvas

    invoice = get_object_or_404(
        Invoice.objects.select_related("customer", "order", "created_by"), pk=pk
    )
    lines = invoice.lines.select_related("item", "unit").all()

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, h - 2 * cm, "TAX INVOICE")
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, h - 2.8 * cm, f"Invoice No: {invoice.fy_number}")
    c.drawString(2 * cm, h - 3.4 * cm, f"Date: {invoice.invoice_date}")
    c.drawString(2 * cm, h - 4.0 * cm, f"Customer: {invoice.customer.name}")
    c.drawString(2 * cm, h - 4.6 * cm, f"GSTIN: {invoice.customer.gstin}")
    c.drawString(2 * cm, h - 5.2 * cm, f"Place of Supply: {invoice.place_of_supply}")

    # Table header
    y = h - 6.5 * cm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(2 * cm, y, "Item")
    c.drawString(9 * cm, y, "HSN")
    c.drawString(11 * cm, y, "Qty")
    c.drawString(13 * cm, y, "Rate")
    c.drawString(15 * cm, y, "Taxable")
    c.drawString(17.5 * cm, y, "Tax")
    c.drawString(19 * cm, y, "Total")
    y -= 0.5 * cm
    c.setFont("Helvetica", 8)
    for line in lines:
        c.drawString(2 * cm, y, line.item.name[:30])
        c.drawString(9 * cm, y, line.hsn)
        c.drawString(11 * cm, y, f"{line.qty} {line.unit.code}")
        c.drawString(13 * cm, y, str(line.unit_price))
        c.drawString(15 * cm, y, str(line.taxable_value))
        tax = line.cgst + line.sgst + line.igst
        c.drawString(17.5 * cm, y, str(tax))
        c.drawString(19 * cm, y, str(line.line_total))
        y -= 0.5 * cm

    y -= 0.3 * cm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(13 * cm, y, f"Taxable: {invoice.taxable_value}")
    y -= 0.5 * cm
    if invoice.cgst:
        c.drawString(13 * cm, y, f"CGST: {invoice.cgst}  SGST: {invoice.sgst}")
        y -= 0.5 * cm
    if invoice.igst:
        c.drawString(13 * cm, y, f"IGST: {invoice.igst}")
        y -= 0.5 * cm
    c.drawString(13 * cm, y, f"TOTAL: Rs {invoice.total_amount}")

    c.showPage()
    c.save()
    buf.seek(0)
    resp = HttpResponse(buf.read(), content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="invoice-{invoice.fy_number}.pdf"'
    return resp
