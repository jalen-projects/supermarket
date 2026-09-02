"""Applies MAQAM FOOD CITY SUPERMARKET's branding and the owner's login.

    python manage.py setup_maqam

Safe to run again - it only overwrites the shop's identity fields and never
touches stock, sales or any other user. It exists as a command rather than a
one-off edit because the online demo runs on a host with a throwaway disk:
the database and the media folder are rebuilt from nothing on every deploy,
so the name, the logo and his password have to be re-applied automatically.

The password comes from MAQAM_OWNER_PASSWORD when that is set, so the real
one lives in the host's environment and never in this repository.
"""
import os
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from shop.models import ShopSettings, User

COMPANY = "MAQAM FOOD CITY SUPERMARKET"
TAGLINE = "Fresh food, fair prices"

# Placeholders until the client confirms his own details - they print on every
# receipt, so they are the first thing to correct under Settings.
ADDRESS = "Kampala, Uganda"
PHONE = "0700 000 000"

OWNER_USERNAME = "maqam"
OWNER_NAME = "Maqam Food City"
FALLBACK_PASSWORD = "maqam-food-2026"

LOGO_SOURCE = "brand/maqam-logo.png"     # inside static/
LOGO_TARGET = "shop/maqam-logo.png"      # inside media/


class Command(BaseCommand):
    help = "Apply Maqam Food City branding and create the owner's login."

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

        shop.save()
        self.stdout.write(self.style.SUCCESS(f"Shop branded as {COMPANY}"))

        password = os.environ.get("MAQAM_OWNER_PASSWORD") or FALLBACK_PASSWORD
        owner, made = User.objects.get_or_create(
            username=OWNER_USERNAME,
            defaults={"first_name": OWNER_NAME, "role": User.Role.ADMIN},
        )
        # The role is re-asserted every run: he must always land as an admin so
        # the buying prices and the profit report are visible to him.
        owner.role = User.Role.ADMIN
        owner.is_staff = True
        owner.is_superuser = True
        owner.set_password(password)
        owner.save()

        verb = "created" if made else "password reset"
        self.stdout.write(self.style.SUCCESS(
            f"Owner login {verb}: username '{OWNER_USERNAME}'"))
