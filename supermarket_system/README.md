# Supermarket Management System

An **offline** point-of-sale and stock system for a single supermarket. It runs on the
shop's own computer. Nothing is sent to the internet, and no monthly fee is owed to
anyone. The shop's whole record lives in one file, `db.sqlite3`.

Built from the client's own feature list — every item on that paper is accounted for
below.

---

## What the client asked for, and where it lives

| On the client's paper | Where it is in the system |
|---|---|
| Date | On every receipt, and the live clock at the top of every screen |
| Company name | **Setup → Shop details.** Prints at the head of every receipt |
| Served by (seller) | Each cashier signs in as themselves; their name goes on the receipt |
| Customer (walk-in) | Defaults to "Walk-in customer"; named customers exist for regulars and credit |
| Product name | **Stock → Products** |
| Barcode | On the product; the till's search box accepts a scanner or typing |
| Quantity | On the till, on deliveries, and everywhere stock is counted |
| Buying price | On the product and on every delivery line; drives all profit figures |
| Selling price | On the product; a cashier may override it per sale if the owner allows |
| Expiry date | On each **delivery batch**, not on the product — see the note below |
| Category | **Stock → Categories** |
| Measurements | **Stock → Measurements** — piece, kg, litre, crate, tray |
| Purchase | **Stock → Purchases** — the only way goods enter the shop |
| Stock available | **Stock → Stock available**, valued at cost and at selling price |
| Expired item | **Stock → Expiry watch**, plus a report; the till refuses to sell expired goods |
| Low stock | Flagged on the dashboard, the product list and the stock report |

### Why expiry belongs to a delivery, not to a product

The same soap delivered in March and in August expires on different days. If expiry sat
on the product, the second delivery would silently overwrite the first and the expiry
report would lie. So each delivery creates a **batch**, carrying its own quantity, cost
and expiry date. Sales draw from the batch that **expires first**, which is how a real
shop keeps waste down.

---

## Beyond the client's list

These were not on the paper but a shop hits them within the first week:

- **Voiding a receipt** — returns each item to the exact batch it left, and keeps the
  receipt marked VOIDED. Nothing is ever deleted.
- **Discounts, VAT, and payment method** — cash, mobile money, card or credit.
- **Credit sales** — a named customer can owe a balance, shown on their page.
- **Two roles** — a cashier sells, and cannot see buying prices, profit, or reports.
- **Every stock movement recorded** — who moved what, when, and why.
- **Backup** — one click writes a dated copy. An offline shop with one hard disk and no
  backup is one theft away from having no records at all.
- **Spreadsheet export** — stock, sales and expiry to CSV, for Excel.

---

## Installing on the shop's computer

1. Install Python from python.org. **Tick "Add Python to PATH"** during setup.
2. Copy this whole folder onto the shop's computer.
3. Double-click **INSTALL.bat** and answer the prompts.
4. Double-click **START SUPERMARKET.bat**. The browser opens on its own.

Sign in as `admin`. **Change that password immediately** under Setup → Users.

Make a shortcut to `START SUPERMARKET.bat` on the desktop and rename it to the shop's
name. To have it start with the computer, put the shortcut in
`shell:startup` (press Win+R and type that).

### First things to set up

1. **Setup → Shop details** — the shop's name, address, phone, logo, and paper size.
2. **Stock → Measurements** and **Categories** — a starter set is already loaded.
3. **Stock → Suppliers** — who the shop buys from.
4. **Stock → Products** — every item, with its barcode, buying and selling price.
5. **Stock → Purchases** — record what is already on the shelves as the first delivery.
   Give each line its expiry date so the expiry reports start out truthful.

---

## Running the till

The cursor sits in the barcode box. A scanner types into it like a keyboard and ends
with Enter, so a scanned item drops straight into the sale. With no scanner, type part
of a product name and press Enter.

| Key | What it does |
|---|---|
| `F2` | Jump back to the barcode box |
| `F9` | Complete the sale and print |
| `Enter` | Add the highlighted item |
| `Esc` | Clear the search |

The receipt prints on an 80mm or 58mm thermal roll, or on A4 — whichever is chosen in
Shop details, and it can be switched for a single print from the receipt window.

---

## Adding a second till later

Nothing needs reinstalling. The system already listens on the shop's network:

1. Leave the first computer running the system. Its address is shown in the black
   window, like `http://192.168.1.5:8000/`.
2. On the second computer, open that address in a browser. Add it as a bookmark or a
   desktop shortcut.
3. Allow the port through Windows Firewall the first time it asks.

Both tills share one set of stock. The system locks each batch while a sale is being
written, so two cashiers cannot sell the same last packet.

---

## Backup — read this part

Everything is in **`db.sqlite3`** in this folder. That single file is the shop.

- Use **Setup → Backup** at the end of every trading day.
- Then copy the backup file onto a flash disk that does **not** live in the shop.

A backup taken and left on the same machine protects against nothing.

---

## For whoever maintains it

Django 6 on SQLite, plain JavaScript at the till, no build step and no CDN.

```
smms/           settings and URLs
shop/           users, roles, shop details, backup
inventory/      products, categories, units, suppliers, purchases, batches, movements
sales/          till, receipts, customers; services.py holds the money rules
reports/        every report, all read-only
templates/      one base template, one stylesheet
```

`sales/services.py` is the important file. `record_sale`, `receive_purchase`,
`adjust_stock` and `write_off_batch` are the only functions that may change stock, and
each runs in a single database transaction. Views call them; views never touch stock
themselves.

Run the tests before handing over any change:

```
venv\Scripts\python.exe manage.py test
```

Useful commands:

```
manage.py setup_shop --company "Nakawa Super Store"   # first-run setup
manage.py load_demo                                    # demo data for showing a client
```

`load_demo` writes fake sales — never run it on a real shop's database.
