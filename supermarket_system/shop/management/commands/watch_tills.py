"""The server's five-minute check on the shop's tills.

    python manage.py watch_tills
    python manage.py watch_tills --test-email

Run by cron every five minutes on the online server (see DEPLOY-ONLINE.md).
It emails the owner when every till goes silent during trading hours, again
when they come back, and once each night with the day's summary. Safe to run
as often as you like: each email goes exactly once.

--test-email sends one short message to MAQAM_ALERT_EMAIL and nothing else -
the way to prove the alerts will actually arrive before a day they matter.

Pointless on the shop's own computer - if that computer is off, so is this.
"""
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

from shop.models import ShopSettings
from shop.watch import alert_recipients, check_tills


class Command(BaseCommand):
    help = "Check the tills are online; alert the owner if not; send the nightly summary."

    def add_arguments(self, parser):
        parser.add_argument("--test-email", action="store_true",
                            help="Send one test message to the owner and stop.")

    def handle(self, *args, **options):
        if options["test_email"]:
            to = alert_recipients()
            if not to:
                raise CommandError("MAQAM_ALERT_EMAIL is not set - there is nobody to tell.")
            shop = ShopSettings.get()
            send_mail(f"{shop.company_name}: alerts are switched on",
                      "This is a test from your shop system. From now on you will get an "
                      "email here if the tills go silent while the shop is open, and a "
                      "summary of each day's sales at closing time.\n\n"
                      "- CampusNect Smart Technologies",
                      None, to, fail_silently=False)
            self.stdout.write(self.style.SUCCESS(f"Test email sent to {', '.join(to)}"))
            return
        self.stdout.write(check_tills())
