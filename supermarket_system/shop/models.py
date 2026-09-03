from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


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
