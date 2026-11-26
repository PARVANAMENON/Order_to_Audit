/**
 * Automated, caption-narrated demo of the Order-to-Audit ERP.
 *
 * Run from the project root:
 *   node demo/record.mjs
 * Override the target:
 *   TARGET=http://127.0.0.1:8000 node demo/record.mjs
 * Reuse the current data instead of resetting it first:
 *   SKIP_SEED=1 node demo/record.mjs
 *
 * Requires: playwright (+ chromium), ffmpeg/ffprobe, pdftoppm (poppler), and
 * Python with the project dependencies (for the demo seed reset).
 */
import { chromium } from 'playwright';
import { expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const ROOT = path.resolve(import.meta.dirname, '..');
const DEMO = path.join(ROOT, 'demo');
const VIDEOS = path.join(DEMO, 'videos');
const SCREENS = path.join(DEMO, 'screens');
const DOWNLOADS = path.join(DEMO, 'downloads');
const TARGET = (process.env.TARGET || 'http://127.0.0.1:8000').replace(/\/$/, '');
const PASSWORD = 'benchmark123';

// ---------------------------------------------------------------------------
// Tooling: locate pdftoppm even when winget installed it after this shell started.
// ---------------------------------------------------------------------------
const WINGET_PACKAGES = path.join(
  process.env.LOCALAPPDATA || '',
  'Microsoft',
  'WinGet',
  'Packages'
);

function findInWinget(packagePrefix, exeName) {
  if (!fs.existsSync(WINGET_PACKAGES)) return null;
  for (const pkg of fs.readdirSync(WINGET_PACKAGES)) {
    if (!pkg.startsWith(packagePrefix)) continue;
    const stack = [path.join(WINGET_PACKAGES, pkg)];
    while (stack.length) {
      const dir = stack.pop();
      let entries;
      try {
        entries = fs.readdirSync(dir, { withFileTypes: true });
      } catch {
        continue;
      }
      for (const entry of entries) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) stack.push(full);
        else if (
          entry.name.toLowerCase() === exeName.toLowerCase() ||
          entry.name.toLowerCase() === `${exeName.toLowerCase()}.exe`
        ) {
          return full;
        }
      }
    }
  }
  return null;
}

function resolveTool(exeName, wingetPrefix) {
  const explicit = process.env[exeName.toUpperCase()];
  if (explicit && fs.existsSync(explicit)) return explicit;
  const found = findInWinget(wingetPrefix, exeName);
  if (found) return found;
  try {
    execFileSync(exeName, ['-version'], { stdio: 'ignore' });
    return exeName;
  } catch {
    return null;
  }
}

const PDFTOPPM = resolveTool('pdftoppm', 'oschwartz10612.Poppler');
const FFMPEG = resolveTool('ffmpeg', 'Gyan.FFmpeg');
const FFPROBE = resolveTool('ffprobe', 'Gyan.FFmpeg');

// ---------------------------------------------------------------------------
// Filesystem reset for this run.
// ---------------------------------------------------------------------------
for (const dir of [VIDEOS, SCREENS, DOWNLOADS]) {
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
}

const results = [];
const captions = [];
const facts = {};
let sceneNumber = 0;
let currentScene = '';

// ---------------------------------------------------------------------------
// Demo seed profile: transactional data is reset to a clean baseline, then the
// demo purchase, run, orders and payment are recreated before recording starts.
// ---------------------------------------------------------------------------
if (process.env.SKIP_SEED === '1') {
  console.log('Skipping demo data reset (SKIP_SEED=1).');
} else {
  const python = process.env.PYTHON || 'python';
  console.log('Resetting demo data: seed_benchmark --profile demo');
  execFileSync(
    python,
    [path.join(ROOT, 'backend', 'manage.py'), 'seed_benchmark', '--profile', 'demo'],
    { cwd: ROOT, stdio: 'inherit' }
  );
}

