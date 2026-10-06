"""The second shop on the server: the FreshWay demonstration shop.

Two promises are tested here. A second shop shows its OWN name and mark
everywhere, not MAQAM's; and the command that fills the demo with a month of
invented trading is safe to run again, and refuses to run on a real shop.
"""
import os
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from inventory.models import Product, Purchase, StockBatch
from sales.models import Customer, Sale, Shift
from shop import brand
from shop.models import ShopSettings, User


def seed(**kw):
    call_command("seed_demo_shop", "--days", "3", stdout=StringIO(), **kw)


@override_settings(DEMO=True)
@mock.patch.dict(os.environ, {"DEMO_PASSWORD": "Demo@2026"})
class SeedDemoShopTests(TestCase):
    def counts(self):
        return (Product.objects.count(), Sale.objects.count(), Shift.objects.count(),
                Customer.objects.count(), Purchase.objects.count(), User.objects.count())

    def test_fills_the_shop(self):
        seed()
        shop = ShopSettings.get()
        self.assertEqual(shop.company_name, "FreshWay Supermarket")
        self.assertTrue(shop.logo)
        self.assertGreaterEqual(Product.objects.count(), 140)
        barcodes = list(Product.objects.values_list("barcode", flat=True))
        self.assertEqual(len(barcodes), len(set(barcodes)))
        self.assertTrue(Product.objects.filter(unit__allow_decimals=True).exists())
        self.assertTrue(Sale.objects.exists())
        methods = set(Sale.objects.values_list("payment_method", flat=True))
        self.assertTrue({"CASH", "MOBILE"} <= methods)
        self.assertTrue(Purchase.objects.filter(status=Purchase.Status.DRAFT).exists())
        variances = {s.variance for s in Shift.objects.filter(status="CLOSED")}
        self.assertTrue(any(v < 0 for v in variances))
        self.assertTrue(StockBatch.objects.filter(expiry_date__lt=Sale.objects.first()
                                                  .created_at.date()).exists())
        roles = dict(User.objects.values_list("username", "role"))
        self.assertEqual(roles["owner"], "ADMIN")
        self.assertEqual(roles["grace"], "CASHIER")
        self.assertTrue(self.client.login(username="grace", password="Demo@2026"))

    def test_running_it_again_changes_nothing(self):
        seed()
        before = self.counts()
        seed()
        self.assertEqual(self.counts(), before)

    def test_running_it_again_puts_a_changed_password_back(self):
        seed()
        owner = User.objects.get(username="owner")
        owner.set_password("visitor-changed-it")
        owner.save()
        seed()
        self.assertTrue(self.client.login(username="owner", password="Demo@2026"))

    def test_reset_starts_a_fresh_month(self):
        seed()
        Customer.objects.create(name="Typed in by a visitor")
        seed(reset=True)
        self.assertFalse(Customer.objects.filter(name="Typed in by a visitor").exists())
        self.assertTrue(Sale.objects.exists())

    @override_settings(DEMO=False)
    def test_refuses_on_a_real_shop(self):
        with self.assertRaises(CommandError):
            seed()
        self.assertFalse(Product.objects.exists())

    @override_settings(ONLINE=True)
    @mock.patch.dict(os.environ, {"DEMO_PASSWORD": ""})
    def test_online_it_needs_the_password_from_the_settings_file(self):
        with self.assertRaises(CommandError):
            seed()


class SecondShopBrandTests(TestCase):
    def setUp(self):
        shop = ShopSettings.get()
        shop.company_name = "FreshWay Supermarket"
        shop.save()

    @override_settings(SHOP_BRAND="freshway", DEMO=True)
    def test_the_demo_shows_its_own_mark_and_never_maqams(self):
        page = self.client.get(reverse("login")).content.decode()
        self.assertIn(brand.BRANDS["freshway"]["mark_a1"], page)
        self.assertNotIn(brand.BRANDS["maqam"]["mark_a1"], page)
        self.assertNotIn("MAQAM", page.upper())
        self.assertIn("freshway-intro", page)
        self.assertIn("demonstration shop", page)
        manifest = self.client.get(reverse("manifest")).json()
        self.assertEqual(manifest["name"], "FreshWay Supermarket")
        self.assertTrue(all("brand/freshway/" in i["src"] for i in manifest["icons"]))
        self.assertIn("freshway-", self.client.get(reverse("service_worker")).content.decode())

    def test_maqam_is_unchanged_when_nothing_is_set(self):
        page = self.client.get(reverse("login")).content.decode()
        self.assertIn(brand.BRANDS["maqam"]["mark_a1"], page)
        self.assertIn("maqam-intro", page)
        self.assertNotIn("demonstration shop", page)

    @override_settings(DEMO=True, ONLINE=True, SMS_USERNAME="u", SMS_KEY="k", SMS_SENDER="S")
    def test_the_demo_can_never_send_a_text(self):
        # settings.py decides SMS_CONFIGURED once at start-up; this checks the
        # rule it applies, so a future edit cannot quietly drop "not DEMO".
        from pathlib import Path
        from django.conf import settings
        source = (Path(settings.BASE_DIR) / "smms" / "settings.py").read_text(encoding="utf-8")
        self.assertIn("SMS_CONFIGURED = (ONLINE and not DEMO", source)
        self.assertIn("if DEMO:\n    SMS_LIVE = False", source)
