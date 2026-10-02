"""The shop's SMS credit, every message it paid for, and the sign-in codes.

THE CREDIT IS COUNTED IN PAGES, AT THE PRICE IT WAS BOUGHT AT. A bundle of
UGX 10,000 bought at 45 a page is 222 pages, and stays 222 pages if the price
moves later - recomputing would quietly restate a balance he has already spent
against. The balance is never stored: it is what was bought, less what was
sent, worked out every time, so it cannot drift from the records it comes from.

NOTHING IS SPENT THAT IS NOT THERE. A message that would take the balance below
zero is refused before it goes, and recorded as refused.

A MESSAGE THAT DID NOT REALLY GO COSTS NOTHING. Until MAQAM_SMS_LIVE is on,
every message is written down and priced - so the owner can see exactly what it
would have cost - and marked "not sent (test mode)".
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class TopUp(models.Model):
    """Credit bought: online through Flutterwave, or recorded by CampusNect for
    cash / mobile money paid to its number."""

    class Method(models.TextChoices):
        ONLINE = "ONLINE", "Paid online"
        RECORDED = "RECORDED", "Recorded by CampusNect"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Waiting for payment"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Not paid"

    created_at = models.DateTimeField(default=timezone.now)
    method = models.CharField(max_length=10, choices=Method.choices)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    amount = models.PositiveIntegerField(help_text="UGX")
    price_per_page = models.PositiveIntegerField(
        help_text="UGX a page on the day it was bought - frozen.")
    pages = models.PositiveIntegerField()
    reference = models.CharField(max_length=64, unique=True)
    gateway_id = models.CharField(max_length=40, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} UGX {self.amount:,} = {self.pages} pages ({self.status})"


class Broadcast(models.Model):
    """One message the owner sent to a list of people at once."""

    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, related_name="sms_broadcasts")
    body = models.TextField()
    audience = models.CharField(max_length=200)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%d %b %H:%M} to {self.audience}"


class Message(models.Model):
    """One text to one number, and what it cost."""

    class Kind(models.TextChoices):
        CODE = "CODE", "Sign-in code"
        ALERT = "ALERT", "Alert to the owner"
        BROADCAST = "BROADCAST", "Message from the owner"

    class Status(models.TextChoices):
        SENT = "SENT", "Sent"
        TEST = "TEST", "Not sent (test mode)"
        FAILED = "FAILED", "Failed"
        NO_CREDIT = "NO_CREDIT", "Not sent - no SMS credit"

    #: Statuses that used up credit.
    SPENT = (Status.SENT,)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices)
    number = models.CharField(max_length=20)
    recipient = models.CharField(max_length=120, blank=True)
    #: What the person received. A sign-in code is stored masked: the code
    #: itself is a key, and a log is the wrong place for keys.
    body = models.TextField()
    pages = models.PositiveSmallIntegerField()
    cost = models.PositiveIntegerField(help_text="UGX, at the current page price")
    gateway_reply = models.CharField(max_length=255, blank=True)
    broadcast = models.ForeignKey(Broadcast, on_delete=models.CASCADE, null=True,
                                  blank=True, related_name="messages")

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()} to {self.number}: {self.get_status_display()}"


def balance_pages():
    """Pages bought and paid for, less pages actually sent."""
    bought = TopUp.objects.filter(status=TopUp.Status.PAID).aggregate(
        n=Sum("pages"))["n"] or 0
    spent = Message.objects.filter(status__in=Message.SPENT).aggregate(
        n=Sum("pages"))["n"] or 0
    return bought - spent


# ---------------------------------------------------------------------------
# Sign-in codes
# ---------------------------------------------------------------------------
CODE_LIFETIME = timedelta(minutes=5)
CODE_ATTEMPTS = 5
RESEND_AFTER = timedelta(seconds=60)


def _hash(code):
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, code.encode(), hashlib.sha256).hexdigest()


class SignInCode(models.Model):
    """The second step of signing in online: six digits, five minutes, five
    tries. Only a keyed hash of the code is kept, so even a copy of the
    database does not let anybody in."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="sign_in_codes")
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)
    #: Where it was sent, masked, to show on the screen ("SMS to 07xx xxx 123").
    sent_to = models.CharField(max_length=200, blank=True)
    #: The owner approves a cashier's sign-in when SMS credit has run out.
    via_owner = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def issue(cls, user):
        """A fresh code for this user; any earlier one stops working."""
        cls.objects.filter(user=user, used_at__isnull=True).update(
            expires_at=timezone.now())
        code = f"{secrets.randbelow(10 ** 6):06d}"
        row = cls.objects.create(user=user, code_hash=_hash(code),
                                 expires_at=timezone.now() + CODE_LIFETIME)
        return row, code

    @property
    def is_live(self):
        return (self.used_at is None and self.attempts < CODE_ATTEMPTS
                and timezone.now() < self.expires_at)

    def matches(self, code):
        """True if the code is right. Every wrong one uses up a try."""
        if not self.is_live:
            return False
        if hmac.compare_digest(self.code_hash, _hash((code or "").strip())):
            self.used_at = timezone.now()
            self.save(update_fields=["used_at"])
            return True
        self.attempts += 1
        self.save(update_fields=["attempts"])
        return False

    @property
    def may_resend(self):
        return timezone.now() >= self.created_at + RESEND_AFTER