// ---------------------------------------------------------------------------
// Browser + in-page helpers (survive navigation via addInitScript).
// ---------------------------------------------------------------------------
const browser = await chromium.launch({ headless: true, slowMo: 250 });
const VIDEO_START = Date.now();
const context = await browser.newContext({
  viewport: { width: 1280, height: 720 },
  recordVideo: { dir: VIDEOS, size: { width: 1280, height: 720 } },
  acceptDownloads: true,
});
const page = await context.newPage();

await context.addInitScript(() => {
  const ensure = () => {
    if (!document.documentElement) return;
    if (!document.getElementById('ota-cursor')) {
      const style = document.createElement('style');
      style.id = 'ota-cursor-style';
      style.textContent = `
        #ota-cursor {
          position: fixed; left: 50%; top: 50%; width: 14px; height: 14px;
          border-radius: 50%; background: #ef4444; border: 2px solid #fff;
          box-shadow: 0 2px 10px rgba(0,0,0,.45); pointer-events: none;
          transform: translate(-50%, -50%); z-index: 2147483647;
          transition: left .06s linear, top .06s linear;
        }
      `;
      document.documentElement.appendChild(style);
      const dot = document.createElement('div');
      dot.id = 'ota-cursor';
      document.documentElement.appendChild(dot);
      document.addEventListener(
        'mousemove',
        (event) => {
          dot.style.left = `${event.clientX}px`;
          dot.style.top = `${event.clientY}px`;
        },
        true
      );
    }
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ensure, { once: true });
  } else {
    ensure();
  }
});

async function setCaption(text) {
  await page.evaluate((value) => {
    let el = document.getElementById('ota-caption');
    if (!el) {
      el = document.createElement('div');
      el.id = 'ota-caption';
      document.body.appendChild(el);
    }
    el.textContent = value;
    el.style.cssText = [
      'position:fixed',
      'left:50%',
      'bottom:34px',
      'transform:translateX(-50%)',
      'max-width:min(1120px,92vw)',
      'padding:15px 28px',
      'background:rgba(2,6,23,.88)',
      'color:#fff',
      'font:600 28px/1.32 "Segoe UI",system-ui,sans-serif',
      'text-align:center',
      'border:1px solid rgba(148,163,184,.35)',
      'border-radius:14px',
      'box-shadow:0 18px 48px rgba(0,0,0,.45)',
      'z-index:2147483646',
      'pointer-events:none',
      'letter-spacing:-0.01em',
    ].join(';');
  }, text);
}

async function hideCaption() {
  await page.evaluate(() => {
    const el = document.getElementById('ota-caption');
    if (el) el.remove();
  });
}

async function caption(text, seconds) {
  captions.push({
    scene: currentScene,
    at: Number(((Date.now() - VIDEO_START) / 1000).toFixed(2)),
    seconds,
    text,
  });
  await setCaption(text);
  await page.waitForTimeout(seconds * 1000);
  await hideCaption();
}

async function titleCard({ kicker, title, subtitle, footer }, seconds) {
  await page.evaluate(
    ({ kicker, title, subtitle, footer }) => {
      document.getElementById('ota-titlecard')?.remove();
      const el = document.createElement('div');
      el.id = 'ota-titlecard';
      el.style.cssText = [
        'position:fixed',
        'inset:0',
        'z-index:2147483645',
        'display:flex',
        'flex-direction:column',
        'align-items:center',
        'justify-content:center',
        'gap:18px',
        'padding:70px',
        'text-align:center',
        'color:#fff',
        'background:radial-gradient(900px 520px at 20% 0%, rgba(99,102,241,.45), transparent 62%), radial-gradient(800px 500px at 90% 100%, rgba(13,148,136,.35), transparent 60%), #070c18',
        'font-family:"Segoe UI",system-ui,sans-serif',
      ].join(';');
      const kickerEl = document.createElement('div');
      kickerEl.textContent = kicker;
      kickerEl.style.cssText =
        'font-size:17px;letter-spacing:.22em;text-transform:uppercase;color:#5eead4;font-weight:700';
      const titleEl = document.createElement('div');
      titleEl.textContent = title;
      titleEl.style.cssText =
        'font-size:72px;line-height:1.02;font-weight:800;letter-spacing:-0.04em;background:linear-gradient(100deg,#fff,#c7d2fe 55%,#99f6e4);-webkit-background-clip:text;background-clip:text;color:transparent';
      const subEl = document.createElement('div');
      subEl.textContent = subtitle;
      subEl.style.cssText =
        'max-width:940px;font-size:30px;line-height:1.42;color:#cbd5e1;font-weight:500';
      const footEl = document.createElement('div');
      footEl.textContent = footer;
      footEl.style.cssText =
        'margin-top:26px;font-size:18px;color:#94a3b8;letter-spacing:.04em';
      el.append(kickerEl, titleEl, subEl, footEl);
      document.body.appendChild(el);
    },
    { kicker, title, subtitle, footer }
  );
  await page.waitForTimeout(seconds * 1000);
  await page.evaluate(() => document.getElementById('ota-titlecard')?.remove());
}

