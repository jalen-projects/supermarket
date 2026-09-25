"""Checks on the three things built for the day the shop goes live.

Named after the visit rather than after the models, like
tests_client_questions.py, because each of these exists to answer something
the shop actually has to do on the first day: hand over a drawer, get the
product list onto the system, and still have the data tomorrow.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from inventory import importer
from inventory.models import Category, Product, StockMovement, Unit
from sales.models import Sale, Shift
from sales.services import close_shift, current_shift, open_shift, record_sale

from .tests import ShopTestCase


# ---------------------------------------------------------------------------
# Cashing up - the control that protects the owner's money
# ---------------------------------------------------------------------------
class CashUpTests(ShopTestCase):
    def sell(self, product, quantity=1, user=None, method=Sale.Payment.CASH, price="1500"):
        return record_sale(
            user=user or self.cashier,
            lines=[{"product": product, "quantity": Decimal(str(quantity)),
                    "unit_price": Decimal(price)}],
            payment_method=method, amount_paid=Decimal("100000"))

    def test_a_drawer_opens_by_itself_on_the_first_sale(self):
        """A cashier must never be able to sell into no shift - if they could,
        the money from that sale would belong to nobody."""
        product = self.make_product()
        self.deliver(product, 10)
        self.assertEqual(Shift.objects.count(), 0)

        sale = self.sell(product)

        self.assertEqual(Shift.objects.count(), 1)
        self.assertIsNotNone(sale.shift)
        self.assertEqual(sale.shift.user, self.cashier)
        self.assertTrue(sale.shift.is_open)

    def test_a_cashier_only_ever_has_one_drawer_open(self):
        product = self.make_product()
        self.deliver(product, 10)
        first = current_shift(self.cashier)
        self.sell(product)
        self.sell(product)
        self.assertEqual(
            Shift.objects.filter(user=self.cashier, status=Shift.Status.OPEN).count(), 1)
        self.assertEqual(current_shift(self.cashier).pk, first.pk)

    def test_two_cashiers_keep_separate_drawers(self):
        """Two tills is the whole reason this exists. One cashier's shortage
        must never show up against the other."""
        product = self.make_product()
        self.deliver(product, 20)

        self.sell(product, user=self.cashier)
        self.sell(product, user=self.owner)

        cashier_shift = current_shift(self.cashier)
        owner_shift = current_shift(self.owner)
        self.assertNotEqual(cashier_shift.pk, owner_shift.pk)
        self.assertEqual(cashier_shift.cash_sales, Decimal("1500.00"))
        self.assertEqual(owner_shift.cash_sales, Decimal("1500.00"))

    def test_expected_cash_is_the_float_plus_cash_sales_only(self):
        """Mobile money and credit never reach the drawer. Counting them as
        expected would accuse an honest cashier of being short."""
        product = self.make_product()
        self.deliver(product, 50)
        shift = open_shift(user=self.cashier, opening_float=Decimal("50000"))

        self.sell(product, method=Sale.Payment.CASH)      # 1500 cash
        self.sell(product, method=Sale.Payment.MOBILE)    # 1500 mobile
        self.sell(product, method=Sale.Payment.CREDIT)    # 1500 credit

        shift.refresh_from_db()
        self.assertEqual(shift.cash_sales, Decimal("1500.00"))
        self.assertEqual(shift.mobile_sales, Decimal("1500.00"))
        self.assertEqual(shift.credit_sales, Decimal("1500.00"))
        self.assertEqual(shift.expected_cash, Decimal("51500.00"))
        self.assertEqual(shift.total_sales, Decimal("4500.00"))

    def test_a_short_drawer_is_reported_short_and_not_quietly_fixed(self):
        product = self.make_product()
        self.deliver(product, 50)
        shift = open_shift(user=self.cashier, opening_float=Decimal("10000"))
        self.sell(product)                       # expected 11,500

        close_shift(shift=shift, counted_cash=Decimal("9500"),
                    closed_by=self.owner, note="drawer was short")

        shift.refresh_from_db()
        self.assertEqual(shift.expected_cash, Decimal("11500.00"))
        self.assertEqual(shift.counted_cash, Decimal("9500.00"))
        self.assertEqual(shift.variance, Decimal("-2000.00"))
        self.assertTrue(shift.is_short)
        self.assertFalse(shift.is_balanced)
        self.assertFalse(shift.is_open)

    def test_a_balanced_drawer_reads_as_balanced(self):
        product = self.make_product()
        self.deliver(product, 50)
        shift = open_shift(user=self.cashier, opening_float=Decimal("10000"))
        self.sell(product)
        close_shift(shift=shift, counted_cash=Decimal("11500"), closed_by=self.owner)
        shift.refresh_from_db()
        self.assertEqual(shift.variance, Decimal("0.00"))
        self.assertTrue(shift.is_balanced)
        self.assertFalse(shift.is_short)

    def test_closing_a_drawer_twice_is_refused(self):
        """Otherwise a second count could overwrite a shortage that was
        already recorded against someone."""
        shift = current_shift(self.cashier)
        close_shift(shift=shift, counted_cash=Decimal("0"), closed_by=self.owner)
        with self.assertRaises(ValueError):
            close_shift(shift=shift, counted_cash=Decimal("5000"), closed_by=self.owner)

    def test_a_new_drawer_opens_after_the_last_one_was_handed_over(self):
        product = self.make_product()
        self.deliver(product, 10)
        first = current_shift(self.cashier)
        close_shift(shift=first, counted_cash=Decimal("0"), closed_by=self.owner)

        self.sell(product)

        second = current_shift(self.cashier)
        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(Shift.objects.filter(user=self.cashier).count(), 2)

    def test_a_voided_sale_is_counted_and_shown_to_the_owner(self):
        """Ring it up, take the money, void it - the oldest way to empty a
        till. The count has to be visible on the cash-up sheet."""
        product = self.make_product()
        self.deliver(product, 10)
        sale = self.sell(product)
        shift = sale.shift
        sale.void(self.cashier, reason="changed mind")

        shift.refresh_from_db()
        self.assertEqual(shift.voided_count, 1)
        self.assertEqual(shift.cash_sales, Decimal("0"))

    def test_a_cashier_is_not_shown_what_the_drawer_should_hold(self):
        """A cashier who can see the target writes down the target, and the
        control is worth nothing."""
        self.client.login(username="cashier", password="pw12345")
        response = self.client.get(reverse("cash_up"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_expected"])

    def test_the_owner_is_shown_the_expected_figure(self):
        self.client.login(username="owner", password="pw12345")
        response = self.client.get(reverse("cash_up"))
        self.assertTrue(response.context["show_expected"])

    def test_a_cashier_cannot_open_someone_elses_cash_up_sheet(self):
        other = current_shift(self.owner)
        self.client.login(username="cashier", password="pw12345")
        response = self.client.get(reverse("shift_detail", args=[other.pk]))
        self.assertEqual(response.status_code, 403)

    def test_only_the_owner_sees_the_shortages_report(self):
        self.client.login(username="cashier", password="pw12345")
        self.assertEqual(self.client.get(reverse("shift_list")).status_code, 403)
        self.client.login(username="owner", password="pw12345")
        self.assertEqual(self.client.get(reverse("shift_list")).status_code, 200)

    def test_cashing_up_through_the_screen_records_the_count(self):
        product = self.make_product()
        self.deliver(product, 10)
        self.sell(product)
        self.client.login(username="cashier", password="pw12345")

        response = self.client.post(
            reverse("cash_up"), {"counted_cash": "1500", "note": "all good"})

        shift = Shift.objects.get(user=self.cashier)
        self.assertRedirects(response, reverse("shift_detail", args=[shift.pk]))
        self.assertEqual(shift.counted_cash, Decimal("1500.00"))
        self.assertEqual(shift.variance, Decimal("0.00"))


# ---------------------------------------------------------------------------
# Reading the product list out of a spreadsheet
# ---------------------------------------------------------------------------
class ImportParsingTests(TestCase):
    def test_ugandan_prices_with_thousands_separators_are_read_correctly(self):
        """12,500 is twelve and a half thousand shillings, never twelve and a
        half. Getting this wrong misprices the whole shop."""
        self.assertEqual(importer.parse_money("12,500"), Decimal("12500"))
        self.assertEqual(importer.parse_money("UGX 12,500.00"), Decimal("12500.00"))
        self.assertEqual(importer.parse_money("12 500"), Decimal("12500"))
        self.assertEqual(importer.parse_money("shs 900"), Decimal("900"))
        self.assertIsNone(importer.parse_money(""))

    def test_a_price_that_is_not_a_number_is_rejected_not_guessed(self):
        with self.assertRaises(ValueError):
            importer.parse_money("ask the boss")
        with self.assertRaises(ValueError):
            importer.parse_money("-500")

    def test_dates_are_read_day_first(self):
        """03/04/2027 is the 3rd of April here. Read the American way it would
        leave expired goods on sale for a month."""
        self.assertEqual(importer.parse_date("03/04/2027"), date(2027, 4, 3))
        self.assertEqual(importer.parse_date("2027-04-30"), date(2027, 4, 30))
        self.assertEqual(importer.parse_date("30-04-2027"), date(2027, 4, 30))

    def test_a_month_only_expiry_means_the_end_of_that_month(self):
        """Packets are stamped 04/2027, and that means good until the 30th."""
        self.assertEqual(importer.parse_date("04/2027"), date(2027, 4, 30))
        self.assertEqual(importer.parse_date("Feb 2028"), date(2028, 2, 29))

    def test_headings_are_matched_however_the_shop_wrote_them(self):
        mapping = importer.map_headings(
            ["Item Name", "Bar Code", "Buying Price (UGX)", "SELLING PRICE", "Qty"])
        self.assertEqual(mapping["name"], 0)
        self.assertEqual(mapping["barcode"], 1)
        self.assertEqual(mapping["buying_price"], 2)
        self.assertEqual(mapping["selling_price"], 3)
        self.assertEqual(mapping["quantity"], 4)

    def test_a_semicolon_file_from_excel_is_read(self):
        raw = "Name;Selling price;Qty\r\nSoap;3000;5\r\n".encode("utf-8-sig")
        records, columns = importer.read_rows(raw)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "Soap")
        self.assertIn("selling_price", columns)

    def test_an_xlsx_file_is_refused_with_an_instruction_not_a_stack_trace(self):
        with self.assertRaises(importer.ImportProblem) as caught:
            importer.read_rows(b"PK\x03\x04rest of a zip")
        self.assertIn("Save As", str(caught.exception))

    def test_a_file_with_no_name_column_is_refused(self):
        with self.assertRaises(importer.ImportProblem):
            importer.read_rows(b"Price,Qty\n1000,5\n")


class ImportApplyTests(ShopTestCase):
    def rows(self, text):
        records, _ = importer.read_rows(text.encode("utf-8"))
        return records

    def test_a_product_list_becomes_products_with_opening_stock(self):
        records = self.rows(
            "Name,Category,Unit,Buying price,Selling price,Quantity\n"
            "Blue Band 250g,Spreads,Piece,9500,11000,24\n"
            "Omo 500g,Soap,Piece,4000,5000,10\n")
        plans = importer.plan(records)
        self.assertTrue(all(p.ok for p in plans))

        result = importer.apply_plan(plans, user=self.owner)

        self.assertEqual(result["created"], 2)
        self.assertEqual(result["stocked"], 2)
        blueband = Product.objects.get(name="Blue Band 250g")
        self.assertEqual(blueband.selling_price, Decimal("11000.00"))
        self.assertEqual(blueband.stock_available, Decimal("24.000"))
        self.assertEqual(blueband.category.name, "Spreads")

    def test_opening_stock_from_an_import_is_recorded_as_opening_not_shrinkage(self):
        """An opening balance is not a stock correction, and must not appear
        on the reports as though something went missing."""
        plans = importer.plan(self.rows(
            "Name,Selling price,Quantity\nSugar 1kg,5000,40\n"))
        importer.apply_plan(plans, user=self.owner)
        movement = StockMovement.objects.get(product__name="Sugar 1kg")
        self.assertEqual(movement.kind, StockMovement.Kind.OPENING)

    def test_importing_the_same_file_twice_does_not_double_the_stock(self):
        """The single most damaging mistake available on the first day."""
        text = "Name,Selling price,Quantity\nRice 1kg,4500,30\n"
        importer.apply_plan(importer.plan(self.rows(text)), user=self.owner)
        importer.apply_plan(importer.plan(self.rows(text)), user=self.owner)

        product = Product.objects.get(name="Rice 1kg")
        self.assertEqual(product.stock_available, Decimal("30.000"))
        self.assertEqual(Product.objects.filter(name="Rice 1kg").count(), 1)

    def test_stock_is_added_again_only_when_that_is_asked_for_explicitly(self):
        text = "Name,Selling price,Quantity\nRice 1kg,4500,30\n"
        importer.apply_plan(importer.plan(self.rows(text)), user=self.owner)
        importer.apply_plan(
            importer.plan(self.rows(text), add_stock_to_existing=True),
            user=self.owner, add_stock_to_existing=True)
        self.assertEqual(
            Product.objects.get(name="Rice 1kg").stock_available, Decimal("60.000"))

    def test_two_rows_sharing_a_barcode_are_refused_before_anything_is_written(self):
        plans = importer.plan(self.rows(
            "Name,Barcode,Selling price\nSoap A,12345,3000\nSoap B,12345,3500\n"))
        self.assertTrue(plans[0].ok)
        self.assertFalse(plans[1].ok)
        self.assertIn("already used on row 2", plans[1].errors[0])

    def test_a_bad_row_does_not_stop_the_good_ones(self):
        plans = importer.plan(self.rows(
            "Name,Selling price,Quantity\n"
            "Good Item,5000,10\n"
            ",3000,5\n"
            "Another Good,2000,4\n"))
        result = importer.apply_plan(plans, user=self.owner)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["skipped"], 1)

    def test_nothing_is_written_when_the_whole_file_is_bad(self):
        plans = importer.plan(self.rows("Name,Selling price\n,5000\n"))
        with self.assertRaises(importer.ImportProblem):
            importer.apply_plan(plans, user=self.owner)
        self.assertEqual(Product.objects.count(), 0)

    def test_a_weighed_unit_allows_decimals(self):
        """Without this, half a kilo of sugar cannot be sold at all.

        "Kg" here matches the shop's existing Kilogram unit by its
        abbreviation. Reusing it rather than creating a second, near-identical
        unit is the point.
        """
        importer.apply_plan(
            importer.plan(self.rows("Name,Unit,Selling price\nSugar loose,Kg,5000\n")),
            user=self.owner)
        self.assertTrue(Product.objects.get(name="Sugar loose").unit.allow_decimals)
        self.assertEqual(Unit.objects.filter(abbreviation__iexact="kg").count(), 1)

    def test_a_weighed_unit_the_shop_lacks_is_created_allowing_decimals(self):
        importer.apply_plan(
            importer.plan(self.rows("Name,Unit,Selling price\nParaffin,Litre,4000\n")),
            user=self.owner)
        self.assertTrue(Unit.objects.get(name="Litre").allow_decimals)

    def test_a_counted_unit_does_not_allow_decimals(self):
        """Half a bar of soap is not a thing, and allowing it invites typos."""
        importer.apply_plan(
            importer.plan(self.rows("Name,Unit,Selling price\nSoap bar,Bar,1200\n")),
            user=self.owner)
        self.assertFalse(Unit.objects.get(name="Bar").allow_decimals)

    def test_a_selling_price_below_cost_is_flagged_but_still_imported(self):
        plans = importer.plan(self.rows(
            "Name,Buying price,Selling price\nLoss Leader,5000,4000\n"))
        self.assertTrue(plans[0].ok)
        self.assertTrue(any("LOWER" in w for w in plans[0].warnings))

    def test_an_existing_product_has_its_price_updated_not_duplicated(self):
        self.make_product(name="Soda 500ml", selling="1500")
        plans = importer.plan(self.rows("Name,Selling price\nsoda 500ml,1800\n"))
        self.assertEqual(plans[0].action, "update")
        importer.apply_plan(plans, user=self.owner)
        self.assertEqual(Product.objects.filter(name__iexact="soda 500ml").count(), 1)
        self.assertEqual(
            Product.objects.get(name="Soda 500ml").selling_price, Decimal("1800.00"))

    def test_the_template_can_be_read_back_by_the_importer(self):
        """The template we hand people must not itself fail the check."""
        records, _ = importer.read_rows(importer.template_csv().encode("utf-8"))
        plans = importer.plan(records)
        self.assertEqual(len(plans), 3)
        self.assertTrue(all(p.ok for p in plans), [p.errors for p in plans])


class ImportScreenTests(ShopTestCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="owner", password="pw12345")

    def test_the_preview_writes_nothing(self):
        upload = SimpleUploadedFile(
            "list.csv", b"Name,Selling price,Quantity\nTea leaves,2500,12\n",
            content_type="text/csv")
        response = self.client.post(reverse("product_import"), {"file": upload})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["good"]), 1)
        self.assertEqual(Product.objects.count(), 0)

    def test_confirming_the_preview_writes_the_products(self):
        upload = SimpleUploadedFile(
            "list.csv", b"Name,Selling price,Quantity\nTea leaves,2500,12\n",
            content_type="text/csv")
        preview = self.client.post(reverse("product_import"), {"file": upload})
        token = preview.context["token"]

        self.client.post(reverse("product_import_confirm"), {"token": token})

        product = Product.objects.get(name="Tea leaves")
        self.assertEqual(product.stock_available, Decimal("12.000"))

    def test_a_made_up_token_cannot_read_files_off_the_computer(self):
        for token in ["../../settings", "..", "nonexistent", ""]:
            response = self.client.post(
                reverse("product_import_confirm"), {"token": token})
            self.assertIn(response.status_code, (302, 404))

    def test_a_cashier_cannot_import_products(self):
        self.client.login(username="cashier", password="pw12345")
        self.assertEqual(self.client.get(reverse("product_import")).status_code, 403)


# ---------------------------------------------------------------------------
# Stock capture - the client has no list, so it is built off the shelves
# ---------------------------------------------------------------------------
class StockCaptureTests(ShopTestCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="owner", password="pw12345")

    def test_capturing_an_item_creates_it_with_its_opening_stock(self):
        response = self.client.post(reverse("capture_save"), {
            "barcode": "6009510800012", "name": "Blue Band 250g",
            "category": self.category.pk, "unit": self.piece.pk,
            "buying_price": "9500", "selling_price": "11000", "quantity": "24"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["action"], "created")
        product = Product.objects.get(barcode="6009510800012")
        self.assertEqual(product.selling_price, Decimal("11000.00"))
        self.assertEqual(product.stock_available, Decimal("24.000"))

    def test_scanning_the_same_item_again_tops_it_up_rather_than_failing(self):
        """The same item turns up on another shelf. Refusing it would stop the
        person capturing and send them hunting for the first entry."""
        payload = {"barcode": "555", "name": "Salt 1kg",
                   "category": self.category.pk, "unit": self.piece.pk,
                   "selling_price": "1500", "quantity": "10"}
        self.client.post(reverse("capture_save"), payload)
        response = self.client.post(reverse("capture_save"), payload)

        self.assertEqual(response.json()["action"], "topped up")
        self.assertEqual(Product.objects.filter(barcode="555").count(), 1)
        self.assertEqual(
            Product.objects.get(barcode="555").stock_available, Decimal("20.000"))

    def test_the_lookup_tells_the_screen_what_is_already_known(self):
        product = self.make_product(name="Known item")
        product.barcode = "999"
        product.save()
        self.deliver(product, 7)

        body = self.client.get(reverse("capture_lookup"), {"barcode": "999"}).json()

        self.assertTrue(body["found"])
        self.assertEqual(body["name"], "Known item")
        self.assertEqual(Decimal(body["stock"]), Decimal("7.000"))

    def test_an_unknown_barcode_reports_not_found(self):
        body = self.client.get(reverse("capture_lookup"), {"barcode": "nope"}).json()
        self.assertFalse(body["found"])

    def test_a_new_item_without_a_selling_price_is_refused(self):
        """Capturing it at zero would let the till give it away for nothing."""
        response = self.client.post(reverse("capture_save"), {
            "name": "No price item", "category": self.category.pk,
            "unit": self.piece.pk, "quantity": "5"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(Product.objects.count(), 0)

    def test_a_new_item_without_a_name_is_refused(self):
        response = self.client.post(reverse("capture_save"), {
            "barcode": "777", "selling_price": "1000", "quantity": "1"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Product.objects.count(), 0)

    def test_loose_goods_with_no_barcode_can_still_be_captured(self):
        self.client.post(reverse("capture_save"), {
            "barcode": "", "name": "Loose rice", "category": self.category.pk,
            "unit": self.kg.pk, "selling_price": "4500", "quantity": "25.5"})
        product = Product.objects.get(name="Loose rice")
        self.assertIsNone(product.barcode)
        self.assertEqual(product.stock_available, Decimal("25.500"))

    def test_two_blank_barcodes_do_not_collide(self):
        """Blank must be stored as NULL or the second one breaks the unique index."""
        for name in ("Loose beans", "Loose maize"):
            response = self.client.post(reverse("capture_save"), {
                "barcode": "", "name": name, "category": self.category.pk,
                "unit": self.kg.pk, "selling_price": "3000", "quantity": "10"})
            self.assertTrue(response.json()["ok"], response.content)
        self.assertEqual(Product.objects.filter(barcode__isnull=True).count(), 2)

    def test_prices_typed_with_commas_are_accepted(self):
        self.client.post(reverse("capture_save"), {
            "name": "Cooking oil 3L", "category": self.category.pk,
            "unit": self.piece.pk, "buying_price": "27,000",
            "selling_price": "31,000", "quantity": "8"})
        self.assertEqual(
            Product.objects.get(name="Cooking oil 3L").selling_price, Decimal("31000.00"))

    def test_a_cashier_cannot_open_stock_capture(self):
        self.client.login(username="cashier", password="pw12345")
        self.assertEqual(self.client.get(reverse("capture")).status_code, 403)


# ---------------------------------------------------------------------------
# Backups - the data has to survive the computer
# ---------------------------------------------------------------------------
class BackupTests(ShopTestCase):
    def test_a_backup_is_a_real_readable_database_holding_the_rows(self):
        """Backs up a real file on disk on purpose.

        The test database runs in memory, so calling backup_database() with no
        source here would faithfully copy nothing at all - the test would pass
        while proving nothing, which is the same trap already documented for
        the WAL pragma check.
        """
        import sqlite3
        import tempfile
        from pathlib import Path

        from shop import services

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            live = path / "live.sqlite3"
            connection = sqlite3.connect(live)
            try:
                connection.execute("CREATE TABLE takings (receipt TEXT, amount INTEGER)")
                connection.execute("INSERT INTO takings VALUES ('R260927001', 84000)")
                connection.commit()
            finally:
                connection.close()

            with override_settings(BACKUP_DIR=path / "backups"):
                target = services.backup_database(source=live)
                self.assertTrue(target.exists())
                reader = sqlite3.connect(target)
                try:
                    rows = list(reader.execute("SELECT receipt, amount FROM takings"))
                finally:
                    reader.close()

        self.assertEqual(rows, [("R260927001", 84000)])

    def test_old_backups_are_pruned_so_the_shop_disk_does_not_fill(self):
        import tempfile
        from pathlib import Path

        from shop import services

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            for index in range(8):
                (path / f"backup_2026-01-{index + 1:02d}_000000.sqlite3").write_text("x")
            with override_settings(BACKUP_DIR=path):
                services.prune_backups(keep=5)
                self.assertEqual(len(list(path.glob("*.sqlite3"))), 5)
                # The five KEPT must be the newest by name, not any five.
                remaining = sorted(p.name for p in path.glob("*.sqlite3"))
                self.assertEqual(remaining[0], "backup_2026-01-04_000000.sqlite3")

    def test_the_automatic_backup_runs_once_a_day_not_once_a_page_view(self):
        import tempfile
        from pathlib import Path

        from shop import services

        with tempfile.TemporaryDirectory() as folder:
            with override_settings(BACKUP_DIR=Path(folder)):
                first = services.auto_backup_if_due()
                second = services.auto_backup_if_due()
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_the_owner_opening_the_dashboard_causes_todays_backup(self):
        import tempfile
        from pathlib import Path

        from shop import services

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            with override_settings(BACKUP_DIR=path):
                self.client.login(username="owner", password="pw12345")
                self.client.get(reverse("dashboard"))
                self.assertEqual(len(list(path.glob("*.sqlite3"))), 1)

    def test_the_age_of_the_last_backup_is_reported(self):
        import tempfile
        from pathlib import Path

        from shop import services

        with tempfile.TemporaryDirectory() as folder:
            with override_settings(BACKUP_DIR=Path(folder)):
                self.assertIsNone(services.last_backup_age_days())
                services.backup_database()
                self.assertEqual(services.last_backup_age_days(), 0)


# ---------------------------------------------------------------------------
# Who built it
# ---------------------------------------------------------------------------
class BrandingTests(ShopTestCase):
    """The credit is the only marketing this system does.

    It sits on a screen the owner and his cashiers look at all day, and on every
    receipt a customer carries out of the shop. A later template edit dropping it
    would be invisible - hence these.
    """

    def test_every_screen_credits_campusnect_and_links_to_the_site(self):
        self.client.login(username="owner", password="pw12345")
        for url_name in ["dashboard", "pos", "product_list", "backup"]:
            page = self.client.get(reverse(url_name)).content.decode()
            self.assertIn("CampusNect Smart Technologies", page, url_name)
            self.assertIn("https://campusnect.com", page, url_name)

    def test_the_printed_receipt_carries_the_credit(self):
        product = self.make_product()
        self.deliver(product, 5)
        sale = record_sale(
            user=self.cashier,
            lines=[{"product": product, "quantity": Decimal("1"),
                    "unit_price": Decimal("1500")}],
            amount_paid=Decimal("2000"))

        self.client.login(username="cashier", password="pw12345")
        receipt = self.client.get(reverse("receipt", args=[sale.pk])).content.decode()

        self.assertIn("Powered by CampusNect Smart Technologies", receipt)
        # No clickable link on paper - nobody types a URL off a thermal roll,
        # and the roll is narrow.
        self.assertNotIn("https://campusnect.com", receipt)
