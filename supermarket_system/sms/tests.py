"""SMS for the shop: the credit, the sign-in codes, the alerts, the owner's
messages. The gateway (EGO) and the payment page (Flutterwave) are always
mocked - no test ever reaches the network."""
import io
import re
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from sales.models import Customer, Sale
from sales.services import record_sale
from sales.tests import ShopTestCase
from shop.models import AuditEvent, User
from shop.watch import _send

from . import credit, services, signin
from .models import Broadcast, Message, SignInCode, TopUp, balance_pages

Action = AuditEvent.Action

LIVE = dict(ONLINE=True, SMS_CONFIGURED=True, SMS_LIVE=True, SMS_USERNAME="u",
            SMS_KEY="k", SMS_SENDER="MAQAM", SMS_PRICE=45,
            OWNER_ALERT_EMAILS=["owner@example.com"],
            OWNER_ALERT_PHONES=["0772 000 111"],
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")


def give_credit(pages):
    topup = credit.new_topup(pages * 45, method=TopUp.Method.RECORDED,
                             reference=f"T-{TopUp.objects.count()}")
    credit.mark_paid(topup)
    return topup


class Gateway:
    """Stands in for EGO and remembers what it was asked to send."""

    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, number, body):
        if self.fail:
            raise services.GatewayError("Insufficient balance")
        self.sent.append((number, body))
        return "Successfully Sent!"

    def last_code(self):
        return re.search(r"\b(\d{6})\b", self.sent[-1][1]).group(1)


# ---------------------------------------------------------------------------
# Counting and numbers
# ---------------------------------------------------------------------------
class CountingTests(ShopTestCase):
    def test_pages_follow_the_gsm_rule(self):
        self.assertEqual(services.pages(""), 0)
        self.assertEqual(services.pages("a" * 160), 1)
        self.assertEqual(services.pages("a" * 161), 2)
        self.assertEqual(services.pages("a" * 306), 2)
        self.assertEqual(services.pages("a" * 307), 3)

    def test_one_curly_quote_makes_it_unicode(self):
        self.assertEqual(services.pages("’" + "a" * 69), 1)
        self.assertEqual(services.pages("’" + "a" * 70), 2)

    def test_phone_numbers_are_made_bare_and_ugandan(self):
        for raw in ("0772 123 456", "+256 772-123456", "256772123456", "772123456"):
            self.assertEqual(services.normalise_phone(raw), "256772123456")
        for raw in ("", "12345", "0412 123456", "+44 7700 900123"):
            self.assertIsNone(services.normalise_phone(raw))

    def test_a_number_is_masked_on_screen(self):
        self.assertEqual(services.mask("256772123456"), "0772 *** 456")