async function typeSlow(locator, text) {
  await expect(locator).toBeVisible({ timeout: 15000 });
  await locator.click();
  await locator.fill('');
  await locator.pressSequentially(text, { delay: 60 });
}

async function go(url) {
  await page.goto(`${TARGET}${url}`, { waitUntil: 'domcontentloaded' });
}

async function login(username, expectedName) {
  await go('/login/');
  await expect(page.getByLabel('Username')).toBeVisible({ timeout: 15000 });
  await typeSlow(page.getByLabel('Username'), username);
  await typeSlow(page.getByLabel('Password'), PASSWORD);
  await page.getByRole('button', { name: 'Login' }).click();
  await page.waitForURL(`${TARGET}/`);
  await expect(page.locator('.hero')).toBeVisible({ timeout: 15000 });
  if (expectedName) {
    await expect(page.locator('.hero h1')).toContainText(expectedName, {
      timeout: 15000,
    });
  }
}

async function logout() {
  const button = page.getByRole('button', { name: 'Logout' });
  if (await button.count()) {
    await button.click();
    await page.waitForURL(`${TARGET}/login/`);
  }
}

// ---------------------------------------------------------------------------
// Scene runner: exact budget, failure isolation, per-scene screenshot.
// ---------------------------------------------------------------------------
async function scene(name, budgetSeconds, fn) {
  sceneNumber += 1;
  const label = `${String(sceneNumber).padStart(2, '0')}-${name}`;
  currentScene = label;
  const started = Date.now();
  let ok = true;
  console.log(`\n▶ ${label} (${budgetSeconds}s budget)`);
  try {
    await fn();
  } catch (error) {
    ok = false;
    console.error(`✖ ${label}: ${error.message}`);
    try {
      await page.screenshot({ path: path.join(SCREENS, `${label}-failure.png`) });
    } catch {
      /* screenshot is best effort */
    }
    try {
      await page.goto(`${TARGET}/`, { waitUntil: 'domcontentloaded' });
    } catch {
      /* keep going */
    }
  }

  const startOffset = Number(((started - VIDEO_START) / 1000).toFixed(2));
  const elapsed = (Date.now() - started) / 1000;
  if (elapsed > budgetSeconds) {
    console.warn(
      `⚠ ${label} overran by ${(elapsed - budgetSeconds).toFixed(1)}s`
    );
  } else {
    await page.waitForTimeout((budgetSeconds - elapsed) * 1000);
  }

  try {
    await page.screenshot({ path: path.join(SCREENS, `${label}.png`) });
  } catch (error) {
    console.warn(`⚠ screenshot for ${label} failed: ${error.message}`);
  }

  const finalElapsed = (Date.now() - started) / 1000;
  results.push({
    scene: label,
    ok,
    start: startOffset,
    seconds: Number(finalElapsed.toFixed(1)),
  });
  console.log(
    `${ok ? '✓' : '✖'} ${label} finished in ${finalElapsed.toFixed(1)}s`
  );
}

