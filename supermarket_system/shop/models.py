from datetime import time

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """A person who logs in. Either the owner/manager or a cashier at the till.

    The paper asks for "Served by (seller)" on every receipt - that only means
    something if each cashier signs in as themselves, so roles live here.
    """

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrator (owner / manager)"
        CASHIER = "CASHIER", "Cashier (seller)"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CASHIER)
    phone = models.CharField(max_length=30, blank=True)

    # Whether this person has been through the guided tour. It lives on the
    # user rather than in the browser on purpose: the shop runs on two
    # computers, and being offered the tour again on the second one - after he
    # has already sat through it on the first - reads as the system forgetting
    # who he is.
    has_taken_tour = models.BooleanField(default=False)

    class Meta:
        ordering = ["first_name", "username"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        full = self.get_full_name().strip()
        return full or self.username

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def can_see_cost(self):
        """Only admins see buying prices and profit."""
        return self.is_admin


class ShopSettings(models.Model):
    """The 'Company name' from the client's list, plus everything else that
    has to appear on a printed receipt. There is only ever one row.
    """

    company_name = models.CharField(max_length=120, default="My Supermarket")
    tagline = models.CharField(max_length=120, blank=True)
    address = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=60, blank=True)
    email = models.EmailField(blank=True)
    tin = models.CharField("TIN / Reg. No.", max_length=40, blank=True)
    logo = models.ImageField(upload_to="shop/", blank=True, null=True)

    currency = models.CharField(max_length=10, default="UGX")
    vat_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Set to 0 if the shop does not charge VAT.")

    receipt_footer = models.CharField(
        max_length=200, default="Thank you for shopping with us. Goods once sold are not returnable.")
    receipt_width = models.CharField(
        max_length=10, default="80mm",
        choices=[("58mm", "58mm thermal roll"), ("80mm", "80mm thermal roll"), ("A4", "A4 paper")],
        help_text="Choose A4 if the shop has an ordinary printer.")

    default_reorder_level = models.PositiveIntegerField(
        default=5, help_text="A product is 'low stock' at or below this, unless it sets its own.")
    expiry_warning_days = models.PositiveIntegerField(
        default=30, help_text="Warn this many days before an item expires.")

    # -- the watch on the tills (online) ----------------------------------
    # The owner's fear, in his own words: a cashier switches the router off
    # while he is away and sells without the system seeing it. Online, every
    # open till checks in once a minute; these say when silence is news.
    opens_at = models.TimeField(
        "Shop opens at", default=time(7, 0),
        help_text="A till that is silent before this is not news.")
    closes_at = models.TimeField(
        "Shop closes at", default=time(22, 0),
        help_text="After this, silent tills are expected.")
    silence_alert_minutes = models.PositiveIntegerField(
        "Alert after (minutes)", default=10,
        help_text="Email the owner when no till has reached the system for this "
                  "many minutes while the shop is open.")

    # The annual hosting, paid to CampusNect Smart Technologies. Set by
    # setup_maqam from the server's environment and left off the Shop details
    # form on purpose - see ShopSettingsForm.
    hosting_paid_until = models.DateField(null=True, blank=True)

    # The trading day whose end-of-day summary has already gone to the owner,
    # so the five-minute check sends it exactly once.
    summary_sent_for = models.DateField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Shop settings"
        verbose_name_plural = "Shop settings"

    def __str__(self):
        return self.company_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("The shop settings cannot be deleted.")

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def hosting_days_left(self):
        if not self.hosting_paid_until:
            return None
        return (self.hosting_paid_until - timezone.localdate()).days

    def is_open_at(self, moment):
        """Is the shop trading at this moment? Copes with a shop that closes
        after midnight: 07:00 to 01:00 still means open at half past twelve."""
        now = timezone.localtime(moment).time()
        if self.opens_at <= self.closes_at:
            return self.opens_at <= now < self.closes_at
        return now >= self.opens_at or now < self.closes_at