# ---------------------------------------------------------------------------
# The credit
# ---------------------------------------------------------------------------
class CreditTests(ShopTestCase):
    @override_settings(**{**LIVE, "SMS_LIVE": False})
    def test_test_mode_records_and_prices_but_spends_nothing(self):
        give_credit(10)
        m = services.send("256772000111", "Hello", kind=Message.Kind.BROADCAST)
        self.assertEqual(m.status, Message.Status.TEST)
        self.assertEqual(m.cost, 45)
        self.assertEqual(balance_pages(), 10)

    @override_settings(**LIVE)
    def test_nothing_goes_without_credit(self):
        gw = Gateway()
        with mock.patch("sms.services.ego_send", gw):
            m = services.send("256772000111", "Hello", kind=Message.Kind.BROADCAST)
        self.assertEqual(m.status, Message.Status.NO_CREDIT)
        self.assertEqual(gw.sent, [])

    @override_settings(**LIVE)
    def test_a_send_spends_its_pages_and_a_refusal_gives_them_back(self):
        give_credit(3)
        with mock.patch("sms.services.ego_send", Gateway()):
            services.send("256772000111", "a" * 200, kind=Message.Kind.BROADCAST)
        self.assertEqual(balance_pages(), 1)
        with mock.patch("sms.services.ego_send", Gateway(fail=True)):
            m = services.send("256772000111", "Hi", kind=Message.Kind.BROADCAST)
        self.assertEqual(m.status, Message.Status.FAILED)
        self.assertIn("Insufficient", m.gateway_reply)
        self.assertEqual(balance_pages(), 1)

    def test_price_is_frozen_on_the_top_up(self):
        topup = credit.new_topup(10000)
        self.assertEqual((topup.price_per_page, topup.pages), (45, 222))
        with override_settings(SMS_PRICE=50):
            self.assertEqual(TopUp.objects.get(pk=topup.pk).pages, 222)

    def test_a_payment_is_credited_once(self):
        topup = credit.new_topup(5000)
        self.assertTrue(credit.mark_paid(topup))
        self.assertFalse(credit.mark_paid(topup))
        self.assertEqual(balance_pages(), 111)

    @override_settings(FLW_SECRET_KEY="sk")
    def test_confirm_trusts_only_flutterwaves_own_record(self):
        topup = credit.new_topup(10000)
        short = {"status": "successful", "currency": "UGX", "amount": 9000,
                 "tx_ref": topup.reference, "id": 1}
        with mock.patch("sms.flutterwave.verify_reference", return_value=short):
            self.assertFalse(credit.confirm(topup))
        good = dict(short, amount=10000)
        with mock.patch("sms.flutterwave.verify_reference", return_value=good):
            self.assertTrue(credit.confirm(topup))
            self.assertFalse(credit.confirm(TopUp.objects.get(pk=topup.pk)))
        self.assertEqual(balance_pages(), 222)

    def test_manual_credit_command_refuses_the_same_payment_twice(self):
        out = io.StringIO()
        call_command("sms_credit", "20000", ref="MOMO-1", stdout=out)
        self.assertIn("444 pages", out.getvalue())
        with self.assertRaises(CommandError):
            call_command("sms_credit", "20000", ref="MOMO-1", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("sms_credit", "20000", stdout=io.StringIO())


# ---------------------------------------------------------------------------
# Signing in with a code
# ---------------------------------------------------------------------------
class SignInCodeTests(ShopTestCase):
    def setUp(self):
        super().setUp()
        self.cashier.phone = "0772 123 456"
        self.cashier.save()
        self.owner.phone = "0701 999 888"
        self.owner.email = "grace@example.com"
        self.owner.save()

    def sign_in(self, name="cashier"):
        return self.client.post(reverse("login"), {"username": name, "password": "pw12345"})

    def signed_in(self):
        return "_auth_user_id" in self.client.session

    def test_offline_sign_in_is_exactly_the_password(self):
        with override_settings(ONLINE=False):
            self.sign_in()
        self.assertTrue(self.signed_in())
        self.assertFalse(SignInCode.objects.exists())

    @override_settings(**{**LIVE, "SMS_CONFIGURED": False})
    def test_online_without_a_channel_is_still_just_the_password(self):
        self.sign_in()
        self.assertTrue(self.signed_in())

    @override_settings(**LIVE)
    def test_cashier_gets_an_sms_and_the_code_lets_them_in(self):
        give_credit(5)
        gw = Gateway()
        with mock.patch("sms.services.ego_send", gw):
            response = self.sign_in()
        self.assertRedirects(response, reverse("sms_code"), fetch_redirect_response=False)
        self.assertFalse(self.signed_in())
        self.assertEqual(gw.sent[0][0], "256772123456")
        # The log keeps the message, never the code.
        self.assertNotIn(gw.last_code(), Message.objects.get().body)
        self.assertTrue(AuditEvent.objects.filter(action=Action.OTP_SENT).exists())

        self.client.post(reverse("sms_code"), {"code": "000000" if gw.last_code() != "000000" else "111111"})
        self.assertFalse(self.signed_in())
        self.assertTrue(AuditEvent.objects.filter(action=Action.OTP_FAILED,
                                                  reference="cashier").exists())

        response = self.client.post(reverse("sms_code"), {"code": gw.last_code()})
        self.assertTrue(self.signed_in())
        self.assertTrue(AuditEvent.objects.filter(action=Action.OTP_PASSED).exists())
        self.assertTrue(AuditEvent.objects.filter(action=Action.SIGN_IN, user=self.cashier).exists())

    @override_settings(**LIVE)
    def test_owner_gets_it_by_sms_and_email(self):
        give_credit(5)
        gw = Gateway()
        with mock.patch("sms.services.ego_send", gw):
            self.sign_in("owner")
        self.assertEqual(gw.sent[0][0], "256701999888")
        self.assertEqual(mail.outbox[0].to, ["grace@example.com"])
        self.assertIn(gw.last_code(), mail.outbox[0].body)
        self.assertIn("SMS to 0701 *** 888 and email", SignInCode.objects.get().sent_to)

    @override_settings(**LIVE)
    def test_owner_is_never_locked_out_by_empty_credit(self):
        with mock.patch("sms.services.ego_send", Gateway()):
            self.sign_in("owner")
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)
        self.client.post(reverse("sms_code"), {"code": code})
        self.assertTrue(self.signed_in())

    @override_settings(**LIVE)
    def test_a_cashier_without_a_phone_is_told_to_ask_the_owner(self):
        self.cashier.phone = ""
        self.cashier.save()
        response = self.sign_in()
        self.assertContains(response, "no mobile number")
        self.assertFalse(self.signed_in())

    @override_settings(**LIVE)
    def test_no_credit_sends_the_cashiers_code_to_the_owner(self):
        with mock.patch("sms.services.ego_send", Gateway()):
            self.sign_in()
        row = SignInCode.objects.get()
        self.assertTrue(row.via_owner)
        self.assertEqual(mail.outbox[0].to, ["owner@example.com"])
        self.assertIn("Moses", mail.outbox[0].subject)
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)
        page = self.client.get(reverse("sms_code"))
        self.assertContains(page, "Ask the owner for it")
        self.client.post(reverse("sms_code"), {"code": code})
        self.assertTrue(self.signed_in())

    @override_settings(**{**LIVE, "OWNER_ALERT_EMAILS": []})
    def test_no_credit_and_no_owner_email_refuses_with_the_reason(self):
        response = self.sign_in()
        self.assertContains(response, "top up the SMS credit")
        self.assertFalse(self.signed_in())

    @override_settings(**LIVE)
    def test_five_wrong_codes_end_the_attempt(self):
        give_credit(5)
        with mock.patch("sms.services.ego_send", Gateway()):
            self.sign_in()
        for _ in range(5):
            response = self.client.post(reverse("sms_code"), {"code": "abcdef"})
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn(signin.SESSION_KEY, self.client.session)

    @override_settings(**LIVE)
    def test_an_expired_code_does_not_work(self):
        give_credit(5)
        gw = Gateway()
        with mock.patch("sms.services.ego_send", gw):
            self.sign_in()
        SignInCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.client.post(reverse("sms_code"), {"code": gw.last_code()})
        self.assertFalse(self.signed_in())

    @override_settings(**LIVE)
    def test_resend_waits_a_minute_then_replaces_the_code(self):
        give_credit(5)
        gw = Gateway()
        with mock.patch("sms.services.ego_send", gw):
            self.sign_in()
            response = self.client.post(reverse("sms_code"), {"resend": "1"})
            self.assertContains(response, "wait a minute")
            SignInCode.objects.update(created_at=timezone.now() - timedelta(minutes=2))
            self.client.post(reverse("sms_code"), {"resend": "1"})
        self.assertEqual(len(gw.sent), 2)
        self.client.post(reverse("sms_code"), {"code": gw.last_code()})
        self.assertTrue(self.signed_in())
        self.assertFalse(SignInCode.objects.filter(used_at__isnull=True,
                                                   expires_at__gt=timezone.now()).exists())

    @override_settings(**LIVE)
    def test_wrong_codes_count_towards_the_sign_in_lock(self):
        for _ in range(5):
            AuditEvent.objects.create(action=Action.OTP_FAILED, summary="x",
                                      reference="cashier")
        response = self.sign_in()
        self.assertContains(response, "Too many wrong passwords")
        self.assertFalse(SignInCode.objects.exists())

    @override_settings(**LIVE)
    def test_the_code_step_cannot_be_reached_without_a_password(self):
        self.assertRedirects(self.client.get(reverse("sms_code")), reverse("login"),
                             fetch_redirect_response=False)


