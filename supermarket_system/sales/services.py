"""Business rules that must never be duplicated in a view."""
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from inventory.models import StockBatch, StockMovement

from .models import InsufficientStock, Sale, SaleItem, SaleItemBatch

TWO = Decimal("0.01")


@transaction.atomic
def record_sale(*, user, lines, customer=None, discount=Decimal("0"),
                tax=Decimal("0"), payment_method=Sale.Payment.CASH,
                amount_paid=Decimal("0"), note=""):
    """Create a completed sale and take the goods off the shelf.

    `lines` is a list of dicts: {"product": Product, "quantity": Decimal,
    "unit_price": Decimal}. Stock is drawn first-expiry-first-out so the
    oldest goods leave the shop first and less is ever written off.
    """
    if not lines:
        raise ValueError("A sale must have at least one item.")

    sale = Sale.objects.create(
        served_by=user, customer=customer, discount=discount, tax=tax,
        payment_method=payment_method, amount_paid=amount_paid, note=note)

    for line in lines:
        product = line["product"]
        quantity = Decimal(str(line["quantity"]))
        if quantity <= 0:
            raise ValueError(f"Quantity for {product} must be more than zero.")
        unit_price = Decimal(str(line.get("unit_price", product.selling_price)))

        # Lock the batches so two tills cannot sell the same last packet.
        batches = list(
            StockBatch.objects.select_for_update()
            .filter(pk__in=[b.pk for b in product.sellable_batches()])
            .order_by(F("expiry_date").asc(nulls_last=True), "id"))
        available = sum((b.quantity_remaining for b in batches), Decimal("0"))
        if available < quantity:
            raise InsufficientStock(product, quantity, available)

        item = SaleItem.objects.create(
            sale=sale, product=product, product_name=product.name,
            quantity=quantity, unit_price=unit_price,
            buying_price=product.buying_price)

        outstanding = quantity
        cost = Decimal("0")
        for batch in batches:
            if outstanding <= 0:
                break
            take = min(batch.quantity_remaining, outstanding)
            batch.quantity_remaining -= take
            batch.save(update_fields=["quantity_remaining"])

            SaleItemBatch.objects.create(
                sale_item=item, batch=batch, quantity=take,
                buying_price=batch.buying_price)
            StockMovement.objects.create(
                product=product, batch=batch, kind=StockMovement.Kind.SALE,
                quantity=-take, reference=sale.receipt_no, user=user)

            cost += take * batch.buying_price
            outstanding -= take

        # Cost of THIS sale, from the actual batches, not the current list price.
        item.buying_price = (cost / quantity).quantize(TWO) if quantity else Decimal("0")
        item.save(update_fields=["buying_price"])

    sale.recalculate()
    return sale


@transaction.atomic
def receive_purchase(purchase, user):
    """Mark a delivery as received: create a batch per line and push stock in.

    This is the 'Purchase' item on the client's paper, and it is the only way
    stock enters the shop apart from an opening-stock adjustment.
    """
    if purchase.status == purchase.Status.RECEIVED:
        return purchase

    for line in purchase.items.select_related("product"):
        batch = StockBatch.objects.create(
            product=line.product, purchase_item=line,
            quantity_received=line.quantity, quantity_remaining=line.quantity,
            buying_price=line.buying_price, expiry_date=line.expiry_date,
            received_on=purchase.date)

        StockMovement.objects.create(
            product=line.product, batch=batch, kind=StockMovement.Kind.PURCHASE,
            quantity=line.quantity, reference=purchase.reference,
            reason=f"From {purchase.supplier}", user=user)

        # The latest delivery sets the cost price used for margin display.
        fields = ["buying_price"]
        line.product.buying_price = line.buying_price
        if line.selling_price:
            line.product.selling_price = line.selling_price
            fields.append("selling_price")
        line.product.save(update_fields=fields)

    purchase.status = purchase.Status.RECEIVED
    purchase.save(update_fields=["status"])
    return purchase


@transaction.atomic
def adjust_stock(*, product, quantity, kind, reason, user, batch=None):
    """Manual correction: opening stock, breakage, theft, expiry write-off."""
    quantity = Decimal(str(quantity))
    if quantity == 0:
        raise ValueError("Adjustment quantity cannot be zero.")

    if quantity > 0 and batch is None:
        batch = StockBatch.objects.create(
            product=product, quantity_received=quantity, quantity_remaining=quantity,
            buying_price=product.buying_price, note=reason)
    elif quantity < 0:
        outstanding = -quantity
        candidates = ([batch] if batch else
                      list(StockBatch.objects.select_for_update()
                           .filter(product=product, quantity_remaining__gt=0)
                           .order_by(F("expiry_date").asc(nulls_last=True), "id")))
        available = sum((b.quantity_remaining for b in candidates), Decimal("0"))
        if available < outstanding:
            raise InsufficientStock(product, outstanding, available)
        for b in candidates:
            if outstanding <= 0:
                break
            take = min(b.quantity_remaining, outstanding)
            b.quantity_remaining -= take
            b.save(update_fields=["quantity_remaining"])
            outstanding -= take

    StockMovement.objects.create(
        product=product, batch=batch, kind=kind, quantity=quantity,
        reason=reason, user=user)
    return product


@transaction.atomic
def write_off_batch(batch, user, reason="Expired"):
    """Take an expired or damaged lot off the books, keeping the paper trail."""
    quantity = batch.quantity_remaining
    if quantity <= 0:
        return batch
    batch.quantity_remaining = Decimal("0")
    batch.save(update_fields=["quantity_remaining"])
    StockMovement.objects.create(
        product=batch.product, batch=batch, kind=StockMovement.Kind.WRITE_OFF,
        quantity=-quantity, reason=reason, user=user)
    return batch
