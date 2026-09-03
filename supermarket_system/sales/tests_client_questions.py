"""The five things the client came back and asked for, plus the network answer.

He sent a handwritten list headed "Challenges with the system":

    - How to cash out (Complete payment)
    - How to enter products in the system
    - How to delete products
    - How to record products without Invoice No.
    - How to do stock taking (things already in the supermarket)

and asked separately whether two or more computers could share the same data
over a network while staying offline.

Each class below is one of those lines. Keeping them in their own file, named
after his questions rather than after our models, means that when one of these
breaks it is obvious which promise to him was broken.
"""
import json
import shutil
import sqlite3
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from inventory.models import (Product, Purchase, PurchaseItem, StockBatch, StockCount,
                              StockMovement)
from sales.models import InsufficientStock
from sales.services import apply_stock_count, receive_purchase, record_sale
from sales.tests import ShopTestCase


class StockTakeTests(ShopTestCase):
    """'How to do stock taking (things already in the supermarket)'."""

    def test_counting_brings_goods_that_were_never_delivered_onto_the_books(self):
        product = self.make_product(name="Blue Band 500g")
        self.assertEqual(product.stock_available, Decimal("0"))

        count = apply_stock_count(
            rows=[{"product": product, "counted": Decimal("14")}],
            user=self.owner, scope="Groceries shelf")

        product.refresh_from_db()
        self.assertEqual(product.stock_available, Decimal("14.000"))
        self.assertEqual(count.line_count, 1)
        self.assertEqual(count.difference_count, 1)
        # The first time stock appears this way it is an opening balance, not a
        # correction - it must not read as shrinkage on the reports.
        movement = StockMovement.objects.get(product=product)
        self.assertEqual(movement.kind, StockMovement.Kind.OPENING)
        self.assertEqual(movement.reference, count.reference)

    def test_a_short_shelf_is_written_down_and_valued_as_a_loss(self):
        product = self.make_product(buying="1000")
        self.deliver(product, 20)

        count = apply_stock_count(
            rows=[{"product": product, "counted": Decimal("17")}], user=self.owner)

        product.refresh_from_db()
        self.assertEqual(product.stock_available, Decimal("17.000"))
        line = count.lines.get()
        self.assertEqual(line.system_quantity, Decimal("20.000"))
        self.assertEqual(line.difference, Decimal("-3.000"))
        self.assertEqual(count.value_difference, Decimal("-3000.00"))
        self.assertEqual(
            StockMovement.objects.filter(kind=StockMovement.Kind.ADJUST).count(), 1)

    def test_a_count_that_matches_changes_nothing_but_is_still_recorded(self):
        product = self.make_product()
        self.deliver(product, 10)
        movements_before = StockMovement.objects.count()

        count = apply_stock_count(
            rows=[{"product": product, "counted": Decimal("10")}], user=self.owner)

        self.assertEqual(count.line_count, 1)
        self.assertEqual(count.difference_count, 0)
        self.assertEqual(StockMovement.objects.count(), movements_before)

    def test_a_count_carries_its_own_cost_and_expiry_onto_the_new_batch(self):
        """Goods already in the shop still cost money and still go off. If that
        is not captured while they are entered it is never captured at all."""
        product = self.make_product(buying="0")
        expiry = timezone.localdate() + timedelta(days=60)

        apply_stock_count(rows=[{"product": product, "counted": Decimal("6"),
                                 "buying_price": Decimal("900"),
                                 "expiry_date": expiry}], user=self.owner)

        batch = StockBatch.objects.get(product=product)
        self.assertEqual(batch.buying_price, Decimal("900.00"))
        self.assertEqual(batch.expiry_date, expiry)
        product.refresh_from_db()
        self.assertEqual(product.buying_price, Decimal("900.00"))

    def test_a_negative_count_is_refused(self):
        product = self.make_product()
        with self.assertRaises(ValueError):
            apply_stock_count(rows=[{"product": product, "counted": Decimal("-3")}],
                              user=self.owner)

    def test_an_empty_count_is_refused(self):
        with self.assertRaises(ValueError):
            apply_stock_count(rows=[], user=self.owner)

    def test_a_blank_box_means_not_counted_not_zero(self):
        """The one mistake that would wipe out a shelf nobody looked at."""
        counted = self.make_product(name="Counted item")
        skipped = self.make_product(name="Skipped item")
        self.deliver(counted, 10)
        self.deliver(skipped, 30)

        self.client.login(username="owner", password="pw12345")
        response = self.client.post(reverse("stock_take"), {
            "product_id": [str(counted.pk), str(skipped.pk)],
            f"counted_{counted.pk}": "8",
            f"counted_{skipped.pk}": "",          # left alone on the shelf
            "scope": "Front shelf",
        })
        self.assertEqual(response.status_code, 302)

        counted.refresh_from_db()
        skipped.refresh_from_db()
        self.assertEqual(counted.stock_available, Decimal("8.000"))
        self.assertEqual(skipped.stock_available, Decimal("30.000"))
        self.assertEqual(StockCount.objects.get().line_count, 1)

    def test_counting_nothing_at_all_is_reported_not_silently_accepted(self):
        product = self.make_product()
        self.deliver(product, 4)
        self.client.login(username="owner", password="pw12345")

        response = self.client.post(reverse("stock_take"), {
            "product_id": [str(product.pk)], f"counted_{product.pk}": "",
        }, follow=True)

        self.assertContains(response, "No quantities were typed in")
        self.assertFalse(StockCount.objects.exists())

    def test_the_count_screens_open(self):
        product = self.make_product()
        count = apply_stock_count(
            rows=[{"product": product, "counted": Decimal("2")}], user=self.owner)
        self.client.login(username="owner", password="pw12345")
        for url in [reverse("stock_take"), reverse("stock_count_list"),
                    reverse("stock_count_detail", args=[count.pk])]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_a_cashier_cannot_count_the_stock(self):
        self.client.login(username="cashier", password="pw12345")
        self.assertEqual(self.client.get(reverse("stock_take")).status_code, 403)


