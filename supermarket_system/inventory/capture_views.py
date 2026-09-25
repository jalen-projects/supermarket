"""Stock capture - building the product list by walking the shelves.

The client has no stock list in any form. That means the first day is not an
import at all, it is data capture: somebody stands at the counter with the
scanner, picks up each item, and types what it costs and what it sells for.

The ordinary "Add a product" screen is wrong for that job. It is a full page
load per item, the cursor lands in the wrong box, and after saving it goes
somewhere else - which at two hundred items is an afternoon of wasted
keystrokes. This screen does one thing: scan, type, Enter, and the cursor is
back on the barcode box ready for the next item off the shelf.

Scanning something already captured tops up its quantity instead of failing,
because in a real shop the same item is found again on another shelf.
"""
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.dateparse import parse_date

from sales.services import adjust_stock
from shop.permissions import admin_required

from .models import Category, Product, StockMovement, Unit


def _decimal(raw, field):
    raw = (raw or "").strip().replace(",", "").replace(" ", "")
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"{field} is not a number.")
    if value < 0:
        raise ValueError(f"{field} cannot be negative.")
    return value


@admin_required
def capture(request):
    """The capture screen itself."""
    return render(request, "inventory/capture.html", {
        "categories": Category.objects.all(),
        "units": Unit.objects.all(),
        # What has been captured so far today, so the person can see progress
        # and spot a mistake they just made.
        "recent": (Product.objects.select_related("category", "unit")
                   .order_by("-created_at")[:15]),
        "total_products": Product.objects.count(),
    })


@admin_required
def capture_lookup(request):
    """Has this barcode already been captured? Called as the scanner fires."""
    barcode = (request.GET.get("barcode") or "").strip()
    if not barcode:
        return JsonResponse({"found": False})
    product = (Product.objects.select_related("category", "unit")
               .filter(barcode=barcode).first())
    if product is None:
        return JsonResponse({"found": False})
    return JsonResponse({
        "found": True, "id": product.pk, "name": product.name,
        "category": product.category_id, "unit": product.unit_id,
        "buying_price": str(product.buying_price),
        "selling_price": str(product.selling_price),
        "stock": str(product.stock_available),
    })


@admin_required
@transaction.atomic
def capture_save(request):
    """Save one captured item and hand back what to show on screen."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Use the form."}, status=405)

    name = (request.POST.get("name") or "").strip()
    barcode = (request.POST.get("barcode") or "").strip() or None

    try:
        buying = _decimal(request.POST.get("buying_price"), "Buying price")
        selling = _decimal(request.POST.get("selling_price"), "Selling price")
        quantity = _decimal(request.POST.get("quantity"), "Quantity")
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    expiry = parse_date((request.POST.get("expiry") or "").strip() or "1900-01-01")
    if expiry and expiry.year == 1900:
        expiry = None

    existing = Product.objects.filter(barcode=barcode).first() if barcode else None
    if existing is None and name:
        existing = Product.objects.filter(name__iexact=name).first()

    if existing is None:
        if not name:
            return JsonResponse(
                {"ok": False, "error": "Type the product name."}, status=400)
        if selling is None:
            return JsonResponse(
                {"ok": False, "error": "Type the selling price."}, status=400)

        category = Category.objects.filter(pk=request.POST.get("category")).first()
        if category is None:
            category, _ = Category.objects.get_or_create(name="General")
        unit = Unit.objects.filter(pk=request.POST.get("unit")).first()
        if unit is None:
            unit = Unit.objects.first() or Unit.objects.create(
                name="Piece", abbreviation="pc")

        product = Product.objects.create(
            name=name, barcode=barcode, category=category, unit=unit,
            buying_price=buying or Decimal("0"), selling_price=selling)
        action = "created"
    else:
        product = existing
        fields = []
        if buying is not None:
            product.buying_price = buying
            fields.append("buying_price")
        if selling is not None:
            product.selling_price = selling
            fields.append("selling_price")
        if barcode and not product.barcode:
            product.barcode = barcode
            fields.append("barcode")
        if fields:
            product.save(update_fields=fields)
        action = "topped up"

    if quantity and quantity > 0:
        adjust_stock(
            product=product, quantity=quantity,
            kind=StockMovement.Kind.OPENING,
            reason="Opening stock captured from the shelf", user=request.user,
            buying_price=buying, expiry_date=expiry, reference="CAPTURE")

    return JsonResponse({
        "ok": True, "action": action, "id": product.pk, "name": product.name,
        "barcode": product.barcode or "", "quantity": str(quantity or 0),
        "stock": str(product.stock_available),
        "selling_price": str(product.selling_price),
        "total_products": Product.objects.count(),
    })
