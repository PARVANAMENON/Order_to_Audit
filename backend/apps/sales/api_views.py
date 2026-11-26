"""REST API for the salesman PWA — order submission and status."""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.models import Role
from apps.masters.models import Customer, Item, Unit
from apps.sales.models import Order
from apps.sales.services import submit_order


def api_order_status(request, pk: int) -> JsonResponse:
    """Return basic order status for the PWA polling."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        order = Order.objects.get(pk=pk)
        if request.user.role == Role.SALESMAN and order.salesman_id != request.user.id:
            return JsonResponse({"error": "Forbidden"}, status=403)
        return JsonResponse(
            {
                "id": order.id,
                "status": order.status,
                "customer": order.customer.name,
                "total_lines": order.lines.count(),
            }
        )
    except Order.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)


@require_POST
@csrf_exempt  # PWA sends JSON; CSRF handled by session cookie in real deploy
def api_submit_order(request) -> JsonResponse:
    """PWA endpoint: submit order with idempotency key."""
    import json

    if not request.user.is_authenticated:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    try:
        data = json.loads(request.body)
        customer = Customer.objects.get(pk=data["customer_id"])
        key = uuid.UUID(data.get("idempotency_key", str(uuid.uuid4())))
        created = not Order.objects.filter(idempotency_key=key).exists()
        lines = []
        for ln in data.get("lines", []):
            item = Item.objects.get(pk=ln["item_id"])
            unit = Unit.objects.get(pk=ln["unit_id"])
            lines.append(
                {
                    "item": item,
                    "qty": ln["qty"],
                    "unit": unit,
                    "unit_price": ln["unit_price"],
                }
            )
        order = submit_order(
            customer=customer,
            salesman=request.user,
            lines=lines,
            notes=data.get("notes", ""),
            idempotency_key=key,
        )
        return JsonResponse({"id": order.id, "status": order.status, "created": created})
    except (ValidationError, ValueError, KeyError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