// ---------------------------------------------------------------------------
// Small flows reused across scenes.
// ---------------------------------------------------------------------------
async function showPdf(invoiceUrl) {
  const pdfPath = path.join(DOWNLOADS, 'invoice.pdf');
  const pdfUrl = `${invoiceUrl.replace(/\/$/, '')}/pdf/`;
  let saved = false;

  // Preferred path: a real browser download event.
  try {
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 6000 }),
      page.getByRole('link', { name: 'Download PDF' }).click(),
    ]);
    await download.saveAs(pdfPath);
    saved = true;
    console.log('  PDF captured through the download event');
  } catch {
    console.log(
      '  PDF link is served inline; fetching it through the browser request context'
    );
  }

  for (const other of context.pages()) {
    if (other !== page) await other.close().catch(() => {});
  }

  if (!saved) {
    const response = await context.request.get(pdfUrl);
    if (!response.ok()) throw new Error(`PDF request failed: ${response.status()}`);
    fs.writeFileSync(pdfPath, await response.body());
  }

  if (!PDFTOPPM) throw new Error('pdftoppm (poppler) is required to render the PDF');
  const prefix = path.join(DOWNLOADS, 'invoice-page');
  // 200 DPI so the line-item table stays crisp when it is zoomed in.
  execFileSync(
    PDFTOPPM,
    ['-png', '-r', '200', '-f', '1', '-l', '1', '-singlefile', pdfPath, prefix],
    { stdio: 'ignore' }
  );
  const pngPath = `${prefix}.png`;
  const base64 = fs.readFileSync(pngPath).toString('base64');

  await page.evaluate(async (src) => {
    document.getElementById('ota-pdf')?.remove();
    const overlay = document.createElement('div');
    overlay.id = 'ota-pdf';
    overlay.style.cssText =
      'position:fixed;inset:0;z-index:2147483644;background:#070c18;display:flex;align-items:center;justify-content:center;padding:2vh 2vw 16vh;box-sizing:border-box';
    const img = document.createElement('img');
    img.style.cssText =
      'max-width:100%;max-height:100%;background:#fff;border-radius:6px;box-shadow:0 30px 80px rgba(0,0,0,.6)';
    overlay.appendChild(img);
    document.body.appendChild(overlay);

    // The invoice only fills the top third of the A4 page; trim the whitespace
    // so the line items and totals are shown at roughly 2.7x their fitted size.
    const pageImage = new Image();
    pageImage.src = src;
    await pageImage.decode();
    const canvas = document.createElement('canvas');
    canvas.width = pageImage.naturalWidth;
    canvas.height = pageImage.naturalHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(pageImage, 0, 0);
    const { data, width, height } = ctx.getImageData(0, 0, canvas.width, canvas.height);
    let top = height;
    let left = width;
    let right = 0;
    let bottom = 0;
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const offset = (y * width + x) * 4;
        if (data[offset] < 245 || data[offset + 1] < 245 || data[offset + 2] < 245) {
          if (y < top) top = y;
          if (y > bottom) bottom = y;
          if (x < left) left = x;
          if (x > right) right = x;
        }
      }
    }
    if (right <= left || bottom <= top) return;

    const pad = 18;
    const crop = document.createElement('canvas');
    const sx = Math.max(0, left - pad);
    const sy = Math.max(0, top - pad);
    crop.width = Math.min(width - sx, right - left + pad * 2);
    crop.height = Math.min(height - sy, bottom - top + pad * 2);
    crop
      .getContext('2d')
      .drawImage(canvas, sx, sy, crop.width, crop.height, 0, 0, crop.width, crop.height);
    img.src = crop.toDataURL('image/png');
  }, `data:image/png;base64,${base64}`);
}

async function hidePdf() {
  await page.evaluate(() => document.getElementById('ota-pdf')?.remove());
}