class EnteringProductsTests(ShopTestCase):
    """'How to enter products in the system' - one screen, not two."""

    def test_a_product_added_with_a_quantity_can_be_sold_immediately(self):
        self.client.login(username="owner", password="pw12345")
        response = self.client.post(reverse("product_create"), {
            "name": "Omo 1kg", "barcode": "", "category": self.category.id,
            "unit": self.piece.id, "buying_price": "5000", "selling_price": "6500",
            "is_active": "on", "opening_quantity": "12",
        })
        self.assertEqual(response.status_code, 302)

        product = Product.objects.get(name="Omo 1kg")
        self.assertEqual(product.stock_available, Decimal("12.000"))
        self.assertEqual(
            StockMovement.objects.get(product=product).kind, StockMovement.Kind.OPENING)

        # And it really is sellable, which is the whole point of the change.
        sale = record_sale(user=self.owner, lines=[
            {"product": product, "quantity": Decimal("1"), "unit_price": Decimal("6500")}])
        self.assertEqual(sale.total, Decimal("6500.00"))

    def test_an_opening_expiry_is_kept(self):
        expiry = timezone.localdate() + timedelta(days=30)
        self.client.login(username="owner", password="pw12345")
        self.client.post(reverse("product_create"), {
            "name": "Yoghurt", "barcode": "", "category": self.category.id,
            "unit": self.piece.id, "buying_price": "1500", "selling_price": "2000",
            "is_active": "on", "opening_quantity": "9",
            "opening_expiry": expiry.isoformat(),
        })
        batch = StockBatch.objects.get(product__name="Yoghurt")
        self.assertEqual(batch.expiry_date, expiry)

    def test_leaving_the_quantity_empty_still_creates_the_product(self):
        self.client.login(username="owner", password="pw12345")
        self.client.post(reverse("product_create"), {
            "name": "Nothing yet", "barcode": "", "category": self.category.id,
            "unit": self.piece.id, "buying_price": "500", "selling_price": "800",
            "is_active": "on", "opening_quantity": "",
        })
        product = Product.objects.get(name="Nothing yet")
        self.assertEqual(product.stock_available, Decimal("0"))
        self.assertFalse(product.movements.exists())

    def test_the_opening_boxes_do_not_appear_when_editing(self):
        """On an edit they would read as 'set the stock to this' but would in
        fact add to it, so the count would drift every time a price changed."""
        from inventory.forms import ProductForm

        product = self.make_product()
        self.assertNotIn("opening_quantity", ProductForm(instance=product).fields)
        self.assertIn("opening_quantity", ProductForm().fields)

    def test_editing_a_product_never_touches_its_stock(self):
        product = self.make_product()
        self.deliver(product, 7)
        self.client.login(username="owner", password="pw12345")

        self.client.post(reverse("product_edit", args=[product.pk]), {
            "name": product.name, "barcode": "", "category": self.category.id,
            "unit": self.piece.id, "buying_price": "1100", "selling_price": "1700",
            "is_active": "on", "opening_quantity": "999",   # ignored - not a field
        })

        product.refresh_from_db()
        self.assertEqual(product.stock_available, Decimal("7.000"))
        self.assertEqual(product.selling_price, Decimal("1700.00"))


