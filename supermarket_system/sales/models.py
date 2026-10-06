import secrets
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

    # Which cashier's drawer this sale's money belongs in. Attached at the
    # moment of sale rather than worked out afterwards from the clock: two
    # cashiers swapping over mid-minute, or a till left signed in overnight,
    # both make a time-window guess wrong, and a cash-up that is wrong is
    # worse than no cash-up because someone gets accused over it.
    shift = models.ForeignKey(
        "Shift", on_delete=models.PROTECT, null=True, blank=True)

    note = models.CharField(max_length=200, blank=True)

    # What the QR code on the printed receipt points at, online: anybody
    # holding the slip can open /r/<token>/ and see that the receipt is real
    # and whether it has since been voided. Random rather than the receipt
    # number, so nobody can walk the shop's sales by counting upwards.
    verify_token = models.CharField(
        max_length=24, unique=True, null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.receipt_no

    def save(self, *args, **kwargs):
        if not self.receipt_no:
            self.receipt_no = self._next_receipt_no()
        if not self.verify_token:
            self.verify_token = new_verify_token()
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


def new_verify_token():
    """16 characters, 96 random bits: short enough to keep the QR code small
    on the roll, far too many to guess."""
    return secrets.token_urlsafe(12)


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
        msg = (f"Only {available} {product.unit} of {product.name} available "
               f"(you asked for {requested}).")
        expired = getattr(product, "expired_quantity", 0)
        if expired:
            msg += (f" Another {expired:g} is in stock but past its expiry date - if that date "
                    "was entered wrongly, the manager can correct it on the Expiry page.")
        super().__init__(msg)


class Shift(models.Model):
    """One cashier's spell at a till: from the moment they start selling until
    they count the money in the drawer and hand it over.

    This is the control that protects the owner's cash. Without it the system
    can say "UGX 840,000 was sold today" but nobody can say whether UGX 840,000
    was actually handed over, because there is nothing to compare the takings
    against. A shift records what the drawer started with, what the system
    believes was taken, and what the cashier physically counted - and the
    difference between the last two is the number the owner reads.

    A shift opens by itself on the cashier's first sale. Asking a busy cashier
    to remember to "open a shift" before serving means that on the day it is
    forgotten the sales belong to nothing and the control quietly stops
    working. Opening it automatically means it can never not happen.
    """

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed / handed over"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="shifts")
    opened_at = models.DateTimeField(default=timezone.now, db_index=True)
    opening_float = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="The change money already in the drawer when the shift started.")

    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="shifts_closed")
    counted_cash = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="The cash actually counted out of the drawer at handover.")
    note = models.CharField(max_length=200, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)

    class Meta:
        ordering = ["-opened_at", "-id"]
        # A cashier may only have one drawer open at a time. Two open shifts
        # would split their sales between them and neither would reconcile.
        constraints = [
            models.UniqueConstraint(
                fields=["user"], condition=models.Q(status="OPEN"),
                name="one_open_shift_per_user"),
        ]

    def __str__(self):
        return f"{self.user} from {timezone.localtime(self.opened_at):%d %b %H:%M}"

    # -- what the system believes ----------------------------------------
    @property
    def sales(self):
        return self.sale_set.filter(status=Sale.Status.COMPLETED)

    def _taken(self, method):
        total = self.sales.filter(payment_method=method).aggregate(
            t=models.Sum("total"))["t"]
        return total or Decimal("0")

    @property
    def cash_sales(self):
        return self._taken(Sale.Payment.CASH)

    @property
    def mobile_sales(self):
        return self._taken(Sale.Payment.MOBILE)

    @property
    def card_sales(self):
        return self._taken(Sale.Payment.CARD)

    @property
    def credit_sales(self):
        """Sold but not paid for. It is deliberately NOT expected in the
        drawer - chasing a cashier for money a customer took on credit is how
        an honest cashier is wrongly accused."""
        return self._taken(Sale.Payment.CREDIT)

    @property
    def total_sales(self):
        return self.sales.aggregate(t=models.Sum("total"))["t"] or Decimal("0")

    @property
    def sale_count(self):
        return self.sales.count()

    @property
    def voided_count(self):
        """Voided sales are shown to the owner on purpose. Ringing a sale up,
        taking the money and then voiding it is the oldest way to empty a till
        without the books noticing."""
        return self.sale_set.filter(status=Sale.Status.VOIDED).count()

    @property
    def expected_cash(self):
        """What should be in the drawer: the float it started with plus every
        sale that was paid for in cash. Mobile money and card never reach the
        drawer, and credit has not been paid at all."""
        return (self.opening_float + self.cash_sales).quantize(Decimal("0.01"))

    # -- what was actually there ------------------------------------------
    @property
    def is_open(self):
        return self.status == self.Status.OPEN

    @property
    def variance(self):
        """Counted minus expected. Negative is money missing; positive means
        a customer was short-changed or a sale was never rung up."""
        if self.counted_cash is None:
            return None
        return (self.counted_cash - self.expected_cash).quantize(Decimal("0.01"))

    @property
    def is_short(self):
        v = self.variance
        return v is not None and v < 0

    @property
    def is_balanced(self):
        return self.variance == Decimal("0.00")

    @property
    def duration(self):
        end = self.closed_at or timezone.now()
        minutes = int((end - self.opened_at).total_seconds() // 60)
        hours, mins = divmod(minutes, 60)
        return f"{hours}h {mins:02d}m"


class HeldSale(models.Model):
    """A basket parked at the till ("Hold sale").

    The customer has gone back for something - a different size, the item
    they forgot - and the queue cannot wait. The cashier holds the basket,
    serves the next people, and brings it back when the customer returns.

    KEPT ON THE SERVER, NOT IN THE BROWSER. The live basket already survives
    a reload in the browser; a held one has to survive more than that: the
    cashier going on break and the customer returning to the next till, a
    till computer restarted, a second cashier taking over the counter.
    Nothing here touches stock or money - a held basket is a list of what
    was scanned, and the sale is written, with today's prices and stock
    checked again, only when it is brought back and cashed out.

    Bringing it back deletes it in the same moment (see sales.views
    held_recall), so two tills can never both restore the same basket and
    charge for it twice.
    """

    label = models.CharField(max_length=60)
    held_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="held_sales")
    held_at = models.DateTimeField(default=timezone.now, db_index=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # [{"id": product id, "qty": "1.5", "price": "3500", "list_price": "3500"}]
    # - quantities and prices as strings, so a half kilo stays exactly 0.5.
    lines = models.JSONField(default=list)
    item_count = models.PositiveIntegerField(default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["held_at", "id"]

    def __str__(self):
        return f"{self.label} ({self.item_count} items)"
