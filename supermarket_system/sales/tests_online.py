"""Checks on going online at maqam.campusnect.com.

Named after the move, like tests_go_live.py, because each of these exists to
answer something Mr. Mujuzi asked or feared when he agreed to it: will I know
if the tills go quiet, can I see who did what, can I watch from my phone, is
the shop safe on the internet, and will his own data come up intact.
"""
import io
import os
import sqlite3
import tempfile
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.forms.models import model_to_dict
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from sales.models import Sale
from sales.services import open_shift, record_sale
from shop.forms import ShopSettingsForm
from shop.models import AuditEvent, ShopSettings, Till, TillGap, User
from shop.watch import check_in, check_tills

from .tests import ShopTestCase

Action = AuditEvent.Action
PHONE_UA = "Mozilla/5.0 (Linux; Android 13) Mobile Safari/537.36"
DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"


def at(hour, minute=0, day=None):
    day = day or timezone.localdate()
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


# ---------------------------------------------------------------------------
# The audit trail
# ---------------------------------------------------------------------------
class AuditTrailTests(ShopTestCase):
    def sell(self, product):
        return record_sale(
            user=self.cashier,
            lines=[{"product": product, "quantity": Decimal("1"), "unit_price": Decimal("1500")}],
            amount_paid=Decimal("2000"))

    def test_signing_in_and_a_wrong_password_are_both_written_down(self):
        self.client.post(reverse("login"), {"username": "cashier", "password": "nope"})
        self.client.post(reverse("login"), {"username": "cashier", "password": "pw12345"})
        failed = AuditEvent.objects.get(action=Action.SIGN_IN_FAILED)
        self.assertEqual(failed.reference, "cashier")
        self.assertTrue(AuditEvent.objects.filter(action=Action.SIGN_IN, user=self.cashier).exists())

    def test_the_wrong_password_itself_is_never_stored(self):
        self.client.post(reverse("login"), {"username": "cashier", "password": "Secret-Guess-99"})
        for e in AuditEvent.objects.all():
            self.assertNotIn("Secret-Guess-99", e.summary + e.changes + e.reference)

    def test_a_void_names_the_receipt_the_amount_and_the_reason(self):
        product = self.make_product()
        self.deliver(product, 5)
        sale = self.sell(product)
        self.client.login(username="owner", password="pw12345")
        self.client.post(reverse("sale_void", args=[sale.pk]), {"reason": "customer changed mind"})
        e = AuditEvent.objects.get(action=Action.SALE_VOIDED)
        self.assertEqual(e.reference, sale.receipt_no)
        self.assertIn("customer changed mind", e.changes)
        self.assertEqual(e.user, self.owner)

    def _edit(self, product, **changes):
        from inventory.forms import ProductForm
        data = {k: v for k, v in model_to_dict(product).items()
                if k in ProductForm.base_fields and v is not None}
        data.update(changes)
        self.client.login(username="owner", password="pw12345")
        return self.client.post(reverse("product_edit", args=[product.pk]), data)

    def test_a_price_change_records_old_and_new(self):
        product = self.make_product(selling="1500")
        self._edit(product, selling_price="1800")
        e = AuditEvent.objects.get(action=Action.PRICE_CHANGED)
        self.assertIn("1,500 -> 1,800", e.changes)

    def test_editing_without_touching_a_price_writes_nothing(self):
        """1500.00 from the database and 1500 from the form are the same
        price. Compared as text they differ, and every save would log a price
        change that never happened."""
        product = self.make_product(selling="1500")
        self._edit(product, name="Soda 500ml cold")
        self.assertFalse(AuditEvent.objects.filter(action=Action.PRICE_CHANGED).exists())

    def test_cash_up_records_the_shortage(self):
        product = self.make_product()
        self.deliver(product, 5)
        open_shift(user=self.cashier, opening_float=Decimal("0"))
        self.sell(product)
        self.client.login(username="cashier", password="pw12345")
        self.client.post(reverse("cash_up"), {"counted_cash": "1000", "note": ""})
        e = AuditEvent.objects.get(action=Action.DRAWER_HANDED_OVER)
        self.assertIn("SHORT 500", e.summary)

    def test_a_password_reset_and_a_new_user_are_recorded(self):
        self.client.login(username="owner", password="pw12345")
        self.client.post(reverse("user_password", args=[self.cashier.pk]),
                         {"password1": "newpass", "password2": "newpass"})
        self.assertTrue(AuditEvent.objects.filter(action=Action.PASSWORD_RESET).exists())

    def test_a_stock_adjustment_is_recorded(self):
        product = self.make_product()
        self.deliver(product, 5)
        self.client.login(username="owner", password="pw12345")
        self.client.post(reverse("product_adjust", args=[product.pk]),
                         {"quantity": "-2", "kind": "ADJUST", "reason": "broken"})
        self.assertTrue(AuditEvent.objects.filter(action=Action.STOCK_ADJUSTED).exists())

    def test_only_the_owner_can_read_the_trail(self):
        self.client.login(username="cashier", password="pw12345")
        self.assertEqual(self.client.get(reverse("audit")).status_code, 403)
        self.client.login(username="owner", password="pw12345")
        self.assertEqual(self.client.get(reverse("audit")).status_code, 200)

    def test_the_trail_page_filters_by_action(self):
        AuditEvent.objects.create(action=Action.SALE_VOIDED, summary="Voided R1")
        AuditEvent.objects.create(action=Action.SIGN_IN, summary="Grace signed in")
        self.client.login(username="owner", password="pw12345")
        page = self.client.get(reverse("audit") + "?action=SALE_VOIDED").content.decode()
        self.assertIn("Voided R1", page)
        self.assertNotIn("Grace signed in", page)


