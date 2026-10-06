"""The QR code on the receipt, the public page it opens, and holding a sale.

Both answer things that happen at a supermarket counter: a customer (or the
guard at the door) wants to know a slip is genuine and has not been refunded,
and a customer goes back for the bigger tin while the queue keeps moving.
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from sales import qr
from sales.models import HeldSale, Sale
from sales.services import record_sale

from .tests import ShopTestCase


def decode(rows):
    """Read a QR matrix back with a real decoder, when one is installed (the
    shop PC's wheelhouse has none, so there the test is skipped, not failed)."""
    import numpy as np
    import cv2
    scale, quiet = 8, 4
    full = len(rows) + quiet * 2
    img = np.full((full * scale, full * scale), 255, np.uint8)
    for y, row in enumerate(rows):
        for x, dark in enumerate(row):
            if dark:
                img[(y + quiet) * scale:(y + quiet + 1) * scale,
                    (x + quiet) * scale:(x + quiet + 1) * scale] = 0
    for detector in (cv2.QRCodeDetector(), cv2.QRCodeDetectorAruco()):
        text = detector.detectAndDecode(img)[0]
        if text:
            return text
    return ""


class QrEncoderTests(ShopTestCase):
    def test_codes_read_back_exactly_with_a_real_decoder(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("OpenCV is not installed here")
        samples = [
            "https://maqam.campusnect.com/r/Ab3dEfGhIjKlMnOp/",
            "FreshWay Supermarket\nReceipt R2610070012\n07/10/2026 14:03\nTotal UGX 12,500",
            "x" * 150,                      # version 7+: carries version bits
            "Ssalongo's shop - matooke 16,000/=",
        ]
        for text in samples:
            with self.subTest(length=len(text)):
                self.assertEqual(decode(qr.matrix(text)), text)

    def test_too_long_is_refused_rather_than_printed_wrong(self):
        with self.assertRaises(qr.TooLong):
            qr.matrix("x" * 400)

    def test_svg_is_sized_in_whole_printer_dots(self):
        svg = qr.svg("https://maqam.campusnect.com/r/Ab3dEfGhIjKlMnOp/")
        self.assertIn('shape-rendering="crispEdges"', svg)
        # version 4 = 33 modules + 8 quiet = 41 x 0.75 mm (6 dots at 203 dpi)
        self.assertIn('width="30.75mm"', svg)


class ReceiptQrTests(ShopTestCase):
    def sale(self):
        product = self.make_product()
        self.deliver(product, 10)
        return record_sale(user=self.cashier, lines=[
            {"product": product, "quantity": Decimal("2"), "unit_price": Decimal("1500")}],
            amount_paid=Decimal("3000"))

    def test_every_sale_gets_its_own_unguessable_token(self):
        a, b = self.sale(), self.sale()
        self.assertTrue(a.verify_token and b.verify_token)
        self.assertNotEqual(a.verify_token, b.verify_token)
        self.assertGreaterEqual(len(a.verify_token), 16)
        self.assertNotIn(a.receipt_no, a.verify_token)

    def test_offline_the_receipt_carries_the_details_as_text(self):
        sale = self.sale()
        self.client.login(username="cashier", password="pw12345")
        page = self.client.get(reverse("receipt", args=[sale.pk]))
        self.assertContains(page, "<svg")
        self.assertContains(page, "Scan for the receipt details")
        text = page.context["qr_svg"]
        self.assertNotIn("/r/", text)

    @override_settings(ONLINE=True, PUBLIC_HOSTNAME="shop.example.com")
    def test_online_the_receipt_links_to_its_check_page(self):
        from sales.views import receipt_qr_text
        sale = self.sale()
        self.assertEqual(receipt_qr_text(None, sale, self.shop),
                         f"https://shop.example.com/r/{sale.verify_token}/")
        self.client.login(username="cashier", password="pw12345")
        self.assertContains(self.client.get(reverse("receipt", args=[sale.pk])),
                            "Scan to check this receipt")

    def test_check_page_needs_no_sign_in_and_shows_only_what_the_slip_shows(self):
        self.cashier.last_name = "Okello-Private"
        self.cashier.save()
        sale = self.sale()
        page = self.client.get(reverse("receipt_verify", args=[sale.verify_token]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, sale.receipt_no)
        self.assertContains(page, "Soda 500ml")
        self.assertContains(page, "3,000")
        self.assertContains(page, "genuine receipt")
        self.assertContains(page, "Moses")                  # first name only
        self.assertNotContains(page, "Okello-Private")
        self.assertNotContains(page, "1,000")               # the buying price
        self.assertEqual(page["X-Robots-Tag"], "noindex, nofollow")

    def test_a_voided_receipt_says_so(self):
        sale = self.sale()
        sale.void(self.owner, "test")
        page = self.client.get(reverse("receipt_verify", args=[sale.verify_token]))
        self.assertContains(page, "VOIDED")
        self.assertNotContains(page, "genuine receipt")

    def test_a_made_up_token_finds_nothing(self):
        self.sale()
        self.assertEqual(self.client.get("/r/not-a-real-token/").status_code, 404)
        self.assertEqual(self.client.get("/r/" + "x" * 40 + "/").status_code, 404)


class HoldSaleTests(ShopTestCase):
    def setUp(self):
        super().setUp()
        self.soda = self.make_product()
        self.rice = self.make_product("Rice", "3500", "4500", unit=self.kg)
        self.deliver(self.soda, 20)
        self.deliver(self.rice, 20, buying="3500")
        self.client.login(username="cashier", password="pw12345")

    def hold(self, lines=None, label="", client=None):
        lines = lines or [{"product_id": self.soda.id, "quantity": 2, "unit_price": 1500},
                          {"product_id": self.rice.id, "quantity": 1.5, "unit_price": 4500}]
        return (client or self.client).post(
            reverse("held_sales"), json.dumps({"label": label, "lines": lines}),
            content_type="application/json")

    def test_holding_keeps_the_basket_and_moves_no_stock(self):
        res = self.hold(label="Lady in red").json()
        self.assertTrue(res["ok"])
        self.assertEqual(res["held"]["label"], "Lady in red")
        self.assertEqual(res["held"]["items"], 2)
        self.assertEqual(Decimal(res["held"]["total"]), Decimal("9750"))
        self.assertEqual(self.soda.stock_available, Decimal("20"))
        self.assertFalse(Sale.objects.exists())

    def test_unnamed_baskets_are_numbered_and_numbers_are_reused(self):
        self.assertEqual(self.hold().json()["held"]["label"], "Held 1")
        second = self.hold().json()["held"]
        self.assertEqual(second["label"], "Held 2")
        self.client.post(reverse("held_recall", args=[HeldSale.objects.get(label="Held 1").pk]))
        self.assertEqual(self.hold().json()["held"]["label"], "Held 1")

    def test_an_empty_basket_cannot_be_held(self):
        self.assertEqual(self.hold(lines=[{"product_id": 999, "quantity": 1,
                                           "unit_price": 1}]).status_code, 400)

    def test_every_till_sees_every_held_basket(self):
        self.hold(label="Mr Kato")
        self.client.logout()
        self.client.login(username="owner", password="pw12345")
        held = self.client.get(reverse("held_sales")).json()["held"]
        self.assertEqual([h["label"] for h in held], ["Mr Kato"])
        self.assertFalse(held[0]["mine"])
        self.assertEqual(held[0]["held_by"], "Moses")

    def test_bringing_back_returns_the_lines_and_only_once(self):
        pk = self.hold().json()["held"]["id"]
        back = self.client.post(reverse("held_recall", args=[pk])).json()
        self.assertTrue(back["ok"])
        self.assertEqual([(l["id"], l["qty"]) for l in back["lines"]],
                         [(self.soda.id, 2.0), (self.rice.id, 1.5)])
        again = self.client.post(reverse("held_recall", args=[pk]))
        self.assertEqual(again.status_code, 404)
        self.assertFalse(HeldSale.objects.exists())

    def test_brought_back_at_todays_price_unless_the_cashier_changed_it(self):
        pk = self.hold(lines=[
            {"product_id": self.soda.id, "quantity": 1, "unit_price": 1500},   # list price
            {"product_id": self.rice.id, "quantity": 1, "unit_price": 4000},   # typed in
        ]).json()["held"]["id"]
        self.soda.selling_price = Decimal("1700")
        self.soda.save()
        self.rice.selling_price = Decimal("5000")
        self.rice.save()
        back = self.client.post(reverse("held_recall", args=[pk])).json()
        prices = {l["id"]: l["price"] for l in back["lines"]}
        self.assertEqual(prices[self.soda.id], 1700.0)
        self.assertEqual(prices[self.rice.id], 4000.0)
        self.assertTrue(any("1,700" in n for n in back["notes"]))

    def test_an_item_taken_off_sale_is_left_out_and_named(self):
        pk = self.hold().json()["held"]["id"]
        self.rice.is_active = False
        self.rice.save()
        back = self.client.post(reverse("held_recall", args=[pk])).json()
        self.assertEqual([l["id"] for l in back["lines"]], [self.soda.id])
        self.assertIn("Rice", back["notes"][0])

    def test_only_the_cashier_or_the_owner_may_discard(self):
        pk = self.hold().json()["held"]["id"]
        other = type(self.cashier).objects.create_user(
            username="other", password="pw12345", role="CASHIER")
        self.client.logout()
        self.client.login(username="other", password="pw12345")
        self.assertEqual(self.client.post(reverse("held_discard", args=[pk])).status_code, 403)
        self.client.logout()
        self.client.login(username="owner", password="pw12345")
        self.assertEqual(self.client.post(reverse("held_discard", args=[pk])).status_code, 200)
        self.assertFalse(HeldSale.objects.exists())

    def test_baskets_nobody_came_back_for_are_cleared_after_two_days(self):
        self.hold()
        HeldSale.objects.update(held_at=timezone.now() - timedelta(hours=49))
        self.assertEqual(self.client.get(reverse("held_sales")).json()["held"], [])

    def test_needs_a_sign_in(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("held_sales")).status_code, 302)

    def test_the_till_page_carries_the_hold_button_and_the_list(self):
        page = self.client.get(reverse("pos"))
        self.assertContains(page, 'id="hold"')
        self.assertContains(page, 'id="held-card"')
        self.assertContains(page, reverse("held_sales"))
