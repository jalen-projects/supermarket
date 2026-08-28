from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from sales.models import InsufficientStock
from sales.services import adjust_stock, receive_purchase, write_off_batch
from shop.permissions import admin_required

from .forms import (CategoryForm, ProductForm, PurchaseForm, PurchaseItemFormSet,
                    StockAdjustmentForm, SupplierForm, UnitForm)
from .models import (Category, Product, Purchase, StockBatch, StockMovement, Supplier,
                     Unit, expired_batches, expiring_batches)


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
        messages.success(request, f"{product.name} added. Now receive a delivery to give it stock.")
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
