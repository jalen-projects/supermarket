"""
The product list MAQAM actually sent (2 Oct 2026), and what Excel had done to it.

Their CSV refused 74 of 595 rows. Almost all of them were the file's fault, not
the shop's: expiry written the way packets print it ("Sept-29"), and Excel
rounding every long barcode into 6.00962E+12 when the list was saved as CSV.
These tests pin each repair, and the one thing that must never happen: a
barcode Excel has damaged going onto a product, where the scanner would never
find it.
"""
import io
import zipfile
from datetime import date

from django.test import TestCase

from inventory.importer import plan, read_rows


def csv_bytes(*lines):
    return ("\n".join(lines) + "\n").encode("latin-1")


HEAD = "Name,Barcode+B2B1,Category,Unit,Buying price,Selling price,Quantity,Expiry,Reorder level"


def xlsx_bytes(rows):
    """A minimal real .xlsx: strings shared, numbers as numbers."""
    shared, sheet_rows = [], []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                shared.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
        sheet_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml",
                   f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>'
                   f'<sheet name="Stock" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml",
                   f'<sst xmlns="{main}">' + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml",
                   f'<worksheet xmlns="{main}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    return buf.getvalue()


def checked(data):
    records, fields = read_rows(data)
    return plan(records), fields


class MaqamListTests(TestCase):
    def test_excels_heading_with_a_formula_address_is_still_the_barcode(self):
        _, fields = checked(csv_bytes(HEAD, "Fanta 500ml,40822938,beverages,piece,1250,2000,96,03/12/2026,20"))
        self.assertIn("barcode", fields)

    def test_month_and_year_expiry_means_the_end_of_that_month(self):
        plans, _ = checked(csv_bytes(
            HEAD,
            "Ankit Bourbon 175g,,biscuits,piece,1000,1500,10,Sept-29,0",
            "CHEKS Orange 100g,,biscuits,piece,1000,1500,10,Feb-28,0",
            "Blue Band,,spreads,piece,1000,1500,10,Nov 2027,0"))
        self.assertEqual([p.errors for p in plans], [[], [], []])
        self.assertEqual(plans[0].data["expiry"], date(2029, 9, 30))
        self.assertEqual(plans[1].data["expiry"], date(2028, 2, 29))
        self.assertEqual(plans[2].data["expiry"], date(2027, 11, 30))

    def test_a_barcode_excel_has_damaged_is_never_put_on_a_product(self):
        plans, _ = checked(csv_bytes(
            HEAD, "Rwenzori 1.5l,6.00962E+12,beverages,piece,1541.66,2500,240,10/03/2027,50"))
        row = plans[0]
        self.assertTrue(row.ok)
        self.assertIsNone(row.data["barcode"])
        self.assertTrue(any("damaged by Excel" in w for w in row.warnings))

    def test_a_repeated_barcode_does_not_cost_the_product(self):
        plans, _ = checked(csv_bytes(
            HEAD,
            "Coca cola 330ml,87303438,beverages,piece,833,1500,120,01/01/2027,20",
            "Schweppes 330ml,87303438,beverages,piece,833,1500,60,01/01/2027,20"))
        self.assertTrue(all(p.ok for p in plans))
        self.assertEqual(plans[0].data["barcode"], "87303438")
        self.assertIsNone(plans[1].data["barcode"])
        self.assertTrue(any("also on row 2" in w for w in plans[1].warnings))

    def test_words_in_the_barcode_column_are_not_a_barcode(self):
        plans, _ = checked(csv_bytes(
            HEAD, "Cussons lotion,baby products,baby,piece,5000,7000,5,,0"))
        self.assertTrue(plans[0].ok)
        self.assertIsNone(plans[0].data["barcode"])

    def test_a_number_excel_turned_into_a_date_says_so(self):
        plans, _ = checked(csv_bytes(
            HEAD, "Pepsi 2L,,beverages,piece,3583.33,5000,02/01/1900,,0"))
        self.assertIn("Excel has turned it into a date", plans[0].errors[0])

    def test_a_real_typing_mistake_is_still_refused(self):
        plans, _ = checked(csv_bytes(
            HEAD, "Nivana 1.5l,,beverages,piece,1500,2500,10,3-89-2026,0"))
        self.assertFalse(plans[0].ok)


class ExcelFileTests(TestCase):
    def test_the_excel_file_itself_keeps_every_barcode_and_date(self):
        data = xlsx_bytes([
            ["Name", "Barcode", "Category", "Unit", "Buying price", "Selling price",
             "Quantity", "Expiry", "Reorder level"],
            ["Rwenzori 1.5l", 6009620000123, "beverages", "piece", 1541.66, 2500, 240,
             46821, 50],
            ["Pepsi 2L", 6001234567890, "beverages", "piece", 3583.33, 5000, 2, "Sept-29", 0],
        ])
        plans, fields = checked(data)
        self.assertIn("barcode", fields)
        self.assertEqual(plans[0].data["barcode"], "6009620000123")
        self.assertEqual(plans[0].data["expiry"], date(2028, 3, 9))
        self.assertEqual(str(plans[0].data["buying_price"]), "1541.66")
        self.assertEqual(plans[1].data["quantity"], 2)
        self.assertEqual(plans[1].data["expiry"], date(2029, 9, 30))
        self.assertTrue(all(p.ok for p in plans))

    def test_a_broken_excel_file_is_refused_politely(self):
        from inventory.importer import ImportProblem
        with self.assertRaises(ImportProblem):
            read_rows(b"PK\x03\x04 not really a zip")


class MistypedYearTests(TestCase):
    def test_a_year_like_6202_is_refused_not_believed(self):
        plans, _ = checked(csv_bytes(
            HEAD, "Mountain dew 500ml,,beverages,piece,1250,2000,98,30/11/6202,20"))
        self.assertFalse(plans[0].ok)
        self.assertIn("mistyped", plans[0].errors[0])


class StockEntrySheetTests(TestCase):
    def setUp(self):
        from shop.models import User
        self.owner = User.objects.create_user("owner", password="pw", role=User.Role.ADMIN)
        self.client.force_login(self.owner)

    def test_the_template_is_the_excel_sheet_and_reads_back_clean(self):
        from django.urls import reverse
        response = self.client.get(reverse("product_import_template"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])
        data = b"".join(response.streaming_content)
        records, fields = read_rows(data)
        self.assertEqual(records, [])
        self.assertTrue({"name", "barcode", "expiry", "quantity"} <= set(fields))

    def test_the_csv_template_is_still_there_for_anyone_without_excel(self):
        from django.urls import reverse
        response = self.client.get(reverse("product_import_template") + "?format=csv")
        self.assertEqual(response["Content-Type"], "text/csv")