# ---------------------------------------------------------------------------
# Signing in on the internet
# ---------------------------------------------------------------------------
class SignInLockTests(ShopTestCase):
    def fail(self, n, name="cashier"):
        for _ in range(n):
            self.client.post(reverse("login"), {"username": name, "password": "wrong"})

    @override_settings(ONLINE=True)
    def test_online_five_wrong_passwords_lock_the_name(self):
        self.fail(5)
        r = self.client.post(reverse("login"), {"username": "cashier", "password": "pw12345"})
        self.assertContains(r, "Too many wrong passwords")
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(ONLINE=True)
    def test_the_lock_is_per_name(self):
        self.fail(5, name="cashier")
        self.client.post(reverse("login"), {"username": "owner", "password": "pw12345"})
        self.assertIn("_auth_user_id", self.client.session)

    @override_settings(ONLINE=False)
    def test_on_the_shop_computer_there_is_no_lock(self):
        """Offline only somebody standing in the shop can reach the screen.
        Locking the owner out of his own till over a typo would be worse."""
        self.fail(6)
        self.client.post(reverse("login"), {"username": "cashier", "password": "pw12345"})
        self.assertIn("_auth_user_id", self.client.session)


# ---------------------------------------------------------------------------
# The watch on the tills
# ---------------------------------------------------------------------------
@override_settings(OWNER_ALERT_EMAILS=["owner@example.com"])
class TillWatchTests(ShopTestCase):
    def setUp(self):
        super().setUp()
        self.shop.opens_at = time(7, 0)
        self.shop.closes_at = time(22, 0)
        self.shop.silence_alert_minutes = 10
        self.shop.save()

    def test_silent_tills_in_trading_hours_open_a_gap_and_email_the_owner(self):
        check_in(key="till-1", label="Counter 1", now=at(9, 0))
        check_tills(now=at(9, 15))
        gap = TillGap.objects.get()
        self.assertEqual(gap.started_at, at(9, 0))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("since 09:00", mail.outbox[0].subject)
        self.assertTrue(AuditEvent.objects.filter(action=Action.TILLS_SILENT).exists())

    def test_a_short_quiet_spell_is_not_news(self):
        check_in(key="till-1", now=at(9, 0))
        check_tills(now=at(9, 5))
        self.assertFalse(TillGap.objects.exists())
        self.assertEqual(mail.outbox, [])

    def test_the_owner_is_told_once_not_every_five_minutes(self):
        check_in(key="till-1", now=at(9, 0))
        for minute in (15, 20, 25, 30):
            check_tills(now=at(9, minute))
        self.assertEqual(TillGap.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_coming_back_closes_the_gap_exactly_and_sends_how_long(self):
        check_in(key="till-1", now=at(9, 0))
        check_tills(now=at(9, 15))
        check_in(key="till-1", now=at(10, 2))
        gap = TillGap.objects.get()
        self.assertEqual(gap.ended_at, at(10, 2))
        check_tills(now=at(10, 5))
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("1 hour 2 min", mail.outbox[1].body)

    def test_a_phone_never_counts_as_a_till(self):
        """The owner reading his phone at home must not keep the alarm quiet
        while every till in the shop is switched off."""
        check_in(key="till-1", now=at(9, 0))
        check_in(key="phone", phone=True, now=at(9, 14))
        check_tills(now=at(9, 15))
        self.assertTrue(TillGap.objects.filter(ended_at__isnull=True).exists())
        check_in(key="phone", phone=True, now=at(9, 20))
        self.assertTrue(TillGap.objects.filter(ended_at__isnull=True).exists())

    def test_closed_hours_are_quiet(self):
        check_in(key="till-1", now=at(6, 0))
        check_tills(now=at(6, 50))
        check_tills(now=at(23, 0))
        self.assertFalse(TillGap.objects.exists())

    def test_no_till_at_all_after_opening_raises_it_from_opening_time(self):
        check_tills(now=at(7, 30))
        self.assertEqual(TillGap.objects.get().started_at, at(7, 0))

    def test_a_gap_open_at_closing_time_ends_there_not_next_morning(self):
        check_in(key="till-1", now=at(20, 0))
        check_tills(now=at(20, 30))
        check_tills(now=at(22, 5))
        gap = TillGap.objects.get()
        self.assertEqual(gap.ended_at, at(22, 5))

    def test_the_nightly_summary_goes_once_after_closing(self):
        product = self.make_product()
        self.deliver(product, 5)
        record_sale(user=self.cashier,
                    lines=[{"product": product, "quantity": Decimal("2"),
                            "unit_price": Decimal("1500")}],
                    amount_paid=Decimal("3000"))
        check_in(key="till-1", now=timezone.now())
        evening = at(22, 10)
        check_tills(now=evening)
        check_tills(now=evening + timedelta(minutes=5))
        summaries = [m for m in mail.outbox if "sold" in m.subject]
        self.assertEqual(len(summaries), 1)
        self.assertIn("3,000", summaries[0].subject)

    def test_shop_closing_after_midnight_still_counts_as_open(self):
        self.shop.opens_at, self.shop.closes_at = time(7, 0), time(1, 0)
        self.assertTrue(self.shop.is_open_at(at(0, 30)))
        self.assertFalse(self.shop.is_open_at(at(3, 0)))


class TillCheckInEndpointTests(ShopTestCase):
    def test_nobody_signed_out_can_keep_the_alarm_quiet(self):
        r = self.client.post(reverse("till_check_in"), '{"till": "x"}',
                             content_type="application/json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Till.objects.exists())

    def test_a_till_checks_in(self):
        self.client.login(username="cashier", password="pw12345")
        self.client.post(reverse("till_check_in"), '{"till": "abc", "label": "Counter"}',
                         content_type="application/json", HTTP_USER_AGENT=DESKTOP_UA)
        till = Till.objects.get()
        self.assertEqual(till.last_user, self.cashier)
        self.assertFalse(till.is_phone)

    def test_a_phone_is_recognised_by_the_server_not_by_its_own_word(self):
        self.client.login(username="owner", password="pw12345")
        self.client.post(reverse("till_check_in"), '{"till": "p", "label": "Computer"}',
                         content_type="application/json", HTTP_USER_AGENT=PHONE_UA)
        self.assertTrue(Till.objects.get().is_phone)

    def test_every_signed_in_page_carries_the_check_in_except_the_phone_view(self):
        self.client.login(username="owner", password="pw12345")
        self.assertContains(self.client.get(reverse("dashboard")), "js/till.js")
        self.assertNotContains(self.client.get(reverse("owner")), "js/till.js")


# ---------------------------------------------------------------------------
# The phone app
# ---------------------------------------------------------------------------
class PhoneAppTests(ShopTestCase):
    def test_the_owner_view_shows_todays_takings(self):
        product = self.make_product()
        self.deliver(product, 5)
        record_sale(user=self.cashier,
                    lines=[{"product": product, "quantity": Decimal("3"),
                            "unit_price": Decimal("1500")}],
                    amount_paid=Decimal("4500"))
        self.client.login(username="owner", password="pw12345")
        r = self.client.get(reverse("owner"))
        self.assertContains(r, "4,500")
        self.assertContains(r, "Today so far")

    def test_a_cashier_cannot_open_the_owner_view(self):
        self.client.login(username="cashier", password="pw12345")
        self.assertEqual(self.client.get(reverse("owner")).status_code, 403)

    def test_the_owner_view_raises_the_alarm_for_an_open_gap(self):
        TillGap.objects.create(started_at=timezone.now() - timedelta(minutes=30))
        self.client.login(username="owner", password="pw12345")
        self.assertContains(self.client.get(reverse("owner")), "No till has reached the system")

    def test_manifest_and_service_worker(self):
        m = self.client.get(reverse("manifest"))
        self.assertEqual(m["Content-Type"], "application/manifest+json")
        data = m.json()
        self.assertEqual(data["display"], "standalone")
        for icon in data["icons"]:
            path = Path(__file__).resolve().parent.parent / icon["src"].lstrip("/")
            self.assertTrue(path.exists(), icon["src"])
        sw = self.client.get(reverse("service_worker"))
        self.assertEqual(sw["Content-Type"], "application/javascript")
        self.assertEqual(sw["Service-Worker-Allowed"], "/")

    def test_the_service_worker_precaches_only_files_that_exist(self):
        """cache.addAll fails as a whole if one file 404s, and then the app
        never installs on his phone. Every listed file must be real."""
        import re
        root = Path(__file__).resolve().parent.parent
        sw = (root / "static" / "js" / "sw.js").read_text(encoding="utf-8")
        for path in re.findall(r"'(/static/[^']+)'", sw):
            self.assertTrue((root / path.lstrip("/")).exists(), path)

    def test_the_service_worker_never_caches_pages_or_posts(self):
        root = Path(__file__).resolve().parent.parent
        sw = (root / "static" / "js" / "sw.js").read_text(encoding="utf-8")
        self.assertIn("if (req.method !== 'GET') return;", sw)
        navigate = sw.split("req.mode === 'navigate'")[1].split("return;")[0]
        self.assertNotIn("cache.put", navigate)

    def test_offline_page_has_no_figures(self):
        r = self.client.get(reverse("offline"))
        self.assertContains(r, "no connection")
        self.assertNotContains(r, "UGX")


# ---------------------------------------------------------------------------
# The yearly hosting reminder
# ---------------------------------------------------------------------------
class HostingNoticeTests(ShopTestCase):
    def set_days(self, days):
        self.shop.hosting_paid_until = timezone.localdate() + timedelta(days=days)
        self.shop.save()

    @override_settings(ONLINE=True)
    def test_the_owner_sees_it_in_the_last_month(self):
        self.set_days(20)
        self.client.login(username="owner", password="pw12345")
        self.assertContains(self.client.get(reverse("dashboard")), "ends in 20 days")

    @override_settings(ONLINE=True)
    def test_not_before_the_last_month(self):
        self.set_days(60)
        self.client.login(username="owner", password="pw12345")
        self.assertNotContains(self.client.get(reverse("dashboard")), "hosting year")

    @override_settings(ONLINE=True)
    def test_a_cashier_never_sees_it(self):
        self.set_days(5)
        self.client.login(username="cashier", password="pw12345")
        self.assertNotContains(self.client.get(reverse("dashboard")), "hosting year")

    @override_settings(ONLINE=False)
    def test_never_on_the_shop_computer(self):
        self.set_days(5)
        self.client.login(username="owner", password="pw12345")
        self.assertNotContains(self.client.get(reverse("dashboard")), "hosting year")

    def test_the_shop_cannot_extend_its_own_hosting(self):
        self.assertNotIn("hosting_paid_until", ShopSettingsForm().fields)


# ---------------------------------------------------------------------------
# setup_maqam on the online server
# ---------------------------------------------------------------------------
class SetupMaqamOnlineTests(ShopTestCase):
    def run_setup(self, *args, **env):
        with mock.patch.dict(os.environ, env, clear=False):
            call_command("setup_maqam", *args, stdout=io.StringIO(), stderr=io.StringIO())

    def test_his_real_address_and_phone_print_on_receipts(self):
        self.run_setup(MAQAM_OWNER_PASSWORD="first-pass")
        shop = ShopSettings.get()
        self.assertEqual(shop.address, "Kampala - Gulu Highway")
        self.assertEqual(shop.phone, "+256 703 649411")

    def test_re_running_never_swaps_his_own_password_back(self):
        self.run_setup(MAQAM_OWNER_PASSWORD="first-pass")
        owner = User.objects.get(username="maqam")
        owner.set_password("his-own-choice")
        owner.save()
        self.run_setup(MAQAM_OWNER_PASSWORD="first-pass")
        owner.refresh_from_db()
        self.assertTrue(owner.check_password("his-own-choice"))

    def test_reset_password_is_explicit(self):
        self.run_setup(MAQAM_OWNER_PASSWORD="first-pass")
        self.run_setup("--reset-password", MAQAM_OWNER_PASSWORD="second-pass")
        self.assertTrue(User.objects.get(username="maqam").check_password("second-pass"))

    def test_the_spare_installer_admin_is_closed_online(self):
        User.objects.create_user(username="admin", password="admin1234", role=User.Role.ADMIN)
        self.run_setup("--close-spare-admin", MAQAM_OWNER_PASSWORD="x-pass")
        spare = User.objects.get(username="admin")
        self.assertFalse(spare.is_active)
        self.assertFalse(spare.check_password("admin1234"))

    def test_hosting_date_comes_from_the_server(self):
        self.run_setup(MAQAM_OWNER_PASSWORD="x-pass", MAQAM_HOSTING_PAID_UNTIL="2027-10-01")
        self.assertEqual(ShopSettings.get().hosting_paid_until, date(2027, 10, 1))


# ---------------------------------------------------------------------------
# Bringing his data up
# ---------------------------------------------------------------------------
class ImportShopDbTests(ShopTestCase):
    def snapshot(self):
        """A real file holding this test's database.

        Written with iterdump, NOT Connection.backup: the test database is a
        shared-cache in-memory one inside an open transaction, and backup()
        retries a locked source forever - the whole suite hangs. On the server
        the source is a plain file and backup() is the right tool."""
        handle, name = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(name) and os.unlink(name))
        connection.ensure_connection()
        script = "\n".join(connection.connection.iterdump())
        target = sqlite3.connect(name)
        target.executescript(script)
        target.close()
        return name

    def test_check_reads_the_file_and_changes_nothing(self):
        product = self.make_product()
        self.deliver(product, 5)
        path = self.snapshot()
        out = io.StringIO()
        call_command("import_shop_db", path, "--check", stdout=out)
        text = out.getvalue()
        self.assertIn("Products:", text)
        self.assertIn("owner", text)
        self.assertIn("Nothing has been changed", text)

    def test_a_file_that_is_not_the_shop_database_is_refused(self):
        handle, name = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.addCleanup(os.unlink, name)
        db = sqlite3.connect(name)
        db.execute("CREATE TABLE something(x)")
        db.commit()
        db.close()
        with self.assertRaisesMessage(CommandError, "not the supermarket system"):
            call_command("import_shop_db", name, "--check", stdout=io.StringIO())

    def test_a_file_from_newer_code_is_refused(self):
        path = self.snapshot()
        db = sqlite3.connect(path)
        db.execute("INSERT INTO django_migrations(app, name, applied) "
                   "VALUES ('sales', '0099_from_the_future', '2027-01-01')")
        db.commit()
        db.close()
        with self.assertRaisesMessage(CommandError, "NEWER code"):
            call_command("import_shop_db", path, "--check", stdout=io.StringIO())


# ---------------------------------------------------------------------------
# The front door
# ---------------------------------------------------------------------------
class SignInPageTests(ShopTestCase):
    def test_the_page_is_whole_without_any_template_noise(self):
        page = self.client.get(reverse("login")).content.decode()
        for noise in ("{#", "#}", "{%", "%}"):
            self.assertNotIn(noise, page)
        self.assertIn('name="username"', page)
        self.assertIn('name="password"', page)

    def test_fonts_are_served_from_the_shop_not_the_internet(self):
        page = self.client.get(reverse("login")).content.decode()
        self.assertNotIn("fonts.googleapis", page)
        self.assertNotIn("fonts.gstatic", page)
        css = (Path(__file__).resolve().parent.parent / "static" / "css" / "login.css").read_text()
        self.assertNotIn("http", css.split("*/", 1)[1].replace("http://www.w3.org", ""))

    @override_settings(ONLINE=False)
    def test_offline_it_still_says_nothing_leaves_the_computer(self):
        self.assertContains(self.client.get(reverse("login")), "runs on this computer only")

    @override_settings(ONLINE=True)
    def test_online_it_says_what_protects_him(self):
        self.assertContains(self.client.get(reverse("login")), "every sign-in is recorded")

    def test_wrong_password_message_is_the_friendly_one(self):
        r = self.client.post(reverse("login"), {"username": "owner", "password": "bad"})
        self.assertContains(r, "Check the caps")
