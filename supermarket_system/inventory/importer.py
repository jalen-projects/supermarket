"""Reading a shop's existing product list out of a spreadsheet.

A supermarket going live has hundreds of lines already written down somewhere -
in an exercise book, in Excel, or in the system it is replacing. Typing those
in one product at a time is a day of work nobody has, and it is the first thing
abandoned when the shop gets busy. So the list is read in bulk.

The file is never trusted. Everything is parsed defensively and reported back
before a single row is written, because the person doing the import is standing
in a shop with the owner watching, and a half-finished import that has to be
unpicked by hand is worse than one that refused to start.
"""
import csv
import io
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from sales.services import adjust_stock

from .models import Category, Product, StockMovement, Unit


class ImportProblem(Exception):
    """Something about the file itself means no row can be read."""


# What we accept as a heading for each field. Spreadsheets in the wild are
# never headed the way the documentation says, and rejecting a file because it
# says "Item" instead of "name" just means the file gets retyped by hand.
COLUMNS = {
    "name": ["name", "product", "product name", "item", "item name", "description",
             "particulars", "goods"],
    "barcode": ["barcode", "bar code", "code", "sku", "item code", "product code"],
    "category": ["category", "catergory", "group", "type", "section", "department"],
    "unit": ["unit", "units", "measurement", "measurements", "uom", "measure"],
    "buying_price": ["buying price", "buy price", "cost", "cost price",
                     "purchase price", "buying", "bp"],
    "selling_price": ["selling price", "sell price", "price", "retail price",
                      "sale price", "selling", "sp", "unit price"],
    "quantity": ["quantity", "qty", "stock", "opening stock", "opening quantity",
                 "balance", "on hand", "in stock"],
    "expiry": ["expiry", "expiry date", "expires", "best before", "exp"],
    "reorder_level": ["reorder level", "reorder", "minimum", "min stock",
                      "re order level"],
}

TEMPLATE_HEADERS = ["Name", "Barcode", "Category", "Unit", "Buying price",
                    "Selling price", "Quantity", "Expiry", "Reorder level"]

TEMPLATE_SAMPLE = [
    ["Blue Band 250g", "6009510800012", "Spreads", "Piece",
     "9500", "11000", "24", "2027-04-30", "6"],
    ["Sugar (Kakira) 1kg", "", "Cereals and Sugar", "Kg",
     "4200", "5000", "60", "", "10"],
    ["Mukwano Cooking Oil 3L", "6001085000131", "Cooking oil", "Piece",
     "27000", "31000", "8", "", "3"],
]


def _clean(value):
    return ("" if value is None else str(value)).strip()


def _norm(value):
    """Lower-case, drop bracketed notes and punctuation, collapse spaces - so
    that "Buying Price (UGX)" and "buying_price" land on the same field."""
    text = _clean(value).lower()
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_ALIASES = {field: {_norm(a) for a in aliases} for field, aliases in COLUMNS.items()}


def map_headings(headings):
    """Work out which column of the file is which field. Returns {field: index}."""
    found = {}
    for index, raw in enumerate(headings):
        norm = _norm(raw)
        if not norm:
            continue
        for field, aliases in _ALIASES.items():
            if field not in found and norm in aliases:
                found[field] = index
                break
        else:
            # Excel sometimes leaves a formula's address in a heading
            # ("Barcode+B2B1"); the first word still says what the column is.
            first = norm.split(" ")[0]
            for field, aliases in _ALIASES.items():
                if field not in found and len(first) > 3 and first in aliases:
                    found[field] = index
                    break
    return found


def _not_a_number(raw):
    """Why a figure was refused. Excel quietly turns a number into a date when
    a cell is formatted as one ("2" becomes "02/01/1900"), and that is worth
    saying, because otherwise the file looks right and the error looks wrong."""
    if re.search(r"\d{1,2}[/-]\d{1,2}[/-](18|19)\d\d|^[A-Za-z]{3}-\d\d$", raw):
        return (f"is not a number - Excel has turned it into a date ({raw}). "
                f"Retype the number in that cell")
    return "is not a number"


def parse_money(value):
    """"UGX 12,500.00" or "12 500" becomes a Decimal. Blank becomes None.

    The thousands separator is stripped before parsing. A Ugandan price list
    written as 12,500 must never be read as twelve and a half shillings.
    """
    raw = _clean(value)
    if not raw:
        return None
    raw = re.sub(r"(?i)\b(ugx|ush|shs|shillings?)\b", "", raw)
    raw = raw.replace(",", "").replace(" ", "").strip()
    if not raw:
        return None
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise ValueError(_not_a_number(raw))
    if amount < 0:
        raise ValueError("cannot be negative")
    return amount


