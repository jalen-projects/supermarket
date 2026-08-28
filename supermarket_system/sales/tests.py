"""End-to-end checks of the rules the shop's money depends on."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from inventory.models import (Category, Product, Purchase, PurchaseItem, StockBatch,
                              StockMovement, Supplier, Unit)
from sales.models import Customer, InsufficientStock, Sale
from sales.services import receive_purchase, record_sale, write_off_batch
from shop.models import ShopSettings, User


class ShopTestCase(TestCase):
    def setUp(self):
        self.shop = ShopSettings.get()
        self.owner = User.objects.create_user(
            username="owner", password="pw12345", role=User.Role.ADMIN,
            first_name="Grace")
        self.cashier = User.objects.create_user(
            username="cashier", password="pw12345", role=User.Role.CASHIER,
            first_name="Moses")
        self.category = Category.objects.create(name="Beverages")
        self.piece = Unit.objects.create(name="Piece", abbreviation="pc")
        self.kg = Unit.objects.create(name="Kilogram", abbreviation="kg", allow_decimals=True)
        self.supplier = Supplier.objects.create(name="Kampala Wholesalers")

    def make_product(self, name="Soda 500ml", buying="1000", selling="1500", unit=None):
        return Product.objects.create(
            name=name, category=self.category, unit=unit or self.piece,
            buying_price=Decimal(buying), selling_price=Decimal(selling))

    def deliver(self, product, quantity, buying="1000", expiry=None, receive=True):
        purchase = Purchase.objects.create(supplier=self.supplier, received_by=self.owner)
        PurchaseItem.objects.create(
            purchase=purchase, product=product, quantity=Decimal(str(quantity)),
            buying_price=Decimal(buying), expiry_date=expiry)
        if receive:
            receive_purchase(purchase, self.owner)
        return purchase


class PurchaseTests(ShopTestCase):
    def test_receiving_a_delivery_puts_stock_on_the_shelf(self):
        product = self.make_product()
        self.assertEqual(product.stock_available, Decimal("0"))

        self.deliver(product, 24, buying="1100")

        product.refresh_from_db()
        self.assertEqual(product.stock_available, Decimal("24.000"))
        self.assertEqual(product.buying_price, Decimal("1100.00"))
        self.assertEqual(StockBatch.objects.count(), 1)
        self.assertEqual(
            StockMovement.objects.filter(kind=StockMovement.Kind.PURCHASE).count(), 1)

    def test_a_draft_delivery_adds_nothing(self):
        product = self.make_product()
        self.deliver(product, 24, receive=False)
        self.assertEqual(product.stock_available, Decimal("0"))

    def test_receiving_twice_does_not_double_the_stock(self):
        product = self.make_product()
        purchase = self.deliver(product, 10)
        receive_purchase(purchase, self.owner)
        self.assertEqual(product.stock_available, Decimal("10.000"))

    def test_a_delivery_can_change_the_selling_price(self):
        product = self.make_product(selling="1500")
        purchase = Purchase.objects.create(supplier=self.supplier, received_by=self.owner)
        PurchaseItem.objects.create(
            purchase=purchase, product=product, quantity=Decimal("5"),
            buying_price=Decimal("1200"), selling_price=Decimal("1800"))
        receive_purchase(purchase, self.owner)

        product.refresh_from_db()
        self.assertEqual(product.selling_price, Decimal("1800.00"))


class SaleTests(ShopTestCase):
    def test_a_sale_deducts_stock_and_totals_correctly(self):
        product = self.make_product(selling="1500")
        self.deliver(product, 10)

        sale = record_sale(user=self.cashier,
                           lines=[{"product": product, "quantity": 3,
                                   "unit_price": Decimal("1500")}],
                           amount_paid=Decimal("5000"))

        self.assertEqual(sale.total, Decimal("4500.00"))
        self.assertEqual(sale.change, Decimal("500.00"))
        self.assertEqual(product.stock_available, Decimal("7.000"))
        self.assertEqual(sale.served_by, self.cashier)
        self.assertEqual(sale.customer_name, "Walk-in customer")

    def test_stock_leaves_by_first_expiry_first(self):
        """The oldest goods must go out first, or the shop writes off good stock."""
        product = self.make_product()
        today = timezone.localdate()
        self.deliver(product, 5, buying="1000", expiry=today + timedelta(days=60))
        self.deliver(product, 5, buying="1200", expiry=today + timedelta(days=10))

        record_sale(user=self.cashier,
                    lines=[{"product": product, "quantity": 5, "unit_price": Decimal("1500")}])

        soonest = StockBatch.objects.get(expiry_date=today + timedelta(days=10))
        later = StockBatch.objects.get(expiry_date=today + timedelta(days=60))
        self.assertEqual(soonest.quantity_remaining, Decimal("0.000"))
        self.assertEqual(later.quantity_remaining, Decimal("5.000"))

    def test_cost_comes_from_the_batches_actually_sold(self):
        product = self.make_product()
        today = timezone.localdate()
        self.deliver(product, 2, buying="1000", expiry=today + timedelta(days=5))
        self.deliver(product, 2, buying="2000", expiry=today + timedelta(days=50))

        sale = record_sale(user=self.cashier,
                           lines=[{"product": product, "quantity": 4,
                                   "unit_price": Decimal("3000")}])

        # 2 at 1000 + 2 at 2000 = 6000, not 4 x the current list price.
        self.assertEqual(sale.cost_total, Decimal("6000.00"))
        self.assertEqual(sale.profit, Decimal("6000.00"))

    def test_selling_more_than_is_on_the_shelf_is_refused(self):
        product = self.make_product()
        self.deliver(product, 2)

        with self.assertRaises(InsufficientStock):
            record_sale(user=self.cashier,
                        lines=[{"product": product, "quantity": 5,
                                "unit_price": Decimal("1500")}])

        # Nothing must be left half-written.
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(product.stock_available, Decimal("2.000"))

    def test_expired_stock_cannot_be_sold(self):
        product = self.make_product()
        yesterday = timezone.localdate() - timedelta(days=1)
        self.deliver(product, 10, expiry=yesterday)

        self.assertEqual(product.stock_available, Decimal("10.000"))
        self.assertEqual(product.sellable_quantity, Decimal("0"))
        with self.assertRaises(InsufficientStock):
            record_sale(user=self.cashier,
                        lines=[{"product": product, "quantity": 1,
                                "unit_price": Decimal("1500")}])

    def test_goods_sold_by_weight_accept_fractions(self):
        rice = self.make_product(name="Rice", unit=self.kg, buying="3000", selling="4000")
        self.deliver(rice, "10.5", buying="3000")

        sale = record_sale(user=self.cashier,
                           lines=[{"product": rice, "quantity": Decimal("2.5"),
                                   "unit_price": Decimal("4000")}])

        self.assertEqual(sale.total, Decimal("10000.00"))
        self.assertEqual(rice.stock_available, Decimal("8.000"))

    def test_discount_and_vat(self):
        product = self.make_product(selling="1000")
        self.deliver(product, 10)

        sale = record_sale(user=self.cashier,
                           lines=[{"product": product, "quantity": 10,
                                   "unit_price": Decimal("1000")}],
                           discount=Decimal("1000"), tax=Decimal("1620"))

        # 10,000 less 1,000 discount = 9,000, plus 1,620 VAT.
        self.assertEqual(sale.total, Decimal("10620.00"))

    def test_credit_sale_records_a_balance(self):
        product = self.make_product(selling="1000")
        self.deliver(product, 10)
        customer = Customer.objects.create(name="Mama Nakato", phone="0700000000")

        sale = record_sale(user=self.cashier, customer=customer,
                           lines=[{"product": product, "quantity": 5,
                                   "unit_price": Decimal("1000")}],
                           payment_method=Sale.Payment.CREDIT,
                           amount_paid=Decimal("2000"))

        self.assertEqual(sale.balance_due, Decimal("3000.00"))
        self.assertEqual(sale.customer_name, "Mama Nakato")

    def test_receipt_numbers_do_not_repeat(self):
        product = self.make_product()
        self.deliver(product, 10)
        numbers = set()
        for _ in range(5):
            sale = record_sale(user=self.cashier,
                               lines=[{"product": product, "quantity": 1,
                                       "unit_price": Decimal("1500")}])
            numbers.add(sale.receipt_no)
        self.assertEqual(len(numbers), 5)


class VoidTests(ShopTestCase):
    def test_voiding_returns_stock_to_the_batch_it_came_from(self):
        product = self.make_product()
        today = timezone.localdate()
        self.deliver(product, 5, expiry=today + timedelta(days=10))
        self.deliver(product, 5, expiry=today + timedelta(days=90))

        sale = record_sale(user=self.cashier,
                           lines=[{"product": product, "quantity": 5,
                                   "unit_price": Decimal("1500")}])
        self.assertEqual(product.stock_available, Decimal("5.000"))

        sale.void(self.owner, "Customer changed their mind")

        soonest = StockBatch.objects.get(expiry_date=today + timedelta(days=10))
        soonest.refresh_from_db()
        self.assertEqual(soonest.quantity_remaining, Decimal("5.000"))
        self.assertEqual(product.stock_available, Decimal("10.000"))
        self.assertEqual(sale.status, Sale.Status.VOIDED)

    def test_voiding_twice_does_not_double_the_stock(self):
        product = self.make_product()
        self.deliver(product, 5)
        sale = record_sale(user=self.cashier,
                           lines=[{"product": product, "quantity": 2,
                                   "unit_price": Decimal("1500")}])
        sale.void(self.owner, "Mistake")
        sale.void(self.owner, "Mistake again")
        self.assertEqual(product.stock_available, Decimal("5.000"))

    def test_a_voided_sale_is_kept_not_deleted(self):
        product = self.make_product()
        self.deliver(product, 5)
        sale = record_sale(user=self.cashier,
                           lines=[{"product": product, "quantity": 1,
                                   "unit_price": Decimal("1500")}])
        sale.void(self.owner, "Wrong item")
        self.assertTrue(Sale.objects.filter(pk=sale.pk).exists())


class ExpiryAndStockTests(ShopTestCase):
    def test_low_stock_uses_the_product_level_then_the_shop_default(self):
        self.shop.default_reorder_level = 5
        self.shop.save()

        product = self.make_product()
        self.deliver(product, 4)
        self.assertTrue(product.is_low_stock)

        product.reorder_level = Decimal("2")
        product.save()
        self.assertFalse(product.is_low_stock)

    def test_writing_off_a_batch_removes_it_and_leaves_a_trail(self):
        product = self.make_product()
        self.deliver(product, 6, expiry=timezone.localdate() - timedelta(days=2))
        batch = StockBatch.objects.get()

        write_off_batch(batch, self.owner, "Expired")

        batch.refresh_from_db()
        self.assertEqual(batch.quantity_remaining, Decimal("0.000"))
        self.assertEqual(product.stock_available, Decimal("0"))
        movement = StockMovement.objects.get(kind=StockMovement.Kind.WRITE_OFF)
        self.assertEqual(movement.quantity, Decimal("-6.000"))
        self.assertEqual(movement.reason, "Expired")

    def test_expired_quantity_is_reported_separately(self):
        product = self.make_product()
        today = timezone.localdate()
        self.deliver(product, 3, expiry=today - timedelta(days=1))
        self.deliver(product, 7, expiry=today + timedelta(days=100))

        self.assertEqual(product.stock_available, Decimal("10.000"))
        self.assertEqual(product.expired_quantity, Decimal("3.000"))
        self.assertEqual(product.sellable_quantity, Decimal("7.000"))


class PermissionTests(ShopTestCase):
    def test_a_cashier_cannot_open_the_owner_pages(self):
        self.client.login(username="cashier", password="pw12345")
        for name in ["product_list", "stock_list", "reports", "report_profit",
                     "purchase_list", "user_list", "shop_settings", "backup"]:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 403, f"{name} was not blocked")

    def test_a_cashier_can_use_the_till(self):
        self.client.login(username="cashier", password="pw12345")
        for name in ["pos", "sale_list", "day_summary", "dashboard", "customer_list"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_the_owner_can_open_everything(self):
        self.client.login(username="owner", password="pw12345")
        for name in ["dashboard", "pos", "product_list", "stock_list", "expiry_list",
                     "purchase_list", "purchase_create", "supplier_list", "category_list",
                     "unit_list", "movement_list", "reports", "report_sales",
                     "report_profit", "report_stock", "report_expiry",
                     "report_top_products", "user_list", "shop_settings", "backup",
                     "customer_list", "sale_list", "day_summary"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_a_cashier_cannot_open_another_cashier_s_receipt(self):
        product = self.make_product()
        self.deliver(product, 5)
        sale = record_sale(user=self.owner,
                           lines=[{"product": product, "quantity": 1,
                                   "unit_price": Decimal("1500")}])

        self.client.login(username="cashier", password="pw12345")
        response = self.client.get(reverse("sale_detail", args=[sale.pk]))
        self.assertRedirects(response, reverse("sale_list"))

    def test_signing_in_is_required(self):
        response = self.client.get(reverse("pos"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)


class TillScreenTests(ShopTestCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="cashier", password="pw12345")

    def test_barcode_lookup_returns_the_exact_item(self):
        product = self.make_product()
        product.barcode = "6001234567890"
        product.save()
        self.deliver(product, 10)

        response = self.client.get(reverse("product_lookup"), {"q": "6001234567890"})
        data = response.json()
        self.assertTrue(data["exact"])
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["name"], "Soda 500ml")

    def test_search_by_name_works_without_a_scanner(self):
        self.make_product(name="Blue Band 250g")
        response = self.client.get(reverse("product_lookup"), {"q": "blue"})
        self.assertEqual(len(response.json()["results"]), 1)

    def test_checkout_writes_the_sale(self):
        product = self.make_product(selling="2000")
        self.deliver(product, 10)

        response = self.client.post(
            reverse("pos_checkout"),
            data={"lines": [{"product_id": product.id, "quantity": "3",
                             "unit_price": "2000"}],
                  "payment_method": "CASH", "amount_paid": "10000"},
            content_type="application/json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["total"], "6000.00")
        self.assertEqual(body["change"], "4000.00")

        sale = Sale.objects.get()
        self.assertEqual(sale.served_by, self.cashier)
        self.assertEqual(product.stock_available, Decimal("7.000"))

    def test_checkout_refuses_to_oversell(self):
        product = self.make_product()
        self.deliver(product, 2)

        response = self.client.post(
            reverse("pos_checkout"),
            data={"lines": [{"product_id": product.id, "quantity": "5",
                             "unit_price": "1500"}]},
            content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(Sale.objects.count(), 0)

    def test_checkout_refuses_an_empty_cart(self):
        response = self.client.post(reverse("pos_checkout"), data={"lines": []},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_quick_pick_lists_each_product_only_once(self):
        product = self.make_product()
        self.deliver(product, 50)
        for _ in range(3):
            record_sale(user=self.cashier,
                        lines=[{"product": product, "quantity": 1,
                                "unit_price": Decimal("1500")}])

        quick = self.client.get(reverse("pos")).context["quick_products"]
        names = [p.name for p in quick]
        self.assertEqual(len(names), len(set(names)), f"repeated products: {names}")

    def test_the_receipt_carries_the_four_header_fields(self):
        """Date, company name, served by, customer - straight off the client's list."""
        self.shop.company_name = "Nakawa Super Store"
        self.shop.save()
        customer = Customer.objects.create(name="Mama Nakato")
        product = self.make_product()
        self.deliver(product, 5)
        sale = record_sale(user=self.cashier, customer=customer,
                           lines=[{"product": product, "quantity": 1,
                                   "unit_price": Decimal("1500")}])

        html = self.client.get(reverse("receipt", args=[sale.pk])).content.decode()
        self.assertIn("Nakawa Super Store", html)
        self.assertIn("Moses", html)
        self.assertIn("Mama Nakato", html)
        self.assertIn(sale.receipt_no, html)
        self.assertIn("Soda 500ml", html)


