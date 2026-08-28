from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, Sum
from django.utils import timezone


class Category(models.Model):
    """'Catergory' on the client's list - Beverages, Soap, Cereals, ..."""

    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


class Unit(models.Model):
    """'Measurements' - the unit a product is sold in: piece, kg, litre, crate."""

    name = models.CharField(max_length=40, unique=True)
    abbreviation = models.CharField(max_length=10)
    allow_decimals = models.BooleanField(
        default=False,
        help_text="Tick for units weighed or poured (kg, litre). Leave off for pieces.")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.abbreviation or self.name


class Supplier(models.Model):
    name = models.CharField(max_length=120, unique=True)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=60, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def with_stock(self):
        """Annotate each product with what is physically on the shelf."""
        return self.annotate(
            stock=models.functions.Coalesce(
                Sum("batches__quantity_remaining"), Decimal("0"),
                output_field=models.DecimalField(max_digits=12, decimal_places=3)))


class Product(models.Model):
    """The product master record - everything from 'Product name' down to
    'Measurements' on the client's paper.

    Note that expiry date is NOT here. Expiry belongs to a delivery, because
    the same soap delivered in March and in August expires on different days.
    It lives on StockBatch below.
    """

    name = models.CharField(max_length=150)
    barcode = models.CharField(
        max_length=64, blank=True, null=True, unique=True, db_index=True,
        help_text="Scan the item here. Leave blank for loose goods with no barcode.")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="products")

    buying_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Latest cost price. Updated automatically by each purchase.")
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    reorder_level = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True,
        help_text="Warn when stock falls to this. Blank uses the shop default.")

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    # -- stock ------------------------------------------------------------
    @property
    def stock_available(self):
        """'Stock available' - the sum of what is left in every live batch."""
        return self.batches.aggregate(t=Sum("quantity_remaining"))["t"] or Decimal("0")

    @property
    def effective_reorder_level(self):
        if self.reorder_level is not None:
            return self.reorder_level
        from shop.models import ShopSettings
        return Decimal(ShopSettings.get().default_reorder_level)

    @property
    def is_low_stock(self):
        return self.stock_available <= self.effective_reorder_level

    @property
    def profit_per_unit(self):
        return self.selling_price - self.buying_price

    @property
    def margin_percent(self):
        if not self.selling_price:
            return Decimal("0")
        return (self.profit_per_unit / self.selling_price) * 100

    @property
    def nearest_expiry(self):
        batch = (self.batches.filter(quantity_remaining__gt=0, expiry_date__isnull=False)
                 .order_by("expiry_date").first())
        return batch.expiry_date if batch else None

    def sellable_batches(self):
        """Batches to sell from, first-expiry-first-out. Expired ones are skipped -
        the system will not let a cashier sell an item that has gone bad.
        """
        today = timezone.localdate()
        return (self.batches.filter(quantity_remaining__gt=0)
                .filter(models.Q(expiry_date__isnull=True) | models.Q(expiry_date__gte=today))
                .order_by(F("expiry_date").asc(nulls_last=True), "id"))

    @property
    def sellable_quantity(self):
        return self.sellable_batches().aggregate(t=Sum("quantity_remaining"))["t"] or Decimal("0")

    @property
    def expired_quantity(self):
        today = timezone.localdate()
        return self.batches.filter(quantity_remaining__gt=0, expiry_date__lt=today).aggregate(
            t=Sum("quantity_remaining"))["t"] or Decimal("0")


class Purchase(models.Model):
    """'Purchase' - a delivery received from a supplier. This is what puts
    stock INTO the shop, and it is where buying price and expiry date are set.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        RECEIVED = "RECEIVED", "Received"

    reference = models.CharField(max_length=30, unique=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchases")
    invoice_no = models.CharField(max_length=60, blank=True)
    date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchases")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.reference} - {self.supplier}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._next_reference()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_reference():
        last = Purchase.objects.order_by("-id").first()
        return f"GRN-{(last.id + 1 if last else 1):05d}"

    @property
    def total(self):
        return sum((i.line_total for i in self.items.all()), Decimal("0"))

    @property
    def item_count(self):
        return self.items.count()


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="purchase_items")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    buying_price = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Optional. Fill in to change the product's selling price from this delivery on.")
    expiry_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.product} x {self.quantity}"

    @property
    def line_total(self):
        return (self.quantity * self.buying_price).quantize(Decimal("0.01"))


class StockBatch(models.Model):
    """One lot of one product, received on one day, expiring on one day.

    Keeping expiry per batch is what makes the 'Expired item' report truthful.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="batches")
    purchase_item = models.OneToOneField(
        PurchaseItem, on_delete=models.CASCADE, null=True, blank=True, related_name="batch")
    quantity_received = models.DecimalField(max_digits=12, decimal_places=3)
    quantity_remaining = models.DecimalField(max_digits=12, decimal_places=3)
    buying_price = models.DecimalField(max_digits=12, decimal_places=2)
    expiry_date = models.DateField(null=True, blank=True, db_index=True)
    received_on = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = [F("expiry_date").asc(nulls_last=True), "id"]
        verbose_name_plural = "Stock batches"

    def __str__(self):
        exp = self.expiry_date.isoformat() if self.expiry_date else "no expiry"
        return f"{self.product} ({self.quantity_remaining} left, {exp})"

    @property
    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < timezone.localdate())

    @property
    def days_to_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - timezone.localdate()).days

    @property
    def is_expiring_soon(self):
        from shop.models import ShopSettings
        days = self.days_to_expiry
        if days is None or days < 0:
            return False
        return days <= ShopSettings.get().expiry_warning_days

    @property
    def value(self):
        return (self.quantity_remaining * self.buying_price).quantize(Decimal("0.01"))


class StockMovement(models.Model):
    """Every single change to stock, so the owner can always answer
    'where did those 12 crates go?'.
    """

    class Kind(models.TextChoices):
        PURCHASE = "PURCHASE", "Purchase received"
        SALE = "SALE", "Sold"
        RETURN = "RETURN", "Returned by customer"
        ADJUST = "ADJUST", "Manual adjustment"
        WRITE_OFF = "WRITE_OFF", "Written off (expired / damaged)"
        OPENING = "OPENING", "Opening stock"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="movements")
    batch = models.ForeignKey(
        StockBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name="movements")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    quantity = models.DecimalField(
        max_digits=12, decimal_places=3, help_text="Positive = in, negative = out.")
    reference = models.CharField(max_length=60, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="movements")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity} {self.product}"


def expiring_batches(days=None):
    """Batches that will expire within `days` (shop default if not given)."""
    from shop.models import ShopSettings
    if days is None:
        days = ShopSettings.get().expiry_warning_days
    today = timezone.localdate()
    return (StockBatch.objects.filter(quantity_remaining__gt=0,
                                      expiry_date__gte=today,
                                      expiry_date__lte=today + timedelta(days=days))
            .select_related("product", "product__unit"))


def expired_batches():
    return (StockBatch.objects.filter(quantity_remaining__gt=0,
                                      expiry_date__lt=timezone.localdate())
            .select_related("product", "product__unit"))