// ---------------------------------------------------------------------------
// Pre-flight.
// ---------------------------------------------------------------------------
try {
  const response = await fetch(`${TARGET}/login/`, { redirect: 'manual' });
  if (!response.ok && response.status !== 302) {
    throw new Error(`/login/ returned ${response.status}`);
  }
} catch (error) {
  console.error(
    `Server is not reachable at ${TARGET}. Start it first:\n` +
      '  python backend/manage.py migrate && python backend/manage.py runserver'
  );
  throw error;
}
console.log(`Recording ${TARGET} → demo/videos`);

// ---------------------------------------------------------------------------
// Story.
// ---------------------------------------------------------------------------
await page.goto('about:blank');
await page.evaluate(() => {
  document.body.style.background = '#070c18';
});

let newOrderUrl = '';
let newOrderId = '';
let invoiceUrl = '';
let invoiceId = '';
let runId = '';
const orderQty = 5000;
let availablePackets = null;
let shortagePackets = null;

await scene('title', 40, async () => {
  await titleCard(
    {
      kicker: 'GST-ready snack manufacturing ERP',
      title: 'Order-to-Audit',
      subtitle:
        "From the field salesman's first order to the auditor's last review — one ledger, one trail, zero gaps.",
      footer: 'Automated product demo · Tamil Nadu snack factory',
    },
    9
  );
  await go('/login/');
  await caption(
    'A snack factory in Tamil Nadu needs every order traced from sale to audit.',
    6
  );
  await caption(
    'One Django app, five roles: salesman, admin, production, auditor and owner.',
    6
  );
  await caption(
    'Everyone signs in to the same ledger — no spreadsheets in between.',
    5
  );
});

