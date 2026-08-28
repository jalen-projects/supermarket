from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from inventory.models import Product, StockBatch, StockMovement


class Customer(models.Model):
    """The client wrote 'Customer (walkin)'. Most sales are to a walk-in and
    need no record at all - so customer stays optional on a sale. Named
    customers exist for regulars and for anyone buying on credit.
    """

    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=60, blank=True)
    address = models.CharField(max_length=200, blank=True)
    notes = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Sale(models.Model):
    """One receipt. Carries the four header fields from the client's list:
    Date, Company name (from shop settings), Served by, Customer.
    """

    class Status(models.TextChoices):
        COMPLETED = "COMPLETED", "Completed"
        VOIDED = "VOIDED", "Voided"

    class Payment(models.TextChoices):
        CASH = "CASH", "Cash"
        MOBILE = "MOBILE", "Mobile money"
        CARD = "CARD", "Card"
        CREDIT = "CREDIT", "Credit (pay later)"

    receipt_no = models.CharField(max_length=30, unique=True, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    served_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales")
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="sales")

    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    payment_method = models.CharField(max_length=10, choices=Payment.choices, default=Payment.CASH)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.COMPLETED)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="voided_sales")
    void_reason = models.CharField(max_length=200, blank=True)

    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.receipt_no

    def save(self, *args, **kwargs):
        if not self.receipt_no:
            self.receipt_no = self._next_receipt_no()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_receipt_no():
        today = timezone.localdate()
        prefix = f"R{today.strftime('%y%m%d')}"
        last = Sale.objects.filter(receipt_no__startswith=prefix).order_by("-receipt_no").first()
        seq = int(last.receipt_no[len(prefix):]) + 1 if last else 1
        return f"{prefix}{seq:04d}"

    # -- money ------------------------------------------------------------
    @property
    def customer_name(self):
        return self.customer.name if self.customer else "Walk-in customer"

    @property
    def subtotal(self):
        return sum((i.line_total for i in self.items.all()), Decimal("0"))

    @property
    def cost_total(self):
        return sum((i.cost_total for i in self.items.all()), Decimal("0"))

    @property
    def profit(self):
        return self.total - self.tax - self.cost_total

    @property
    def change(self):
        return max(self.amount_paid - self.total, Decimal("0"))

    @property
    def balance_due(self):
        return max(self.total - self.amount_paid, Decimal("0"))

    @property
    def item_count(self):
        return self.items.count()

    def recalculate(self, save=True):
        sub = self.subtotal
        taxable = max(sub - self.discount, Decimal("0"))
        self.total = (taxable + self.tax).quantize(Decimal("0.01"))
        if save:
            self.save(update_fields=["total"])
        return self.total

    @transaction.atomic
    def void(self, user, reason=""):
        """Cancel a completed sale and put every unit back on the shelf,
        into the very batch it came out of.
        """
        if self.status == self.Status.VOIDED:
            return
        for item in self.items.select_related("product"):
            for alloc in item.allocations.select_related("batch"):
                batch = alloc.batch
                if batch:
                    batch.quantity_remaining = models.F("quantity_remaining") + alloc.quantity
                    batch.save(update_fields=["quantity_remaining"])
                StockMovement.objects.create(
                    product=item.product, batch=batch, kind=StockMovement.Kind.RETURN,
                    quantity=alloc.quantity, reference=self.receipt_no,
                    reason=reason or "Sale voided", user=user)
        self.status = self.Status.VOIDED
        self.voided_at = timezone.now()
        self.voided_by = user
        self.void_reason = reason
        self.save(update_fields=["status", "voided_at", "voided_by", "void_reason"])


class SaleItem(models.Model):
    """One line on the receipt: product name, quantity, selling price.

    buying_price is copied in at the moment of sale so that profit reports stay
    correct even after the cost price later changes.
    """

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="sale_items")
    product_name = models.CharField(max_length=150)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    buying_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.product_name} x {self.quantity}"

    @property
    def line_total(self):
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))

    @property
    def cost_total(self):
        return (self.quantity * self.buying_price).quantize(Decimal("0.01"))

    @property
    def profit(self):
        return self.line_total - self.cost_total


class SaleItemBatch(models.Model):
    """Which batch each sold unit came out of - so a void returns stock to the
    right lot, and so an expiry recall can name the receipts affected.
    """

    sale_item = models.ForeignKey(SaleItem, on_delete=models.CASCADE, related_name="allocations")
    batch = models.ForeignKey(
        StockBatch, on_delete=models.SET_NULL, null=True, related_name="sale_allocations")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    buying_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.quantity} from batch {self.batch_id}"


class InsufficientStock(Exception):
    def __init__(self, product, requested, available):
        self.product = product
        self.requested = requested
        self.available = available
        super().__init__(
            f"Only {available} {product.unit} of {product.name} available "
            f"(you asked for {requested}).")
