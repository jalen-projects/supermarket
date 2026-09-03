from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date

from sales.models import InsufficientStock
from sales.services import (adjust_stock, apply_stock_count, receive_purchase,
                            write_off_batch)
from shop.permissions import admin_required

from .forms import (CategoryForm, ProductForm, PurchaseForm, PurchaseItemFormSet,
                    StockAdjustmentForm, SupplierForm, UnitForm)
from .models import (Category, Product, Purchase, StockBatch, StockCount, StockMovement,
                     Supplier, Unit, expired_batches, expiring_batches)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
@admin_required
def product_list(request):
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    view = request.GET.get("view", "")

    products = Product.objects.select_related("category", "unit").with_stock()
    if q:
        products = products.filter(Q(name__icontains=q) | Q(barcode__icontains=q))
    if category:
        products = products.filter(category_id=category)
    if view == "inactive":
        products = products.filter(is_active=False)
    else:
        products = products.filter(is_active=True)

    rows = list(products)
    if view == "low":
        rows = [p for p in rows if p.stock <= p.effective_reorder_level]
    elif view == "out":
        rows = [p for p in rows if p.stock <= 0]

    paginator = Paginator(rows, 40)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "inventory/product_list.html", {
        "page": page, "q": q, "view": view,
        "categories": Category.objects.all(),
        "selected_category": category,
        "total_products": len(rows),
    })


@admin_required
def product_create(request):
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        product = form.save()

        # If he told us what is already on the shelf, put it there now. This is
        # the difference between "the product exists" and "the product can be
        # sold", and making him find a second screen for it is what generated
        # the question in the first place.
        opening = form.cleaned_data.get("opening_quantity")
        if opening and opening > 0:
            adjust_stock(
                product=product, quantity=opening,
                kind=StockMovement.Kind.OPENING,
                reason="Opening stock, entered when the product was added",
                user=request.user, buying_price=product.buying_price,
                expiry_date=form.cleaned_data.get("opening_expiry"))
            messages.success(
                request,
                f"{product.name} added with {opening:g} {product.unit} in stock. "
                "It can be sold at the till right now.")
        else:
            messages.success(
                request,
                f"{product.name} added. It has no stock yet - receive a delivery, or do a "
                "stock take, before it can be sold.")

        if "save_and_add" in request.POST:
            return redirect("product_create")
        return redirect("product_detail", pk=product.pk)
    return render(request, "inventory/product_form.html",
                  {"form": form, "title": "Add a product"})


@admin_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, instance=product)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{product.name} updated.")
        return redirect("product_detail", pk=product.pk)
    return render(request, "inventory/product_form.html",
                  {"form": form, "title": f"Edit {product.name}", "object": product})


@admin_required
def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects.select_related("category", "unit"), pk=pk)
    return render(request, "inventory/product_detail.html", {
        "product": product,
        "batches": product.batches.filter(quantity_remaining__gt=0),
        "movements": product.movements.select_related("user")[:40],
    })


@admin_required
def product_delete(request, pk):
    """Remove a product - the client's third question, and there was no way to
    do it at all before.

    There are honestly two different things a shopkeeper means by "delete":

    * A mistake. He typed the same soap in twice, or misspelled it, and it has
      never been bought or sold. That one really is deleted, and should be:
      leaving it behind clutters the till search forever.

    * A line the shop has stopped selling. That one must NOT be deleted. Its
      name sits on receipts customers are holding and inside last month's
      profit figures. Deleting it would either fail on a database rule or
      rewrite history. It is retired instead: it disappears from the till and
      from the product list, and every past receipt still adds up.

    The screen tells him which one he is about to get, before he presses
    anything - he should never have to guess.
    """
    product = get_object_or_404(
        Product.objects.select_related("category", "unit"), pk=pk)

    sold = product.sale_items.count()
    delivered = product.purchase_items.count()
    movements = product.movements.count()
    stock = product.stock_available
    # A stock take that found no difference leaves a count line but no movement,
    # and that line is PROTECTed. Miss it and the delete blows up with a
    # database error instead of quietly retiring the product.
    counted = product.count_lines.count()
    can_erase = not (sold or delivered or movements or counted)

    if request.method == "POST":
        name = product.name
        if can_erase:
            product.delete()
            messages.success(request, f"{name} was deleted. It had no history to keep.")
            return redirect("product_list")

        product.is_active = False
        product.save(update_fields=["is_active"])
        messages.success(
            request,
            f"{name} is no longer for sale. It is off the till and out of the product "
            "list, and every past receipt still shows it. You can bring it back any time "
            "from the 'Not for sale' tab.")
        return redirect("product_list")

    return render(request, "inventory/product_delete.html", {
        "product": product, "can_erase": can_erase, "sold": sold,
        "delivered": delivered, "movements": movements, "counted": counted,
        "stock": stock,
    })


