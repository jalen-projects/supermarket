"""
Deleting many products at once (asked for 2 Oct 2026, to clear a list that was
imported wrongly and import it again).

The promise: whatever only ever had its opening stock goes for good, so the
re-import starts clean; whatever was sold or delivered is only taken off sale,
so every past receipt still adds up. And nothing happens without the second,
confirming press.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from inventory import importer
from inventory.models import Category, Product, StockMovement, Unit
from sales.models import Sale
from sales.services import record_sale
from shop.models import AuditEvent, User


class BulkDeleteTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="pw", role=User.Role.ADMIN)
        self.client.force_login(self.owner)
        text = ("Name,Selling price,Buying price,Quantity\n"
                "Fanta 500ml,2000,1250,96\nSprite 500ml,2000,1250,50\n"
                "Omo 500g,5800,4800,10\n")
        records, _ = importer.read_rows(text.encode())
        importer.apply_plan(importer.plan(records), user=self.owner)
        self.fanta = Product.objects.get(name="Fanta 500ml")
        self.sprite = Product.objects.get(name="Sprite 500ml")
        self.omo = Product.objects.get(name="Omo 500g")
        record_sale(user=self.owner, lines=[{"product": self.omo, "quantity": Decimal("1"),
                                             "unit_price": Decimal("5800")}],
                    amount_paid=Decimal("5800"))

    def post(self, **data):
        return self.client.post(reverse("product_bulk_delete"), data)

    def test_the_first_press_only_asks(self):
        page = self.post(scope="selected", ids=[self.fanta.pk, self.omo.pk])
        self.assertContains(page, "1 product will be deleted for good")
        self.assertContains(page, "1 product will only be taken off sale")
        self.assertEqual(Product.objects.count(), 3)

    def test_imported_products_go_for_good_and_sold_ones_are_kept(self):
        self.post(scope="selected", ids=[self.fanta.pk, self.omo.pk], confirm="yes")
        self.assertFalse(Product.objects.filter(pk=self.fanta.pk).exists())
        self.assertFalse(StockMovement.objects.filter(product_id=self.fanta.pk).exists())
        self.omo.refresh_from_db()
        self.assertFalse(self.omo.is_active)
        self.assertEqual(Sale.objects.count(), 1)  # the receipt still adds up
        self.assertTrue(AuditEvent.objects.filter(reference="bulk").exists())

    def test_delete_all_in_this_list_follows_the_search(self):
        self.post(scope="all", q="500ml", confirm="yes")
        self.assertEqual(sorted(Product.objects.values_list("name", flat=True)),
                         ["Omo 500g"])

    def test_after_clearing_the_same_list_imports_again_with_its_stock(self):
        self.post(scope="all", confirm="yes")
        records, _ = importer.read_rows(b"Name,Selling price,Quantity\nFanta 500ml,2000,96\n")
        importer.apply_plan(importer.plan(records), user=self.owner)
        fanta = Product.objects.get(name="Fanta 500ml")
        self.assertEqual(fanta.stock_available, Decimal("96"))

    def test_a_cashier_cannot_delete(self):
        cashier = User.objects.create_user("cash", password="pw", role=User.Role.CASHIER)
        self.client.force_login(cashier)
        self.post(scope="all", confirm="yes")
        self.assertEqual(Product.objects.count(), 3)