# ---------------------------------------------------------------------------
# The till alerts, by SMS as well
# ---------------------------------------------------------------------------
class AlertTests(ShopTestCase):
    @override_settings(**LIVE)
    def test_an_alert_is_texted_to_the_owner_too(self):
        give_credit(5)
        gw = Gateway()
        with mock.patch("sms.services.ego_send", gw):
            self.assertTrue(_send("Subject", "Long email body", sms="MAQAM ALERT: tills silent"))
        self.assertEqual(gw.sent, [("256772000111", "MAQAM ALERT: tills silent")])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(Message.objects.get().kind, Message.Kind.ALERT)

    @override_settings(**LIVE)
    def test_an_alert_without_credit_still_goes_by_email(self):
        with mock.patch("sms.services.ego_send", Gateway()):
            self.assertTrue(_send("Subject", "Body", sms="ALERT"))
        self.assertEqual(Message.objects.get().status, Message.Status.NO_CREDIT)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(ONLINE=False, SMS_CONFIGURED=False, OWNER_ALERT_EMAILS=[],
                       OWNER_ALERT_PHONES=["0772000111"])
    def test_offline_nothing_is_texted(self):
        self.assertFalse(_send("S", "B", sms="ALERT"))
        self.assertFalse(Message.objects.exists())