class ReportTests(ShopTestCase):
    def setUp(self):
        super().setUp()
        self.client.login(username="owner", password="pw12345")

    def test_profit_report_adds_up(self):
        product = self.make_product(buying="1000", selling="1500")
        self.deliver(product, 10, buying="1000")
        record_sale(user=self.cashier,
                    lines=[{"product": product, "quantity": 4,
                            "unit_price": Decimal("1500")}])

        response = self.client.get(reverse("report_profit"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["revenue"], Decimal("6000.00"))
        self.assertEqual(response.context["cost"], Decimal("4000.00"))
        self.assertEqual(response.context["profit"], Decimal("2000.00"))

    def test_stock_report_values_the_shelves(self):
        product = self.make_product(buying="1000", selling="1500")
        self.deliver(product, 10, buying="1000")

        response = self.client.get(reverse("report_stock"))
        self.assertEqual(response.context["cost_total"], Decimal("10000.000"))
        self.assertEqual(response.context["retail_total"], Decimal("15000.000"))

    def test_csv_exports_download(self):
        self.make_product()
        for kind in ["stock", "sales", "expiry"]:
            response = self.client.get(reverse("report_export", args=[kind]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "text/csv")

    def test_dashboard_counts_todays_takings(self):
        product = self.make_product(selling="1500")
        self.deliver(product, 10)
        record_sale(user=self.cashier,
                    lines=[{"product": product, "quantity": 2,
                            "unit_price": Decimal("1500")}])

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["todays_total"], Decimal("3000.00"))
        self.assertEqual(response.context["todays_count"], 1)


class SetupTests(ShopTestCase):
    def test_shop_settings_is_a_single_row(self):
        second = ShopSettings(company_name="Another shop")
        second.save()
        self.assertEqual(ShopSettings.objects.count(), 1)
        self.assertEqual(ShopSettings.get().company_name, "Another shop")

    def test_two_products_may_both_have_no_barcode(self):
        """Loose goods have no barcode; a blank must not collide with another blank."""
        from inventory.forms import ProductForm

        for name in ["Loose sugar", "Loose rice"]:
            form = ProductForm(data={"name": name, "barcode": "",
                                     "category": self.category.id, "unit": self.kg.id,
                                     "buying_price": "3000", "selling_price": "4000",
                                     "is_active": True})
            self.assertTrue(form.is_valid(), form.errors)
            form.save()
        self.assertEqual(Product.objects.filter(barcode__isnull=True).count(), 2)

    def test_a_selling_price_below_cost_is_flagged(self):
        from inventory.forms import ProductForm

        form = ProductForm(data={"name": "Loss maker", "barcode": "",
                                 "category": self.category.id, "unit": self.piece.id,
                                 "buying_price": "2000", "selling_price": "1500",
                                 "is_active": True})
        self.assertFalse(form.is_valid())
        self.assertIn("selling_price", form.errors)
