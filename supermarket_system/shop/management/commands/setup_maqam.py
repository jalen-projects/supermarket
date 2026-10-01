"""Applies MAQAM FOOD CITY SUPERMARKET's branding and the owner's login.

    python manage.py setup_maqam

Safe to run again - it only overwrites the shop's identity fields and never
touches stock, sales or any other user. It exists as a command rather than a
one-off edit because the online demo runs on a host with a throwaway disk:
the database and the media folder are rebuilt from nothing on every deploy,
so the name, the logo and his password have to be re-applied automatically.

The password comes from MAQAM_OWNER_PASSWORD when that is set, so the real
one lives in the host's environment and never in this repository.

ON THE ONLINE SERVER (maqam.campusnect.com) this command is run after his
shop's data has been brought up, so his account already exists with the
password HE chose. It is therefore only set when the account is being created,
or when --reset-password is given on purpose; re-running the command never
quietly swaps his password back to one somebody else knows. Online it also
closes the spare `admin` account INSTALL.bat made, whose password was printed
on the installer's screen - fine behind his shop door, a hole on the internet.

MAQAM_HOSTING_PAID_UNTIL (YYYY-MM-DD) sets the date his paid hosting year
runs to; the owner sees a reminder in the last 30 days.
"""
import os
import secrets
import shutil

from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from shop.models import ShopSettings, User

COMPANY = "MAQAM FOOD CITY SUPERMARKET"
TAGLINE = "Fresh food, fair prices"

# His shop's own details, given by Mr. Jamil Mujuzi on 1 Oct 2026. They print
# on every receipt. His personal email is NOT here: this repository is public,
# and the alerts read it from MAQAM_ALERT_EMAIL on the server instead.
ADDRESS = "Kampala - Gulu Highway"
PHONE = "+256 703 649411"

OWNER_USERNAME = "maqam"
OWNER_NAME = "Maqam Food City"

# Only ever used for a first run on the shop's own machine, which is offline
# and behind his own front door. It is in a PUBLIC repository, so it must never
# be the password on anything reachable from the internet - see handle().
SETUP_PASSWORD = "change-me-on-first-login"

LOGO_SOURCE = "brand/maqam-logo.png"     # inside static/
LOGO_TARGET = "shop/maqam-logo.png"      # inside media/


class Command(BaseCommand):
    help = "Apply Maqam Food City branding and create the owner's login."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-password", action="store_true",
            help="Set the owner's password from MAQAM_OWNER_PASSWORD even though "
                 "the account already exists.")
        parser.add_argument(
            "--close-spare-admin", action="store_true",
            help="Lock the installer's 'admin' account. Used on the online "
                 "server, where its printed password would be a way in.")

    @transaction.atomic
    def handle(self, *args, **options):
        shop = ShopSettings.get()
        shop.company_name = COMPANY
        shop.tagline = TAGLINE
        shop.address = ADDRESS
        shop.phone = PHONE
        shop.currency = "UGX"
        shop.receipt_footer = "Thank you for shopping at Maqam Food City. Come again!"

        source = settings.BASE_DIR / "static" / LOGO_SOURCE
        if source.exists():
            target = settings.MEDIA_ROOT / LOGO_TARGET
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            shop.logo = LOGO_TARGET
            self.stdout.write(f"Logo installed at media/{LOGO_TARGET}")
        else:
            self.stderr.write(f"Logo not found at {source} - skipped.")

        paid_until = os.environ.get("MAQAM_HOSTING_PAID_UNTIL", "").strip()
        if paid_until:
            try:
                shop.hosting_paid_until = date.fromisoformat(paid_until)
            except ValueError:
                raise CommandError(
                    f"MAQAM_HOSTING_PAID_UNTIL must look like 2027-10-01, not '{paid_until}'.")

        shop.save()
        self.stdout.write(self.style.SUCCESS(f"Shop branded as {COMPANY}"))
        if shop.hosting_paid_until:
            self.stdout.write(f"Hosting paid until {shop.hosting_paid_until:%d %B %Y}")

        if options.get("close_spare_admin"):
            self._close_spare_admin()

        owner, made = User.objects.get_or_create(
            username=OWNER_USERNAME,
            defaults={"first_name": OWNER_NAME, "role": User.Role.ADMIN},
        )
        # The role is re-asserted every run: he must always land as an admin so
        # the buying prices and the profit report are visible to him.
        owner.role = User.Role.ADMIN
        owner.is_staff = True
        owner.is_superuser = True
        reset = made or options.get("reset_password")
        if reset:
            owner.set_password(self._password())
        owner.save()

        verb = ("created" if made else "password reset" if reset
                else "kept - his own password is unchanged")
        self.stdout.write(self.style.SUCCESS(
            f"Owner login {verb}: username '{OWNER_USERNAME}'"))

    def _password(self):
        password = os.environ.get("MAQAM_OWNER_PASSWORD")
        if password:
            return password
        if os.environ.get("SMMS_ONLINE") == "1":
            # Facing the internet with no password supplied. Anything written
            # in this file is public, so lock the account with something nobody
            # knows rather than something everybody can read. Set
            # MAQAM_OWNER_PASSWORD to make it usable.
            self.stderr.write(self.style.WARNING(
                "MAQAM_OWNER_PASSWORD is not set. The owner's account has been "
                "locked with a random password - set the variable and run "
                "again with --reset-password."))
            return secrets.token_urlsafe(32)
        return SETUP_PASSWORD

    def _close_spare_admin(self):
        """Lock the installer's `admin` account. Not deleted: it may have rung
        up sales, and those receipts must keep their 'Served by'."""
        spare = User.objects.filter(username="admin").exclude(username=OWNER_USERNAME).first()
        if spare is None or not spare.is_active:
            return
        spare.is_active = False
        spare.set_unusable_password()
        spare.save(update_fields=["is_active", "password"])
        self.stdout.write(self.style.WARNING(
            "The spare 'admin' account from the installer has been closed - "
            "its password was printed on screen at install time."))