class DeleteProductTests(ShopTestCase):
    """'How to delete products' - there was no way to do it at all before."""

    def test_a_product_with_no_history_is_really_deleted(self):
        product = self.make_product(name="Typed in twice")
        self.client.login(username="owner", password="pw12345")

        response = self.client.post(reverse("product_delete", args=[product.pk]))

        self.assertRedirects(response, reverse("product_list"))
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_a_product_that_has_been_sold_is_retired_not_erased(self):
        product = self.make_product(name="Sold before")
        self.deliver(product, 5)
        sale = record_sale(user=self.owner, lines=[
            {"product": product, "quantity": Decimal("1"), "unit_price": Decimal("1500")}])

        self.client.login(username="owner", password="pw12345")
        self.client.post(reverse("product_delete", args=[product.pk]))

        product.refresh_from_db()
        self.assertFalse(product.is_active)
        # The receipt the customer is holding still adds up.
        sale.refresh_from_db()
        self.assertEqual(sale.total, Decimal("1500.00"))
        self.assertEqual(sale.items.count(), 1)

    def test_a_retired_product_is_off_the_till(self):
        product = self.make_product(name="Discontinued")
        self.deliver(product, 5)
        self.client.login(username="owner", password="pw12345")
        self.client.post(reverse("product_delete", args=[product.pk]))

        response = self.client.get(reverse("product_lookup"), {"q": "Discontinued"})
        self.assertEqual(response.json()["results"], [])

    def test_a_retired_product_can_be_brought_back(self):
        product = self.make_product()
        self.deliver(product, 5)
        self.client.login(username="owner", password="pw12345")
        self.client.post(reverse("product_delete", args=[product.pk]))
        self.client.post(reverse("product_restore", args=[product.pk]))

        product.refresh_from_db()
        self.assertTrue(product.is_active)

    def test_a_product_that_was_only_counted_is_not_hard_deleted(self):
        """A count that matched leaves a PROTECTed line but no movement. Miss
        that and the delete blows up with a database error in his face."""
        product = self.make_product()
        apply_stock_count(rows=[{"product": product, "counted": Decimal("0")}],
                          user=self.owner)

        self.client.login(username="owner", password="pw12345")
        self.client.post(reverse("product_delete", args=[product.pk]))

        product.refresh_from_db()
        self.assertFalse(product.is_active)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

    def test_the_screen_says_which_of_the_two_will_happen(self):
        clean = self.make_product(name="Never touched")
        used = self.make_product(name="Has history")
        self.deliver(used, 3)

        self.client.login(username="owner", password="pw12345")
        self.assertTrue(
            self.client.get(reverse("product_delete", args=[clean.pk])).context["can_erase"])
        self.assertFalse(
            self.client.get(reverse("product_delete", args=[used.pk])).context["can_erase"])

    def test_a_cashier_cannot_delete_a_product(self):
        product = self.make_product()
        self.client.login(username="cashier", password="pw12345")
        self.assertEqual(
            self.client.post(reverse("product_delete", args=[product.pk])).status_code, 403)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())