def parse_quantity(value):
    raw = _clean(value).replace(",", "").replace(" ", "")
    if not raw:
        return None
    try:
        quantity = Decimal(raw)
    except InvalidOperation:
        raise ValueError(_not_a_number(raw))
    if quantity < 0:
        raise ValueError("cannot be negative")
    return quantity


# Day-first on purpose: 03/04/2027 is the 3rd of April in Uganda, not the 4th
# of March. Reading it the American way would either pull good stock off the
# shelf a month early or, far worse, leave expired goods on sale for a month.
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%Y",
                "%d %b %Y", "%d %B %Y", "%Y/%m/%d"]
# Month and year only, as most packets print it: "04/2027", "Apr 2027", and the
# way a shop types it into Excel, "Sept-29" or "Feb-29" (two-digit years).
MONTH_FORMATS = ["%b %Y", "%B %Y", "%m/%Y", "%m-%Y", "%b-%y", "%B-%y",
                 "%b %y", "%B %y", "%b-%Y", "%B-%Y", "%b/%y", "%b/%Y"]


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = _clean(value)
    if not raw:
        return None
    # A date cell read straight from an Excel file arrives as Excel's day
    # number (46000 is late 2025). Only a number in the range of real expiry
    # dates is taken that way; a stray "12" is still refused below.
    if re.fullmatch(r"\d{5}(\.0+)?", raw) and 36500 <= float(raw) <= 73000:
        return date(1899, 12, 30) + timedelta(days=int(float(raw)))
    # "Sept" is how a shop writes September; strptime only knows "Sep".
    raw = re.sub(r"(?i)\bsept\b", "Sep", raw)
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        # 30/11/6202 is a perfectly good date to Python and a slip of the
        # fingers to everybody else (MAQAM's list, 2 Oct 2026). Taken as
        # written, that product would never show as expiring.
        if not 2000 <= parsed.year <= 2100:
            raise ValueError(f"has a year that looks mistyped ({raw})")
        return parsed
    # "04/2027" on a packet means it is good to the END of that month.
    for fmt in MONTH_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        following = date(parsed.year + (parsed.month == 12),
                         (parsed.month % 12) + 1, 1)
        return date.fromordinal(following.toordinal() - 1)
    raise ValueError("is not a date I can read (write it as 2027-04-30)")


