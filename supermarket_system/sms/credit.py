"""Turning money into pages - once, however many times a payment is confirmed."""
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import flutterwave, services
from .models import TopUp

#: The same bundles as St Lucia and Team. Below 5,000 the withdrawal fees eat
#: the sale, so the smallest is enforced on the server, not only in the buttons.
BUNDLES = [5000, 10000, 20000, 50000]


def new_topup(amount, method=TopUp.Method.ONLINE, note="", reference=None):
    unit = services.price()
    return TopUp.objects.create(
        method=method, amount=amount, price_per_page=unit,
        pages=amount // unit, note=note[:200],
        reference=reference or f"MQ-SMS-{secrets.token_hex(5).upper()}")


def mark_paid(topup, gateway_id=""):
    """Credit it. Idempotent: the return page and a later check can both land."""
    with transaction.atomic():
        row = TopUp.objects.get(pk=topup.pk)
        if row.status == TopUp.Status.PAID:
            return False
        row.status = TopUp.Status.PAID
        row.paid_at = timezone.now()
        row.gateway_id = str(gateway_id or "")[:40]
        row.save(update_fields=["status", "paid_at", "gateway_id"])
    return True


def confirm(topup):
    """Ask Flutterwave whether this top-up was paid; credit it if so.

    Trusts nothing from the browser: the amount, the currency and the status
    all come from Flutterwave's own record.
    """
    if topup.status != TopUp.Status.PENDING or not flutterwave.configured():
        return False
    data = flutterwave.verify_reference(topup.reference)
    if not data:
        return False
    if (data.get("status") == "successful" and data.get("currency") == "UGX"
            and float(data.get("amount") or 0) >= topup.amount
            and data.get("tx_ref") == topup.reference):
        return mark_paid(topup, data.get("id"))
    if data.get("status") == "failed":
        TopUp.objects.filter(pk=topup.pk, status=TopUp.Status.PENDING).update(
            status=TopUp.Status.FAILED)
    return False


def confirm_pending(max_age_days=3):
    """Check every recent unpaid top-up. Called when the SMS page opens."""
    since = timezone.now() - timedelta(days=max_age_days)
    credited = 0
    for topup in TopUp.objects.filter(status=TopUp.Status.PENDING,
                                      method=TopUp.Method.ONLINE, created_at__gte=since):
        credited += bool(confirm(topup))
    return credited