# ---------------------------------------------------------------------------
# The audit trail
# ---------------------------------------------------------------------------
class AuditEvent(models.Model):
    """Something the owner would want to be able to ask about later: who did
    it, when, from which machine, and what it was before.

    Written once and never edited. There is no edit screen and no delete, on
    purpose - a trail somebody can tidy up is not a trail. The person is kept
    as a name as well as a link, so the line still reads correctly after a
    cashier's account has been renamed or removed.
    """

    class Action(models.TextChoices):
        SIGN_IN = "SIGN_IN", "Signed in"
        SIGN_OUT = "SIGN_OUT", "Signed out"
        SIGN_IN_FAILED = "SIGN_IN_FAILED", "Failed sign-in"
        SALE_VOIDED = "SALE_VOIDED", "Sale voided"
        PRICE_CHANGED = "PRICE_CHANGED", "Price changed"
        PRODUCT_DELETED = "PRODUCT_DELETED", "Product deleted / retired"
        STOCK_ADJUSTED = "STOCK_ADJUSTED", "Stock adjusted"
        STOCK_WRITTEN_OFF = "STOCK_WRITTEN_OFF", "Stock written off"
        STOCK_COUNTED = "STOCK_COUNTED", "Stock take recorded"
        DRAWER_HANDED_OVER = "DRAWER_HANDED_OVER", "Drawer handed over"
        USER_CREATED = "USER_CREATED", "User added"
        USER_CHANGED = "USER_CHANGED", "User changed"
        PASSWORD_RESET = "PASSWORD_RESET", "Password reset"
        SETTINGS_CHANGED = "SETTINGS_CHANGED", "Shop details changed"
        BACKUP_DOWNLOADED = "BACKUP_DOWNLOADED", "Data downloaded"
        TILLS_SILENT = "TILLS_SILENT", "Tills went silent"
        TILLS_BACK = "TILLS_BACK", "Tills back online"

    #: What the owner should read first. Shown in red on his phone.
    SERIOUS = {
        Action.SIGN_IN_FAILED, Action.SALE_VOIDED, Action.PRICE_CHANGED,
        Action.PRODUCT_DELETED, Action.STOCK_ADJUSTED, Action.STOCK_WRITTEN_OFF,
        Action.PASSWORD_RESET, Action.TILLS_SILENT, Action.BACKUP_DOWNLOADED,
    }

    at = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="audit_events")
    username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=24, choices=Action.choices, db_index=True)
    summary = models.CharField(max_length=255)
    # "field: old -> new", one per line. Plain text, so it reads the same in
    # an email, on a phone and in the database itself.
    changes = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    reference = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ["-at", "-id"]

    def __str__(self):
        return f"{timezone.localtime(self.at):%d %b %H:%M} {self.username} {self.summary}"

    @property
    def is_serious(self):
        return self.action in self.SERIOUS


# ---------------------------------------------------------------------------
# The watch on the tills
# ---------------------------------------------------------------------------
class Till(models.Model):
    """One browser used as a till, known by a random id it keeps for itself.

    One row per till, updated on every check-in - not a row per check-in,
    which would be fourteen hundred rows a day per till saying nothing new.
    """

    key = models.CharField(max_length=40, unique=True)
    label = models.CharField(max_length=120, blank=True)
    # A phone is never a till. Without this, the owner watching his shop from
    # home would himself keep the alarm quiet while every real till was off.
    is_phone = models.BooleanField(default=False)
    last_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+")
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    first_seen = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-last_seen"]

    def __str__(self):
        return self.label or self.key[:8]

    @property
    def minutes_silent(self):
        return max(0, int((timezone.now() - self.last_seen).total_seconds() // 60))


class TillGap(models.Model):
    """A stretch of trading hours when no till reached the system.

    Opened by the scheduled check, closed by the first till to check in
    again - so the end time is exact, not rounded to the next check. Each gap
    tells the owner twice: when it starts, and when the tills come back,
    with how long they were gone.
    """

    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    alert_sent_at = models.DateTimeField(null=True, blank=True)
    back_alert_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Silent from {timezone.localtime(self.started_at):%d %b %H:%M}"

    @property
    def is_open(self):
        return self.ended_at is None

    @property
    def minutes(self):
        end = self.ended_at or timezone.now()
        return max(0, int((end - self.started_at).total_seconds() // 60))

    @property
    def length_label(self):
        return minutes_label(self.minutes)


def minutes_label(minutes):
    if minutes < 60:
        return f"{minutes} minute{'' if minutes == 1 else 's'}"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} hour{'' if hours == 1 else 's'} {minutes} min"