def read_xlsx_rows(file_bytes):
    """The first sheet of an Excel .xlsx file, as rows of text.

    WHY THE EXCEL FILE ITSELF IS READ. Saving a product list "as CSV" is where
    it gets damaged: Excel writes a 13-digit barcode as 6.00962E+12, throwing
    the real digits away, and writes a quantity cell formatted as a date as
    "02/01/1900". Inside the .xlsx every value is still exact. Read with the
    standard library only - the shop PC installs offline, so no extra package.

    Numbers come out as plain digits (a barcode stays 6009620000123, not
    6.0096E+12); a date cell comes out as Excel's day number, which the expiry
    column understands (see parse_date).
    """
    import zipfile
    from xml.etree import ElementTree as ET

    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
          "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
    try:
        book = zipfile.ZipFile(io.BytesIO(file_bytes))
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels.findall("rel:Relationship", ns)}
        sheets = []
        for entry in workbook.findall("m:sheets/m:sheet", ns):
            target = targets[entry.get(f"{{{ns['r']}}}id")].lstrip("/")
            sheets.append(ET.fromstring(book.read(
                target if target.startswith("xl/") else f"xl/{target}")))
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            for si in ET.fromstring(book.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
    except (zipfile.BadZipFile, KeyError, StopIteration, AttributeError, ET.ParseError):
        raise ImportProblem(
            "That Excel file could not be opened. Save it again in Excel as an "
            ".xlsx workbook, or as CSV, and upload that.")

    def column(ref):
        letters = re.match(r"[A-Z]+", ref or "A").group(0)
        number = 0
        for letter in letters:
            number = number * 26 + (ord(letter) - 64)
        return number - 1

    def number_text(raw):
        try:
            value = Decimal(raw)
        except InvalidOperation:
            return raw
        if value == value.to_integral_value():
            return str(int(value))
        return format(value.normalize(), "f")

    def sheet_rows(sheet):
        rows = []
        for row in sheet.iter(f"{{{ns['m']}}}row"):
            cells = {}
            for cell in row.findall("m:c", ns):
                kind = cell.get("t")
                value = cell.find("m:v", ns)
                text = value.text if value is not None and value.text is not None else ""
                if kind == "s" and text:
                    text = shared[int(text)]
                elif kind == "inlineStr":
                    text = "".join(t.text or "" for t in cell.iter(f"{{{ns['m']}}}t"))
                elif kind in (None, "n") and text:
                    text = number_text(text)
                cells[column(cell.get("r"))] = text
            if cells and any(_clean(v) for v in cells.values()):
                rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        return rows

    # The list is on whichever tab has a Name heading in its first row - a
    # workbook often opens with instructions or a cover sheet.
    first_rows = [sheet_rows(sheet) for sheet in sheets]
    for rows in first_rows:
        if rows and "name" in map_headings(rows[0]):
            return rows
    return first_rows[0] if first_rows else []


def read_rows(file_bytes):
    """Turn uploaded bytes into a list of dicts, one per spreadsheet row.

    Excel writes CSV with a byte-order mark and, depending on the machine's
    regional settings, often with semicolons rather than commas. Both are
    handled, because "save as CSV" is the only export a shop owner can manage.
    """
    if file_bytes[:2] == b"PK":
        rows = read_xlsx_rows(file_bytes)
        return _records(rows)

    text = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ImportProblem(
            "That file is not a spreadsheet I can read. In Excel use "
            "File - Save As - CSV (Comma delimited), then upload that.")

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    rows = list(csv.reader(io.StringIO(text), dialect))
    return _records(rows)


def _records(rows):
    """Headings row plus data rows -> (records, fields found)."""
    rows = [r for r in rows if any(_clean(c) for c in r)]
    if not rows:
        raise ImportProblem("That file is empty.")

    mapping = map_headings(rows[0])
    if "name" not in mapping:
        raise ImportProblem(
            "I cannot find a product name column. The first row of the file "
            "must be headings, and one of them must say Name (or Product, or "
            "Item). If that is awkward, download the template below and paste "
            "the list into it.")

    records = []
    for number, row in enumerate(rows[1:], start=2):
        record = {"_row": number}
        for field, index in mapping.items():
            record[field] = row[index] if index < len(row) else ""
        records.append(record)
    return records, sorted(mapping)


class PlannedRow:
    """One row of the file, checked, with what would happen spelled out."""

    def __init__(self, row_number, name):
        self.row = row_number
        self.name = name
        self.action = "create"          # create | update
        self.errors = []
        self.warnings = []
        self.product = None
        self.data = {}

    @property
    def ok(self):
        return not self.errors

    def __str__(self):
        return f"row {self.row}: {self.name}"


WEIGHED_UNITS = {"kg", "kilogram", "kilogramme", "g", "gram", "grams", "litre",
                 "liter", "litres", "l", "ml", "metre", "meter", "m"}


def plan(records, *, add_stock_to_existing=False, default_unit="Piece",
         default_category="General", require_barcode=False):
    """Check every row and describe what the import would do. Writes nothing.

    This is what gets read out to the shop owner before committing, so it must
    name the row number of anything wrong: "line 47" is findable in a
    spreadsheet, "a product" is not.
    """
    plans = []
    seen_names = {}
    seen_barcodes = {}
    today = timezone.localdate()

    for record in records:
        name = _clean(record.get("name"))
        row = PlannedRow(record["_row"], name)

        if not name:
            row.errors.append("no product name")
            plans.append(row)
            continue

        for field, parser, label in (
            ("buying_price", parse_money, "Buying price"),
            ("selling_price", parse_money, "Selling price"),
            ("quantity", parse_quantity, "Quantity"),
            ("reorder_level", parse_quantity, "Reorder level"),
            ("expiry", parse_date, "Expiry"),
        ):
            try:
                row.data[field] = parser(record.get(field))
            except ValueError as exc:
                row.errors.append(f"{label} {exc}")
                row.data[field] = None

        barcode = _clean(record.get("barcode")) or None
        if barcode and re.fullmatch(r"\d+(\.\d+)?[eE][+]\d+", barcode):
            # 6.00962E+12: Excel has rounded the barcode away when the file was
            # saved as CSV. The real digits are gone; importing this would put
            # a WRONG barcode on the product and the scanner would never find
            # it. The product comes in without one.
            row.warnings.append(
                f"barcode {barcode} was damaged by Excel - imported without a "
                f"barcode (upload the Excel file itself to keep barcodes, or "
                f"scan it in later under Stock capture)")
            barcode = None
        elif barcode and re.fullmatch(r"\d+\.0+", barcode):
            barcode = barcode.split(".")[0]
        row.data["name"] = name
        row.data["barcode"] = barcode
        row.data["category"] = _clean(record.get("category")) or default_category
        row.data["unit"] = _clean(record.get("unit")) or default_unit

        # Duplicates WITHIN the file. Two rows sharing a barcode would make the
        # second silently overwrite the first.
        key = name.lower()
        if key in seen_names:
            row.warnings.append(f"same name as row {seen_names[key]}")
        seen_names.setdefault(key, row.row)
        # A barcode is one word. Words with spaces in that column ("baby
        # products") are something typed in the wrong column, not a barcode.
        if barcode and " " in barcode:
            row.warnings.append(
                f"\"{barcode}\" in the barcode column is not a barcode - "
                f"imported without one")
            barcode = None
        # The same barcode twice: one of the two is wrong, and only a person
        # holding the packets can say which. The first keeps it; the second
        # comes in WITHOUT a barcode rather than not at all - its name, prices
        # and stock are still right, and the barcode can be scanned in later.
        if barcode and barcode in seen_barcodes:
            row.warnings.append(
                f"barcode {barcode} is also on row {seen_barcodes[barcode]} - "
                f"imported without a barcode; check which product it belongs to")
            barcode = None
        if barcode:
            seen_barcodes.setdefault(barcode, row.row)
        row.data["barcode"] = barcode
        # The owner's rule at MAQAM (2 Oct 2026): nothing goes on the shelf
        # in the system without a barcode, because a product the scanner
        # cannot find gets typed in by hand - or sold at the wrong price.
        if require_barcode and not barcode:
            row.errors.append("has no barcode - scan it into the Barcode column")

        existing = Product.objects.filter(barcode=barcode).first() if barcode else None
        if existing is None:
            existing = Product.objects.filter(name__iexact=name).first()
        if existing is not None:
            row.product = existing
            row.action = "update"
            if row.data.get("quantity") and not add_stock_to_existing:
                row.warnings.append(
                    "already in the system - prices updated, but the quantity in "
                    "the file was NOT added to stock")

        buying = row.data.get("buying_price")
        selling = row.data.get("selling_price")
        if row.action == "create" and selling is None:
            row.warnings.append(
                "no selling price - it will be created at 0, fix before selling")
        if buying is not None and selling not in (None, Decimal("0")) and buying > selling:
            row.warnings.append("selling price is LOWER than the buying price")

        expiry = row.data.get("expiry")
        if expiry and expiry < today:
            row.warnings.append(f"expiry {expiry} has already passed")

        plans.append(row)

    return plans


@transaction.atomic
def apply_plan(plans, *, user, add_stock_to_existing=False):
    """Write the checked rows. All of them, or none of them.

    A part-done import is the worst outcome: nobody knows which half of the
    spreadsheet went in, so the only safe fix is to delete everything and start
    again. One transaction removes that situation entirely.
    """
    good = [p for p in plans if p.ok]
    if not good:
        raise ImportProblem(
            "Nothing in that file can be imported. Fix the errors and try again.")

    categories = {}
    units = {}
    created = updated = stocked = 0

    for row in good:
        data = row.data

        cat_key = data["category"].lower()
        if cat_key not in categories:
            category = Category.objects.filter(name__iexact=data["category"]).first()
            if category is None:
                category = Category.objects.create(name=data["category"])
            categories[cat_key] = category
        category = categories[cat_key]

        unit_key = data["unit"].lower()
        if unit_key not in units:
            unit = (Unit.objects.filter(name__iexact=data["unit"]).first()
                    or Unit.objects.filter(abbreviation__iexact=data["unit"]).first())
            if unit is None:
                # Weighed goods must allow decimals, or half a kilo of sugar
                # cannot be sold at all.
                unit = Unit.objects.create(
                    name=data["unit"], abbreviation=data["unit"][:10],
                    allow_decimals=unit_key in WEIGHED_UNITS)
            units[unit_key] = unit
        unit = units[unit_key]

        product = row.product
        if product is None:
            product = Product.objects.create(
                name=data["name"], barcode=data["barcode"], category=category,
                unit=unit,
                buying_price=data.get("buying_price") or Decimal("0"),
                selling_price=data.get("selling_price") or Decimal("0"),
                reorder_level=data.get("reorder_level"))
            created += 1
        else:
            fields = []
            for field in ("buying_price", "selling_price", "reorder_level"):
                if data.get(field) is not None:
                    setattr(product, field, data[field])
                    fields.append(field)
            if data.get("barcode") and not product.barcode:
                product.barcode = data["barcode"]
                fields.append("barcode")
            if fields:
                product.save(update_fields=fields)
            updated += 1

        quantity = data.get("quantity")
        if quantity and quantity > 0 and (row.action == "create" or add_stock_to_existing):
            adjust_stock(
                product=product, quantity=quantity,
                kind=StockMovement.Kind.OPENING,
                reason="Opening stock from the imported product list",
                user=user, buying_price=data.get("buying_price"),
                expiry_date=data.get("expiry"), reference="IMPORT")
            stocked += 1

    return {"created": created, "updated": updated, "stocked": stocked,
            "skipped": len(plans) - len(good)}


def template_csv():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(TEMPLATE_HEADERS)
    writer.writerows(TEMPLATE_SAMPLE)
    return buffer.getvalue()