class DeliveryWithoutPaperworkTests(ShopTestCase):
    """'How to record products without Invoice No.'"""

    def test_a_delivery_can_be_received_with_no_supplier_and_no_invoice(self):
        product = self.make_product()
        purchase = Purchase.objects.create(received_by=self.owner)
        PurchaseItem.objects.create(purchase=purchase, product=product,
                                    quantity=Decimal("10"), buying_price=Decimal("900"))

        receive_purchase(purchase, self.owner)

        product.refresh_from_db()
        self.assertEqual(product.stock_available, Decimal("10.000"))
        self.assertEqual(purchase.supplier_name, "Supplier not recorded")
        self.assertTrue(purchase.reference.startswith("GRN-"))

    def test_the_form_accepts_a_blank_supplier_and_invoice(self):
        from inventory.forms import PurchaseForm

        form = PurchaseForm(data={"supplier": "", "invoice_no": "",
                                  "date": timezone.localdate(), "notes": ""})
        self.assertTrue(form.is_valid(), form.errors)

    def test_receiving_through_the_screen_with_no_paperwork(self):
        product = self.make_product()
        self.client.login(username="owner", password="pw12345")
        response = self.client.post(reverse("purchase_create"), {
            "supplier": "", "invoice_no": "", "date": timezone.localdate().isoformat(),
            "notes": "Bought for cash in the market",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000",
            "items-0-product": str(product.pk), "items-0-quantity": "6",
            "items-0-buying_price": "1200", "items-0-selling_price": "",
            "items-0-expiry_date": "",
            "action": "receive",
        })
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertEqual(product.stock_available, Decimal("6.000"))

    def test_a_draft_delivery_can_be_thrown_away(self):
        product = self.make_product()
        purchase = self.deliver(product, 5, receive=False)
        self.client.login(username="owner", password="pw12345")

        self.client.post(reverse("purchase_delete", args=[purchase.pk]))

        self.assertFalse(Purchase.objects.filter(pk=purchase.pk).exists())
        product.refresh_from_db()
        self.assertEqual(product.stock_available, Decimal("0"))

    def test_a_received_delivery_cannot_be_thrown_away(self):
        """The goods are on the shelf and may already be sold. Deleting the
        paperwork would leave stock that came from nowhere."""
        product = self.make_product()
        purchase = self.deliver(product, 5)
        self.client.login(username="owner", password="pw12345")

        self.client.post(reverse("purchase_delete", args=[purchase.pk]))

        self.assertTrue(Purchase.objects.filter(pk=purchase.pk).exists())
        product.refresh_from_db()
        self.assertEqual(product.stock_available, Decimal("5.000"))


class CashingOutTests(ShopTestCase):
    """'How to cash out (Complete payment)'."""

    def test_the_till_names_the_button_in_his_words_and_offers_note_buttons(self):
        self.client.login(username="cashier", password="pw12345")
        page = self.client.get(reverse("pos")).content.decode()
        self.assertIn("CASH OUT", page)
        self.assertIn('data-tender="exact"', page)
        self.assertIn('data-tender="5000"', page)

    def test_change_comes_back_so_the_cashier_can_read_it_out(self):
        product = self.make_product(selling="1500")
        self.deliver(product, 10)
        self.client.login(username="cashier", password="pw12345")

        response = self.client.post(
            reverse("pos_checkout"),
            data=json.dumps({
                "lines": [{"product_id": product.pk, "quantity": 2, "unit_price": "1500"}],
                "amount_paid": "5000", "payment_method": "CASH",
            }),
            content_type="application/json")

        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(Decimal(body["total"]), Decimal("3000.00"))
        self.assertEqual(Decimal(body["change"]), Decimal("2000.00"))