# ---------------------------------------------------------------------------
# The owner's screens
# ---------------------------------------------------------------------------
class OwnerScreenTests(ShopTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    @override_settings(**LIVE)
    def test_cashiers_cannot_open_the_sms_screens(self):
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse("sms_home")).status_code, 403)

    @override_settings(ONLINE=False)
    def test_the_sms_screens_do_not_exist_offline(self):
        self.assertEqual(self.client.get(reverse("sms_home")).status_code, 404)

    @override_settings(**LIVE)
    def test_home_shows_the_balance_and_bundles(self):
        give_credit(100)
        page = self.client.get(reverse("sms_home"))
        self.assertContains(page, "100")
        self.assertContains(page, "222")  # 10,000 / 45

    @override_settings(**{**LIVE, "FLW_SECRET_KEY": "sk"})
    def test_buying_a_bundle_goes_to_flutterwave(self):
        with mock.patch("sms.flutterwave.create_payment", return_value="https://pay.example/x"):
            response = self.client.post(reverse("sms_buy"), {"amount": "10000"})
        self.assertRedirects(response, "https://pay.example/x", fetch_redirect_response=False)
        topup = TopUp.objects.get()
        self.assertEqual((topup.status, topup.pages), (TopUp.Status.PENDING, 222))

    @override_settings(**{**LIVE, "FLW_SECRET_KEY": "sk"})
    def test_an_odd_amount_is_refused(self):
        self.client.post(reverse("sms_buy"), {"amount": "1234"})
        self.assertFalse(TopUp.objects.exists())

    def _customer_who_spent(self, name, phone, amount):
        customer = Customer.objects.create(name=name, phone=phone)
        product = self.make_product(name=f"Item for {name}", selling=str(amount))
        self.deliver(product, 5)
        sale = record_sale(user=self.cashier, customer=customer, amount_paid=Decimal(amount),
                           lines=[{"product": product, "quantity": Decimal("1"),
                                   "unit_price": Decimal(amount)}])
        return customer, sale

    def test_top_customers_are_ranked_by_spending(self):
        from .views import top_customers
        small, _ = self._customer_who_spent("Small", "0772000001", 2000)
        big, _ = self._customer_who_spent("Big", "0772000002", 9000)
        Customer.objects.create(name="No phone", phone="")
        self.assertEqual([c.name for c in top_customers(30, 10)], ["Big", "Small"])

    @override_settings(**LIVE)
    def test_a_message_is_previewed_with_its_price_then_sent(self):
        give_credit(10)
        big, _ = self._customer_who_spent("Big", "0772000002", 9000)
        self.cashier.phone = "0772123456"
        self.cashier.save()
        data = {"body": "Fresh bread today!", "customer": [str(big.pk)],
                "cashier": [str(self.cashier.pk)]}
        preview = self.client.post(reverse("sms_compose"), {**data, "step": "preview"})
        self.assertContains(preview, "Check before it goes")
        self.assertContains(preview, "UGX 90")
        self.assertFalse(Broadcast.objects.exists())
        gw = Gateway()
        with mock.patch("sms.services.ego_send", gw):
            response = self.client.post(reverse("sms_compose"), {**data, "step": "send"})
        batch = Broadcast.objects.get()
        self.assertRedirects(response, reverse("sms_broadcast", args=[batch.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(sorted(n for n, _ in gw.sent), ["256772000002", "256772123456"])
        self.assertEqual(balance_pages(), 8)

    @override_settings(**LIVE)
    def test_a_message_bigger_than_the_credit_is_refused_before_sending(self):
        give_credit(1)
        big, _ = self._customer_who_spent("Big", "0772000002", 9000)
        gw = Gateway()
        with mock.patch("sms.services.ego_send", gw):
            self.client.post(reverse("sms_compose"), {"body": "a" * 200, "customer": [str(big.pk)],
                                                      "step": "send"})
        self.assertEqual(gw.sent, [])
        self.assertFalse(Broadcast.objects.exists())