await scene('salesman', 80, async () => {
  await login('salesmanA', 'Salesman A');
  await caption('Salesman A signs in. Every field order starts here.', 3);

  await go('/sales/orders/new/');
  await caption(
    `Placing a ${orderQty.toLocaleString('en-IN')}-packet order for Retailer A in Tamil Nadu.`,
    3
  );
  await page
    .locator('select[name="customer_id"]')
    .selectOption({ label: 'Retailer A (Tamil Nadu)' });
  await typeSlow(page.locator('input[name="notes"]'), 'Salem route — demo order');
  await page
    .locator('select[name="item_id"]')
    .selectOption({ label: 'FG-MURUKKU-200G - Murukku 200g' });
  await typeSlow(page.locator('input[name="qty"]'), String(orderQty));
  await page.locator('select[name="unit_id"]').selectOption({ label: 'packet' });
  await typeSlow(page.locator('input[name="unit_price"]'), '50.00');
  await page.getByRole('button', { name: 'Submit Order' }).click();
  await page.waitForURL(/\/sales\/orders\/\d+\/$/);
  newOrderUrl = page.url();
  newOrderId = newOrderUrl.match(/orders\/(\d+)\//)[1];
  await expect(page.getByText('Stock Shortages:')).toBeVisible({
    timeout: 15000,
  });
  const shortageText = await page
    .locator('.card', { hasText: 'Stock Shortages:' })
    .locator('.badge-flag')
    .first()
    .innerText();
  shortagePackets = Number(shortageText.match(/short\s+([\d,.]+)/)[1].replace(/,/g, ''));
  availablePackets = orderQty - shortagePackets;
  facts.orderQty = orderQty;
  facts.availablePackets = availablePackets;
  facts.shortagePackets = shortagePackets;
  console.log(
    `  stock check: ${availablePackets} on hand, ${shortagePackets} short`
  );
  await caption(
    `Instant stock check: ${availablePackets.toLocaleString('en-IN')} packets on hand, so this order is ${shortagePackets.toLocaleString('en-IN')} short.`,
    6
  );

  await go('/sales/pwa/');
  await page.evaluate(() =>
    navigator.serviceWorker
      ? navigator.serviceWorker.ready.then(() => true)
      : false
  );
  await caption(
    'The field-capture PWA keeps working without a network. Orders queue on the device.',
    4
  );
  await context.setOffline(true);
  await caption('Network dropped — the app is now offline.', 3);

  await page
    .locator('#customer')
    .selectOption({ label: 'Retailer A (Tamil Nadu)' });
  await typeSlow(page.locator('#notes'), 'Offline field visit');
  await page
    .locator('tbody#lines tr')
    .first()
    .locator('select[aria-label="Item"]')
    .selectOption({ label: 'FG-MURUKKU-200G — Murukku 200g' });
  await typeSlow(
    page.locator('tbody#lines tr').first().locator('input[aria-label="Quantity"]'),
    '12'
  );
  await typeSlow(
    page.locator('tbody#lines tr').first().locator('input[aria-label="Unit price"]'),
    '50.00'
  );
  await page.getByRole('button', { name: 'Submit Order' }).click();
  await expect(page.locator('#pwa-status')).toContainText('Offline — order saved', {
    timeout: 15000,
  });
  await caption(
    'Saved locally with an idempotency key. Nothing is lost when the signal drops.',
    5
  );

  await context.setOffline(false);
  await page.getByRole('button', { name: 'Sync Queued Orders' }).click();
  await expect(page.locator('#pwa-status')).toContainText('queued order(s) synced', {
    timeout: 20000,
  });
  await caption(
    'Back online: the queue replays through the idempotent API — no duplicates.',
    5
  );
});

await scene('masters', 60, async () => {
  await go('/masters/items/');
  await expect(page.getByRole('heading', { name: 'Items' })).toBeVisible();
  await caption(
    'Masters: items, HSN codes, GST rates and per-item variance tolerances.',
    5
  );
  await page.getByRole('heading', { name: 'Unit Conversions' }).scrollIntoViewIfNeeded();
  await caption(
    'Table-driven conversions: kg to g, litre to ml, carton to packets.',
    5
  );
  await go('/masters/customers/');
  await expect(page.getByRole('heading', { name: 'Customers' })).toBeVisible();
  await caption(
    'Customer state decides the tax: Tamil Nadu splits CGST + SGST; Karnataka uses IGST.',
    6
  );
  await caption(
    'The Murukku 200 g BOM plans 200 packets per batch, consumed line by line in production.',
    6
  );
});

await scene('admin', 75, async () => {
  await logout();
  await login('admin', 'Admin User');
  await caption('Admin reviews the field order against live stock.', 3);

  await go(`/sales/orders/${newOrderId}/`);
  await expect(page.getByText('Stock Shortages:')).toBeVisible();
  await caption(
    `${orderQty.toLocaleString('en-IN')} requested, ${availablePackets.toLocaleString('en-IN')} available. Admin trims the approved quantity to 200.`,
    5
  );
  const approvedQty = page.locator('input[name^="adj_qty_"]').first();
  await typeSlow(approvedQty, '200');
  await page.getByRole('button', { name: 'Approve' }).click();
  await expect(page.locator('.messages li').first()).toContainText('approved', {
    timeout: 15000,
  });
  await caption(
    'Approval checks stock coverage before it commits. The order is approved.',
    4
  );

  await page.getByRole('button', { name: 'Create Invoice' }).click();
  await page.waitForURL(/\/sales\/invoices\/\d+\/$/);
  invoiceUrl = page.url();
  invoiceId = invoiceUrl.match(/invoices\/(\d+)\//)[1];
  await expect(page.getByRole('heading', { name: /2026-27\/\d+/ })).toBeVisible();
  await caption(
    'Gapless financial-year invoice number. Intra-state supply splits 2.5% CGST + 2.5% SGST.',
    5
  );

  await caption('The GST tax invoice is also a print-ready PDF.', 2);
  await showPdf(invoiceUrl);
  await caption(
    'Zoomed in: HSN, quantity, rate, taxable value and the CGST/SGST split.',
    2
  );
  await caption('ReportLab renders the same ledger numbers — no re-keying.', 5);
  await page.screenshot({ path: path.join(SCREENS, '04-invoice-pdf.png') });
  await hidePdf();

  await page.getByRole('button', { name: 'Post Dispatch' }).click();
  await expect(page.getByRole('heading', { name: 'Dispatches' })).toBeVisible({
    timeout: 15000,
  });
  await caption(
    'Dispatch posts finished goods out of the ledger. Posted documents are never edited.',
    5
  );

  await go('/payments/new/');
  await caption(
    'A Rs 5,000 receipt auto-allocates FIFO to the oldest open invoices.',
    3
  );
  await page
    .locator('select[name="customer_id"]')
    .selectOption({ label: 'Retailer A' });
  await typeSlow(page.locator('input[name="amount"]'), '5000.00');
  await typeSlow(page.locator('input[name="reference"]'), 'UPI-DEMO-7788');
  await typeSlow(page.locator('textarea[name="notes"]'), 'Demo part payment');
  await page.getByRole('button', { name: 'Post Payment' }).click();
  await page.waitForURL(`${TARGET}/payments/`);
  await expect(
    page.getByRole('heading', { name: /Customer Outstanding/ })
  ).toBeVisible();
  await caption('Payment posted. Ageing buckets update immediately.', 4);

  await go(`/sales/invoices/${invoiceId}/`);
  await page.locator('input[name="reason"]').fill('Demo: carton damaged in transit');
  await caption(
    'Credit notes live here: they reverse revenue, tax and optionally stock — the invoice itself stays immutable.',
    5
  );
});

await scene('production', 75, async () => {
  await logout();
  await login('production', 'Production Supervisor');
  await caption('The production supervisor starts a run from the Murukku BOM.', 3);

  await go('/production/new/');
  await page.locator('select[name="bom_id"]').selectOption({ index: 0 });
  await typeSlow(page.locator('textarea[name="notes"]'), 'Demo run — variance check');
  await page.getByRole('button', { name: 'Create Run' }).click();
  await page.waitForURL(/\/production\/\d+\/$/);
  runId = page.url().match(/production\/(\d+)\//)[1];
  await caption('One batch: 200 packets planned from the BOM.', 3);

  await typeSlow(page.locator('#actual_output'), '196');
  await typeSlow(page.locator('#wastage'), '4');
  await typeSlow(page.locator('#damaged_packaging'), '2');
  await caption(
    'Actuals entered: 196 good packets, 4 wastage and 2 damaged pouches.',
    4
  );

  const actualInputs = page.locator('input[name^="actual_qty_"]');
  const actualValues = ['39.5', '9.8', '1.2', '194', '9'];
  for (let i = 0; i < actualValues.length; i += 1) {
    await typeSlow(actualInputs.nth(i), actualValues[i]);
  }
  await caption(
    'Raw material and packaging actuals are entered per BOM line.',
    4
  );

  await page.getByRole('button', { name: /Post Run to StockLedger/ }).click();
  await expect(page.locator('.messages li').first()).toContainText('StockLedger', {
    timeout: 15000,
  });
  await caption(
    'Posted: raw stock out, finished goods in — all append-only ledger rows.',
    5
  );
  await caption(
    'Cartons used 9 vs 10 planned: -10% variance, outside the 3% tolerance — flagged.',
    6
  );
  await page
    .getByRole('heading', { name: /Planned vs Actual/ })
    .scrollIntoViewIfNeeded();
  await caption(
    'Every line shows planned vs actual, variance, tolerance and line cost.',
    5
  );
});

await scene('accountant', 60, async () => {
  await logout();
  await login('auditor', 'Internal Auditor');
  await caption('The auditor works read-only: independent review, same data.', 3);

  await go(`/costing/run/${runId}/`);
  await expect(page.getByRole('heading', { name: /Cost Analysis/ })).toBeVisible();
  await caption(
    'Run costing: weighted-average material cost, overhead, cost per packet and margin.',
    6
  );

  await go('/reports/sales/');
  await expect(page.getByRole('heading', { name: 'Sales Register' })).toBeVisible();
  await caption('Sales register: invoice-level taxable value and the GST split.', 4);
  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 20000 }),
    page.getByRole('link', { name: 'Export CSV' }).click(),
  ]);
  await download.saveAs(path.join(DOWNLOADS, 'sales-register.csv'));
  await caption('CSV export downloads for the accountant; the app stays read-only.', 4);

  await go('/reports/gst/');
  await expect(page.getByRole('heading', { name: 'GST Summary' })).toBeVisible();
  await caption('GST summary: CGST, SGST and IGST collected for the period.', 5);

  await go('/inventory/ledger/');
  await expect(page.getByRole('heading', { name: 'Stock Ledger' })).toBeVisible();
  await caption(
    'Stock ledger: every movement links back to its source document and the user who posted it.',
    6
  );

  await go('/payments/');
  await expect(
    page.getByRole('heading', { name: /Customer Outstanding/ })
  ).toBeVisible();
  await caption('Outstanding and ageing: 0–30 through 90+ day buckets.', 5);
});