class MoreThanOneComputerTests(ShopTestCase):
    """'Will two or more computers be able to share the same data?'"""

    def test_the_database_runs_in_wal_mode_so_tills_do_not_block_each_other(self):
        """WAL is what stops one cashier saving a sale from freezing every
        other screen in the shop.

        This runs the configured PRAGMA string against a real file on disk
        rather than reading the live connection, because Django's test database
        is in memory and can never be in WAL mode. Checking the setting alone
        would not notice a typo in the PRAGMA, which would fail silently and
        leave the shop with the very locking this was meant to remove.
        """
        options = settings.DATABASES["default"]["OPTIONS"]
        self.assertGreaterEqual(options["timeout"], 20)
        self.assertEqual(options["transaction_mode"], "IMMEDIATE")

        path = Path(tempfile.mkdtemp()) / "pragma_check.sqlite3"
        probe = sqlite3.connect(path)
        try:
            probe.executescript(options["init_command"])
            self.assertEqual(
                probe.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            self.assertGreaterEqual(
                probe.execute("PRAGMA busy_timeout").fetchone()[0], 20000)
            self.assertEqual(probe.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        finally:
            probe.close()
            for leftover in path.parent.glob("pragma_check.sqlite3*"):
                leftover.unlink(missing_ok=True)
            path.parent.rmdir()

    def test_two_tills_selling_the_last_packet_cannot_both_win(self):
        """The row lock in record_sale is what stops the shelf going negative
        when two cashiers scan the same last item at the same moment."""
        product = self.make_product()
        self.deliver(product, 1)

        record_sale(user=self.cashier, lines=[
            {"product": product, "quantity": Decimal("1"), "unit_price": Decimal("1500")}])

        with self.assertRaises(InsufficientStock):
            record_sale(user=self.owner, lines=[
                {"product": product, "quantity": Decimal("1"),
                 "unit_price": Decimal("1500")}])

        product.refresh_from_db()
        self.assertEqual(product.stock_available, Decimal("0.000"))

    def test_the_owner_can_read_the_address_to_type_on_the_other_till(self):
        self.client.login(username="owner", password="pw12345")
        response = self.client.get(reverse("network"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["addresses"], "no address was offered at all")
        for address in response.context["addresses"]:
            # An address somebody has to type off a screen: IPv4, and never the
            # loopback one, which would work only on the machine itself.
            self.assertEqual(address["ip"].count("."), 3)
            self.assertFalse(address["ip"].startswith("127."))

    def test_a_cashier_is_not_shown_the_server_address(self):
        self.client.login(username="cashier", password="pw12345")
        self.assertEqual(self.client.get(reverse("network")).status_code, 403)

    def test_a_file_copy_would_lose_recent_sales_but_the_backup_api_does_not(self):
        """The reason the backup screen no longer copies db.sqlite3.

        In WAL mode a committed sale can still be sitting in db.sqlite3-wal.
        Copying the one file produces a backup missing the morning's takings,
        and nobody discovers that until the day they need it. This proves both
        halves on a real file: the plain copy loses the row, SQLite's own
        backup API keeps it.
        """
        folder = Path(tempfile.mkdtemp())
        live = folder / "live.sqlite3"

        # Set the shop up and close cleanly, which checkpoints the WAL - so the
        # table itself is safely inside live.sqlite3, exactly like a shop that
        # has been trading for months.
        setup = sqlite3.connect(live)
        try:
            setup.executescript(settings.DATABASES["default"]["OPTIONS"]["init_command"])
            setup.execute("CREATE TABLE takings (receipt TEXT)")
            setup.commit()
        finally:
            setup.close()

        writer = sqlite3.connect(live)
        try:
            writer.execute("INSERT INTO takings VALUES ('R-0001')")
            writer.commit()          # committed - but still only in the -wal file

            # What the old code did: copy the one file.
            naive = folder / "naive.sqlite3"
            shutil.copy2(live, naive)
            reader = sqlite3.connect(naive)
            try:
                self.assertEqual(
                    reader.execute("SELECT COUNT(*) FROM takings").fetchone()[0], 0,
                    "a plain file copy unexpectedly kept the row - if SQLite has "
                    "changed this, the comment in shop/views.backup needs revisiting")
            finally:
                reader.close()

            # What the backup screen does now.
            safe = folder / "safe.sqlite3"
            destination = sqlite3.connect(safe)
            try:
                writer.backup(destination)
                self.assertEqual(
                    destination.execute("SELECT COUNT(*) FROM takings").fetchone()[0], 1)
            finally:
                destination.close()
        finally:
            writer.close()
            shutil.rmtree(folder, ignore_errors=True)


class HelpTests(ShopTestCase):
    def test_the_help_page_answers_every_question_he_asked(self):
        self.client.login(username="owner", password="pw12345")
        page = self.client.get(reverse("help")).content.decode()
        for phrase in ["Cash out a customer",
                       "Put a new product into the system",
                       "Record the goods that are already in the shop",
                       "Record goods that came with no invoice number",
                       "Delete a product",
                       "Use the system on a second computer"]:
            self.assertIn(phrase, page, f"the help page never mentions: {phrase}")

    def test_a_cashier_gets_the_selling_half_only(self):
        self.client.login(username="cashier", password="pw12345")
        page = self.client.get(reverse("help")).content.decode()
        self.assertIn("Cash out a customer", page)
        self.assertNotIn("Use the system on a second computer", page)


class GuidedTourTests(ShopTestCase):
    """The tour that walks him through the system.

    The tour itself is JavaScript and is exercised in a browser; what these
    tests hold down is the server side of it - the flag, and the anchors in the
    templates that the tour points at. An anchor quietly disappearing from a
    template is the failure that would leave him staring at a highlight over
    nothing, and it is exactly the sort of thing a later edit does by accident.
    """

    TOUR_ANCHORS = {
        "dashboard": ["nav", "takings", "alerts"],
        "pos": ["scan", "cart", "total", "paid", "change", "checkout"],
        "stock_take": ["scope", "sheet", "save-count"],
        "purchase_create": ["no-paperwork", "delivery-lines", "receive"],
        "backup": ["backup-btn", "nav-network"],
    }

    def setUp(self):
        super().setUp()
        # Something for the product list and the counting sheet to show.
        self.product = self.make_product(name="Sugar 1kg")
        self.deliver(self.product, 10)

    def test_every_element_the_tour_points_at_still_exists(self):
        self.client.login(username="owner", password="pw12345")
        for url_name, anchors in self.TOUR_ANCHORS.items():
            page = self.client.get(reverse(url_name)).content.decode()
            for anchor in anchors:
                self.assertIn(
                    f'data-tour="{anchor}"', page,
                    f'the tour points at "{anchor}" on the {url_name} page, '
                    f'but nothing there carries that marker any more')

    def test_the_tour_can_point_at_a_single_form_field(self):
        """The two fields the whole tour is really about."""
        self.client.login(username="owner", password="pw12345")

        add = self.client.get(reverse("product_create")).content.decode()
        self.assertIn('data-tour-field="opening_quantity"', add)

        delivery = self.client.get(reverse("purchase_create")).content.decode()
        self.assertIn('data-tour-field="invoice_no"', delivery)

    def test_the_opening_quantity_anchor_is_absent_when_editing(self):
        """The tour must not promise a box that is deliberately not there."""
        self.client.login(username="owner", password="pw12345")
        page = self.client.get(
            reverse("product_edit", args=[self.product.pk])).content.decode()
        self.assertNotIn('data-tour-field="opening_quantity"', page)

    def test_the_page_key_matches_the_url_name_the_tour_navigates_to(self):
        """The tour finds its place by <body data-page>, and navigates by URL.
        If those two ever stop agreeing it walks to a page and does nothing."""
        self.client.login(username="owner", password="pw12345")
        for url_name in ["dashboard", "pos", "product_create", "stock_take",
                         "purchase_create", "product_list", "backup"]:
            page = self.client.get(reverse(url_name)).content.decode()
            self.assertIn(f'<body data-page="{url_name}"', page, url_name)

    def test_a_new_user_is_offered_the_tour_and_an_old_one_is_not(self):
        self.client.login(username="owner", password="pw12345")
        self.assertIn('data-auto="1"', self.client.get(reverse("dashboard")).content.decode())

        self.owner.has_taken_tour = True
        self.owner.save(update_fields=["has_taken_tour"])
        self.assertIn('data-auto="0"', self.client.get(reverse("dashboard")).content.decode())

    def test_finishing_the_tour_is_remembered_on_the_user(self):
        """On the user, not in the browser: the shop has two computers, and
        being offered the tour again on the second reads as the system having
        forgotten who he is."""
        self.client.login(username="owner", password="pw12345")

        response = self.client.post(reverse("tour_state"),
                                    data=json.dumps({"done": True}),
                                    content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["has_taken_tour"])
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.has_taken_tour)

    def test_the_tour_can_be_started_again_from_the_help_page(self):
        self.owner.has_taken_tour = True
        self.owner.save(update_fields=["has_taken_tour"])
        self.client.login(username="owner", password="pw12345")

        self.client.post(reverse("tour_state"), data=json.dumps({"done": False}),
                         content_type="application/json")

        self.owner.refresh_from_db()
        self.assertFalse(self.owner.has_taken_tour)
        self.assertIn("data-tour-start",
                      self.client.get(reverse("help")).content.decode())

    def test_a_cashier_gets_the_selling_chapters_only(self):
        self.client.login(username="cashier", password="pw12345")
        page = self.client.get(reverse("pos")).content.decode()
        self.assertIn('data-admin="0"', page)
        # A cashier cannot open the stock screens, so the tour must never try
        # to walk them there.
        self.assertNotIn("stock/take", page)

    def test_the_tour_is_not_served_to_a_signed_out_visitor(self):
        page = self.client.get(reverse("login")).content.decode()
        self.assertNotIn('id="tour-cfg"', page)

    def test_the_tour_state_refuses_a_get(self):
        self.client.login(username="owner", password="pw12345")
        self.assertEqual(self.client.get(reverse("tour_state")).status_code, 405)

    def test_signing_in_is_required_to_touch_the_tour_state(self):
        response = self.client.post(reverse("tour_state"), data="{}",
                                    content_type="application/json")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)