@admin_required
def product_restore(request, pk):
    """Put a retired product back on sale. Without this, 'Not for sale' would
    be a one-way door and the only way back would be the database.
    """
    product = get_object_or_404(Product, pk=pk)
    if request.method == "POST":
        product.is_active = True
        product.save(update_fields=["is_active"])
        messages.success(request, f"{product.name} is on sale again.")
    return redirect("product_detail", pk=pk)


@admin_required
def product_adjust(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = StockAdjustmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            adjust_stock(product=product, quantity=form.cleaned_data["quantity"],
                         kind=form.cleaned_data["kind"], reason=form.cleaned_data["reason"],
                         user=request.user)
            messages.success(request, f"Stock for {product.name} adjusted.")
            return redirect("product_detail", pk=product.pk)
        except (InsufficientStock, ValueError) as exc:
            messages.error(request, str(exc))
    return render(request, "inventory/stock_adjust.html", {"form": form, "product": product})


@login_required
def product_lookup(request):
    """Used by the till: scan a barcode or type part of a name.

    A barcode scanner behaves exactly like a keyboard, so the same box serves
    both a shop with a scanner and a shop without one.
    """
    q = request.GET.get("q", "").strip()
    if not q:
        return JsonResponse({"results": []})

    exact = Product.objects.active().filter(barcode=q).select_related("unit").first()
    if exact:
        qs = [exact]
    else:
        qs = list(Product.objects.active()
                  .filter(Q(name__icontains=q) | Q(barcode__icontains=q))
                  .select_related("unit")[:15])

    results = [{
        "id": p.id,
        "name": p.name,
        "barcode": p.barcode or "",
        "price": str(p.selling_price),
        "unit": str(p.unit),
        "allow_decimals": p.unit.allow_decimals,
        "stock": str(p.sellable_quantity),
        "expiry": p.nearest_expiry.isoformat() if p.nearest_expiry else "",
    } for p in qs]
    return JsonResponse({"results": results, "exact": bool(exact)})


# ---------------------------------------------------------------------------
# Categories, units, suppliers
# ---------------------------------------------------------------------------
@admin_required
def category_list(request):
    form = CategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Category added.")
        return redirect("category_list")
    return render(request, "inventory/category_list.html", {
        "form": form,
        "categories": Category.objects.annotate(n=Count("products")),
    })


@admin_required
def category_edit(request, pk):
    obj = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Category updated.")
        return redirect("category_list")
    return render(request, "inventory/simple_form.html",
                  {"form": form, "title": f"Edit {obj.name}", "back": "category_list"})


@admin_required
def unit_list(request):
    form = UnitForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Measurement added.")
        return redirect("unit_list")
    return render(request, "inventory/unit_list.html",
                  {"form": form, "units": Unit.objects.all()})


@admin_required
def supplier_list(request):
    return render(request, "inventory/supplier_list.html",
                  {"suppliers": Supplier.objects.all()})


@admin_required
def supplier_create(request):
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Supplier saved.")
        return redirect("supplier_list")
    return render(request, "inventory/simple_form.html",
                  {"form": form, "title": "Add a supplier", "back": "supplier_list"})


@admin_required
def supplier_edit(request, pk):
    obj = get_object_or_404(Supplier, pk=pk)
    form = SupplierForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Supplier updated.")
        return redirect("supplier_list")
    return render(request, "inventory/simple_form.html",
                  {"form": form, "title": f"Edit {obj.name}", "back": "supplier_list"})


# ---------------------------------------------------------------------------
# Purchases - the 'Purchase' line on the client's paper
# ---------------------------------------------------------------------------
@admin_required
def purchase_list(request):
    purchases = Purchase.objects.select_related("supplier", "received_by")
    paginator = Paginator(purchases, 30)
    return render(request, "inventory/purchase_list.html",
                  {"page": paginator.get_page(request.GET.get("page"))})


@admin_required
def purchase_create(request):
    purchase = Purchase(received_by=request.user)
    form = PurchaseForm(request.POST or None, instance=purchase)
    formset = PurchaseItemFormSet(request.POST or None, instance=purchase)

    if request.method == "POST":
        if form.is_valid() and formset.is_valid():
            obj = form.save()
            formset.instance = obj
            items = formset.save()
            if not items:
                obj.delete()
                messages.error(request, "Add at least one product to the delivery.")
                return redirect("purchase_create")
            if request.POST.get("action") == "receive":
                receive_purchase(obj, request.user)
                messages.success(
                    request, f"{obj.reference} received. Stock is now on the shelf.")
            else:
                messages.success(request, f"{obj.reference} saved as a draft.")
            return redirect("purchase_detail", pk=obj.pk)
        messages.error(request, "Please correct the highlighted lines.")

    return render(request, "inventory/purchase_form.html",
                  {"form": form, "formset": formset, "title": "Receive a delivery"})


@admin_required
def purchase_detail(request, pk):
    purchase = get_object_or_404(
        Purchase.objects.select_related("supplier", "received_by"), pk=pk)
    return render(request, "inventory/purchase_detail.html", {
        "purchase": purchase,
        "items": purchase.items.select_related("product", "product__unit"),
    })


@admin_required
def purchase_receive(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    if request.method == "POST":
        if purchase.status == Purchase.Status.RECEIVED:
            messages.info(request, "That delivery was already received.")
        elif not purchase.items.exists():
            messages.error(request, "The delivery has no items.")
        else:
            receive_purchase(purchase, request.user)
            messages.success(request, f"{purchase.reference} received into stock.")
    return redirect("purchase_detail", pk=pk)


@admin_required
def purchase_delete(request, pk):
    """Throw away a delivery that was typed in wrongly.

    Only while it is still a draft. Once it has been received the goods are on
    the shelf and may already have been sold, so deleting the paperwork would
    leave stock that came from nowhere. Correct a received delivery with a
    stock take instead.
    """
    purchase = get_object_or_404(Purchase, pk=pk)
    if purchase.status == Purchase.Status.RECEIVED:
        messages.error(
            request,
            f"{purchase.reference} has already been received, so it cannot be deleted - "
            "the goods are on the shelf. Do a stock take to correct the quantities.")
        return redirect("purchase_detail", pk=pk)

    if request.method == "POST":
        reference = purchase.reference
        purchase.delete()
        messages.success(request, f"Draft delivery {reference} was deleted.")
        return redirect("purchase_list")

    return render(request, "inventory/purchase_delete.html", {"purchase": purchase})


# ---------------------------------------------------------------------------
# Stock views - 'Stock available', 'Expired item', 'Low stock'
# ---------------------------------------------------------------------------
@admin_required
def stock_list(request):
    q = request.GET.get("q", "").strip()
    products = (Product.objects.active().select_related("category", "unit").with_stock())
    if q:
        products = products.filter(Q(name__icontains=q) | Q(barcode__icontains=q))

    rows = []
    total_cost = total_retail = Decimal("0")
    for p in products:
        cost = p.stock * p.buying_price
        retail = p.stock * p.selling_price
        total_cost += cost
        total_retail += retail
        rows.append({"product": p, "stock": p.stock, "cost": cost, "retail": retail,
                     "low": p.stock <= p.effective_reorder_level,
                     "expiry": p.nearest_expiry})

    return render(request, "inventory/stock_list.html", {
        "rows": rows, "q": q, "total_cost": total_cost, "total_retail": total_retail,
        "potential_profit": total_retail - total_cost,
    })


@admin_required
def expiry_list(request):
    return render(request, "inventory/expiry_list.html", {
        "expired": expired_batches(),
        "expiring": expiring_batches(),
    })


@admin_required
def batch_write_off(request, pk):
    batch = get_object_or_404(StockBatch, pk=pk)
    if request.method == "POST":
        reason = request.POST.get("reason") or "Expired"
        write_off_batch(batch, request.user, reason)
        messages.success(
            request, f"{batch.product.name} written off the books ({reason}).")
    return redirect(request.POST.get("next") or "expiry_list")


# ---------------------------------------------------------------------------
# Stock taking - "how do we record the things already in the supermarket"
# ---------------------------------------------------------------------------
def _decimal_or_none(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"'{raw}' is not a number.")


@admin_required
def stock_take(request):
    """The counting sheet. He walks the shelf, types what he finds, and the
    system works out the difference on its own.

    Counting is done a shelf at a time in a real shop, so this page filters by
    category or by name and each submission is its own count. Leaving a row
    blank means "I did not count this one" - it is not the same as counting
    zero, and treating it as zero would wipe out stock he never looked at.
    """
    category_id = request.GET.get("category", "")
    q = request.GET.get("q", "").strip()

    if request.method == "POST":
        rows, errors = [], []
        for pid in request.POST.getlist("product_id"):
            counted_raw = request.POST.get(f"counted_{pid}", "")
            if not counted_raw.strip():
                continue                      # not counted - leave it alone
            product = Product.objects.filter(pk=pid).first()
            if not product:
                continue
            expiry_raw = (request.POST.get(f"expiry_{pid}") or "").strip()
            try:
                rows.append({
                    "product": product,
                    "counted": _decimal_or_none(counted_raw),
                    "buying_price": _decimal_or_none(request.POST.get(f"cost_{pid}", "")),
                    "expiry_date": parse_date(expiry_raw) if expiry_raw else None,
                })
            except ValueError as exc:
                errors.append(f"{product.name}: {exc}")

        if errors:
            for e in errors[:5]:
                messages.error(request, e)
        elif not rows:
            messages.error(
                request, "No quantities were typed in, so nothing was counted. "
                         "Fill in the 'Counted' box for at least one product.")
        else:
            try:
                count = apply_stock_count(
                    rows=rows, user=request.user,
                    scope=request.POST.get("scope", ""),
                    note=request.POST.get("note", ""))
            except (InsufficientStock, ValueError) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"{count.reference} recorded. {count.line_count} product"
                    f"{'' if count.line_count == 1 else 's'} counted, "
                    f"{count.difference_count} did not match. Stock has been corrected.")
                return redirect("stock_count_detail", pk=count.pk)

    products = (Product.objects.active().select_related("category", "unit").with_stock())
    if category_id:
        products = products.filter(category_id=category_id)
    if q:
        products = products.filter(Q(name__icontains=q) | Q(barcode__icontains=q))

    paginator = Paginator(list(products), 100)
    page = paginator.get_page(request.GET.get("page"))

    scope = ""
    if category_id:
        cat = Category.objects.filter(pk=category_id).first()
        scope = cat.name if cat else ""

    return render(request, "inventory/stock_take.html", {
        "page": page, "categories": Category.objects.all(),
        "selected_category": category_id, "q": q, "scope": scope,
        "recent_counts": StockCount.objects.select_related("counted_by")[:5],
    })


@admin_required
def stock_count_list(request):
    # annotate() adds a GROUP BY, which drops the model's Meta ordering and
    # makes the pages overlap. Name the order explicitly.
    # The list shows each count's variance and what it is worth, and both are
    # worked out from its lines - prefetch them or this is 60 extra queries a
    # page on the shop's PC.
    counts = (StockCount.objects.select_related("counted_by")
              .prefetch_related("lines")
              .annotate(n=Count("lines")).order_by("-created_at", "-id"))
    paginator = Paginator(counts, 30)
    return render(request, "inventory/stock_count_list.html",
                  {"page": paginator.get_page(request.GET.get("page"))})


@admin_required
def stock_count_detail(request, pk):
    """The variance sheet: what the books said, what was on the shelf, and what
    the gap is worth. This is the page that catches shrinkage.
    """
    count = get_object_or_404(StockCount.objects.select_related("counted_by"), pk=pk)
    lines = count.lines.select_related("product", "product__unit")
    return render(request, "inventory/stock_count_detail.html", {
        "count": count, "lines": lines,
        "differences": [line for line in lines if line.difference != 0],
    })


@admin_required
def movement_list(request):
    movements = StockMovement.objects.select_related("product", "user", "product__unit")
    kind = request.GET.get("kind", "")
    if kind:
        movements = movements.filter(kind=kind)
    paginator = Paginator(movements, 60)
    return render(request, "inventory/movement_list.html", {
        "page": paginator.get_page(request.GET.get("page")),
        "kinds": StockMovement.Kind.choices, "kind": kind,
    })