await scene('owner', 60, async () => {
  await logout();
  await login('owner', 'Business Owner');
  await caption(
    "Owner dashboard: today's orders, pending approvals, flagged runs and receivables.",
    4
  );

  await go('/reports/');
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  await caption(
    'Stock is never stored: every balance is SUM(StockLedger.qty) at weighted-average cost.',
    6
  );
  await caption(
    'Low-stock alerts and flagged production runs surface where the owner looks first.',
    5
  );

  await go('/audit/');
  await expect(page.getByRole('heading', { name: 'Audit Log' })).toBeVisible();
  await caption(
    'The audit trail is append-only: actor, action, before/after and timestamp for every write.',
    6
  );

  await go(`/sales/invoices/${invoiceId}/`);
  await caption(
    'Posted invoices are immutable. Corrections are credit notes — never silent edits.',
    6
  );

  await go('/inventory/');
  await caption('One ledger. One trail. Zero gaps.', 4);
});

await scene('closing', 30, async () => {
  await go('/');
  await titleCard(
    {
      kicker: 'Order-to-Audit',
      title: 'One ledger. One trail. Zero gaps.',
      subtitle:
        'Django 5 · Django REST Framework · PostgreSQL · Gunicorn + WhiteNoise · ReportLab · Docker',
      footer:
        'Roles: Salesman · Admin · Production · Auditor · Owner   |   GST-ready snack manufacturing ERP',
    },
    17
  );
  await caption('Built with Django 5, DRF, PostgreSQL and ReportLab; shipped in Docker.', 4);
});

