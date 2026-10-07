# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
- **The owner, Mr. Jamil Mujuzi** (MAQAM FOOD CITY SUPERMARKET, Kampala - Gulu Highway). Often away from the shop; checks takings, till status and the audit trail from his phone. His standing fear: cashiers switching off the router or server while he is away and stealing.
- **Cashiers** at two or more tills (shop PCs with barcode scanners and thermal receipt printers), on their feet, serving queues all day. They need the till fast and unmistakable.

## Product Purpose
The shop's point-of-sale and stock system: tills with receipt printing, products/prices/barcodes, stock in batches with expiry, stock taking, cash-up and drawer reconciliation, suppliers and deliveries, reports, users. Since 2 Oct 2026 it runs online at maqam.campusnect.com, with till heartbeats and owner alerts, an owner-only audit trail, and a phone app (PWA) for the owner. Success: the owner trusts the numbers from anywhere, and cashiers never wait on the screen.

## Operating Context
A busy Ugandan supermarket on a highway; bright shop lighting, shared PCs, a queue at the counter. Internet can drop — the same code also installs fully offline on a shop PC, so every asset (fonts, images, scripts) is vendored locally; no CDN.

## Capabilities and Constraints
- Django 6.1 + SQLite (WAL), plain JS, waitress + whitenoise. Templates under `supermarket_system/templates`, styles under `supermarket_system/static/css`.
- No layout decided by JavaScript; pages must be whole without JS. Respect `prefers-reduced-motion`.
- Must work at phone width (owner) and on till PCs.
- The repository is PUBLIC: never commit passwords, secret keys or the owner's personal email.

## Brand Commitments
- Name: **MAQAM FOOD CITY SUPERMARKET**; tagline "Fresh food, fair prices". Logo: an M whose shoulders are two market arches over a counter bar (`static/brand/maqam-logo.svg` is the master).
- **1 Oct 2026, client decision: the brand colour becomes ORANGE across the whole system, logo included** (a rich orange, not a yellowish one). Green is retired as the primary.
- Wording on the sign-in page stays as it is.
- Every screen carries "Powered by CampusNect Smart Technologies"; receipts carry it as text only.
- **The same code runs a second shop**: the FreshWay Supermarket demonstration shop (supermarket.campusnect.com, fictional, `SMMS_BRAND=freshway`, `SMMS_DEMO=1`). Names and addresses come from Shop details; everything drawn (the mark, app icons, opening animation, browser storage names) comes from `shop/brand.py`. Nothing MAQAM-specific may be hard-coded in a template or script.
- **7 Oct 2026: FreshWay has its own front door**, not MAQAM's with a new name: a market-stall sign-in (striped awning, this morning's produce prices on a board, a crate of fruit), its own opening (the awning drops, the F grows, an orange rolls in, the shutter rolls up), its own owner's-phone header and dashboard band, and a green sidebar. All chosen in `shop/brand.py` (`templates`, `app_css`, `price_board`); MAQAM lists none, so his screens render byte-for-byte as before.

## Evidence on Hand
- Real shop identity: name, address (Kampala - Gulu Highway), phone +256 703 649411.
- No photographs of the real shop yet. The sign-in background is a licensed free stock photograph (a young Black shopper with a trolley full of groceries) until the owner supplies his own.
- No testimonials, sales figures or customer claims exist; never invent them.

## Product Principles
1. The till is never slowed by decoration — expression lives around the work, not in its way.
2. The owner should feel the shop is with him, wherever he is: live, honest, and clear about what the system cannot know.
3. Everything works without the internet on the shop PC, and without JavaScript for layout.
4. It must look like *his* supermarket, not a template.
