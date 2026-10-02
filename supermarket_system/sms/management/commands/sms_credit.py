"""Credit paid outside the website - cash, or Mobile Money to CampusNect.

    python manage.py sms_credit 20000 --ref "MoMo 1234567890"
    python manage.py sms_credit --balance

Priced at today's page price and frozen, exactly like an online purchase.
The reference must be unique, so the same payment cannot be added twice.
"""
from django.core.management.base import BaseCommand, CommandError

from sms import credit, services
from sms.models import TopUp, balance_pages


class Command(BaseCommand):
    help = "Add SMS credit paid by cash or Mobile Money, or show the balance."

    def add_arguments(self, parser):
        parser.add_argument("amount", nargs="?", type=int, help="UGX received")
        parser.add_argument("--ref", default="", help="The payment's own reference")
        parser.add_argument("--balance", action="store_true")

    def handle(self, *args, **opts):
        if opts["balance"] or not opts["amount"]:
            self.stdout.write(f"{balance_pages()} SMS pages left "
                              f"(UGX {services.price()} a page).")
            return
        amount = opts["amount"]
        if amount < services.price():
            raise CommandError("That is less than one page.")
        ref = (opts["ref"] or "").strip()
        if not ref:
            raise CommandError("Give the payment's reference with --ref, so it cannot "
                               "be added twice.")
        reference = f"MQ-REC-{ref}"[:64]
        if TopUp.objects.filter(reference=reference).exists():
            raise CommandError(f"{ref} has already been added.")
        topup = credit.new_topup(amount, method=TopUp.Method.RECORDED,
                                 note=ref, reference=reference)
        credit.mark_paid(topup)
        self.stdout.write(self.style.SUCCESS(
            f"Added {topup.pages} pages for UGX {amount:,}. "
            f"{balance_pages()} pages left."))