// ---------------------------------------------------------------------------
// Finalise the video.
// ---------------------------------------------------------------------------
let videoPath = null;
try {
  const video = page.video();
  await context.close();
  if (video) videoPath = await video.path();
} finally {
  await browser.close().catch(() => {});
}

if (videoPath) {
  const destination = path.join(VIDEOS, 'order-to-audit-demo.webm');
  fs.rmSync(destination, { force: true });
  fs.renameSync(videoPath, destination);
  console.log(`\nVideo written to ${path.relative(ROOT, destination)}`);
} else {
  console.error('No video was produced by Playwright.');
}

fs.writeFileSync(
  path.join(DEMO, 'run-summary.json'),
  JSON.stringify({ target: TARGET, results, facts }, null, 2)
);
fs.writeFileSync(path.join(DEMO, 'captions.json'), JSON.stringify(captions, null, 2));

const total = results.reduce((sum, item) => sum + item.seconds, 0);
console.log(`\nScene total: ${total.toFixed(1)}s`);
for (const item of results) {
  console.log(`${item.ok ? '✓' : '✖'} ${item.scene} — ${item.seconds}s`);
}

if (FFPROBE && videoPath) {
  try {
    const duration = execFileSync(
      FFPROBE,
      [
        '-v',
        'error',
        '-show_entries',
        'format=duration',
        '-of',
        'csv=p=0',
        path.join(VIDEOS, 'order-to-audit-demo.webm'),
      ],
      { encoding: 'utf8' }
    ).trim();
    console.log(`ffprobe duration: ${duration}s`);
  } catch (error) {
    console.warn(`ffprobe failed: ${error.message}`);
  }
}

if (results.some((item) => !item.ok)) {
  process.exitCode = 1;
}
if (FFMPEG) console.log('ffmpeg available for MP4 conversion.');
