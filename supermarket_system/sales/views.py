import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from inventory.models import Category, Product
from shop.models import ShopSettings
from shop.permissions import admin_required

from .forms import CashUpForm, CustomerForm, OpenDrawerForm
from .models import Customer, InsufficientStock, Sale, Shift
from .services import close_shift, current_shift, open_shift, record_sale


@login_required
def pos(request):
    """The till. Scan-first: the cursor sits in the barcode box, and a scanner
    (which types like a keyboard and ends with Enter) adds the item straight
    away. With no scanner, typing part of the name works the same way.
    """
    shop = ShopSettings.get()
    # The 18 items this shop actually sells most often in the last month, so the
    # cashier rarely has to type at all. Counting per product (rather than
    # ordering across the join) keeps each product on the grid exactly once.
    recent = timezone.now() - timedelta(days=30)
    quick = (Product.objects.active().select_related("unit")
             .annotate(times_sold=Count(
                 "sale_items",
                 filter=Q(sale_items__sale__created_at__gte=recent,
                          sale_items__sale__status=Sale.Status.COMPLETED)))
             .order_by("-times_sold", "name")[:18])
    return render(request, "sales/pos.html", {
        "customers": Customer.objects.filter(is_active=True),
        "categories": Category.objects.all(),
        "quick_products": quick,
        "vat_percent": shop.vat_percent,
        "payment_methods": Sale.Payment.choices,
        # Ugandan shilling notes. One tap beats typing five digits with a
        # queue behind you, and it is where most change errors come from.
        "tender_notes": [1000, 2000, 5000, 10000, 20000, 50000],
    })


@login_required
def pos_checkout(request):
    """Receives the cart as JSON and writes the sale in one transaction."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Bad request."}, status=405)

    try:
        payload = json.loads(request.body.decode())
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Could not read the cart."}, status=400)

    raw_lines = payload.get("lines") or []
    if not raw_lines:
        return JsonResponse({"ok": False, "error": "The cart is empty."}, status=400)

    def money(value, default="0"):
        try:
            return Decimal(str(value or default))
        except InvalidOperation:
            return Decimal(default)

    lines = []
    for raw in raw_lines:
        product = Product.objects.filter(pk=raw.get("product_id"), is_active=True).first()
        if not product:
            return JsonResponse(
                {"ok": False, "error": "One of the items is no longer on sale."}, status=400)
        quantity = money(raw.get("quantity"))
        if quantity <= 0:
            return JsonResponse(
                {"ok": False, "error": f"Quantity for {product.name} must be more than zero."},
                status=400)
        lines.append({"product": product, "quantity": quantity,
                      "unit_price": money(raw.get("unit_price"), str(product.selling_price))})

    customer = None
    if payload.get("customer_id"):
        customer = Customer.objects.filter(pk=payload["customer_id"]).first()

    payment_method = payload.get("payment_method") or Sale.Payment.CASH
    if payment_method not in dict(Sale.Payment.choices):
        payment_method = Sale.Payment.CASH

    try:
        sale = record_sale(
            user=request.user, lines=lines, customer=customer,
            discount=money(payload.get("discount")), tax=money(payload.get("tax")),
            payment_method=payment_method, amount_paid=money(payload.get("amount_paid")),
            note=(payload.get("note") or "")[:200])
    except InsufficientStock as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return JsonResponse({
        "ok": True, "sale_id": sale.id, "receipt_no": sale.receipt_no,
        "total": str(sale.total), "change": str(sale.change),
        "receipt_url": f"/sales/{sale.id}/receipt/",
    })


@login_required
def sale_list(request):
    """A cashier sees only their own sales; the owner sees everything."""
    sales = Sale.objects.select_related("served_by", "customer")
    if not request.user.is_admin:
        sales = sales.filter(served_by=request.user)

    q = request.GET.get("q", "").strip()
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")

    if q:
        sales = sales.filter(Q(receipt_no__icontains=q) | Q(customer__name__icontains=q))
    if date_from:
        sales = sales.filter(created_at__date__gte=date_from)
    if date_to:
        sales = sales.filter(created_at__date__lte=date_to)

    totals = sales.filter(status=Sale.Status.COMPLETED).aggregate(t=Sum("total"))
    paginator = Paginator(sales, 40)

    return render(request, "sales/sale_list.html", {
        "page": paginator.get_page(request.GET.get("page")),
        "q": q, "date_from": date_from, "date_to": date_to,
        "grand_total": totals["t"] or Decimal("0"),
        "count": sales.count(),
    })


@login_required
def sale_detail(request, pk):
    sale = get_object_or_404(Sale.objects.select_related("served_by", "customer"), pk=pk)
    if not request.user.is_admin and sale.served_by_id != request.user.id:
        messages.error(request, "You can only open your own receipts.")
        return redirect("sale_list")
    return render(request, "sales/sale_detail.html", {
        "sale": sale, "items": sale.items.select_related("product", "product__unit")})


@login_required
def receipt(request, pk):
    """The printed slip. Carries all four header fields from the client's list:
    date, company name, served by, customer.
    """
    sale = get_object_or_404(Sale.objects.select_related("served_by", "customer"), pk=pk)
    if not request.user.is_admin and sale.served_by_id != request.user.id:
        messages.error(request, "You can only print your own receipts.")
        return redirect("sale_list")
    width = request.GET.get("width") or ShopSettings.get().receipt_width
    return render(request, "sales/receipt.html", {
        "sale": sale, "items": sale.items.all(), "width": width,
        "auto_print": request.GET.get("print") == "1"})


@admin_required
def sale_void(request, pk):
    """Voiding returns every unit to the exact batch it left, so the expiry
    dates stay honest.
    """
    sale = get_object_or_404(Sale, pk=pk)
    if request.method == "POST":
        if sale.status == Sale.Status.VOIDED:
            messages.info(request, "That receipt was already voided.")
        else:
            sale.void(request.user, request.POST.get("reason", "")[:200])
            messages.success(request, f"{sale.receipt_no} voided and stock returned.")
    return redirect("sale_detail", pk=pk)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@login_required
def customer_list(request):
    customers = Customer.objects.annotate(spent=Sum("sales__total"))
    return render(request, "sales/customer_list.html", {"customers": customers})


@login_required
def customer_create(request):
    form = CustomerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        customer = form.save()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "id": customer.id, "name": customer.name})
        messages.success(request, f"{customer.name} saved.")
        return redirect("customer_list")
    return render(request, "inventory/simple_form.html",
                  {"form": form, "title": "Add a customer", "back": "customer_list"})


@login_required
def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Customer updated.")
        return redirect("customer_list")
    return render(request, "inventory/simple_form.html",
                  {"form": form, "title": f"Edit {customer.name}", "back": "customer_list"})


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    sales = customer.sales.select_related("served_by")[:50]
    return render(request, "sales/customer_detail.html", {
        "customer": customer, "sales": sales,
        "total": customer.sales.filter(status=Sale.Status.COMPLETED)
                 .aggregate(t=Sum("total"))["t"] or Decimal("0"),
        "owing": sum((s.balance_due for s in customer.sales.filter(
            status=Sale.Status.COMPLETED, payment_method=Sale.Payment.CREDIT)), Decimal("0")),
    })


@login_required
def day_summary(request):
    """What a cashier hands over at the end of a shift."""
    day = request.GET.get("date") or timezone.localdate().isoformat()
    sales = Sale.objects.filter(created_at__date=day, status=Sale.Status.COMPLETED)
    if not request.user.is_admin:
        sales = sales.filter(served_by=request.user)

    labels = dict(Sale.Payment.choices)
    by_method = [{"label": labels.get(r["payment_method"], r["payment_method"]),
                  "total": r["total"]}
                 for r in sales.values("payment_method")
                 .annotate(total=Sum("total")).order_by("-total")]

    return render(request, "sales/day_summary.html", {
        "day": day, "sales": sales.select_related("served_by", "customer"),
        "total": sales.aggregate(t=Sum("total"))["t"] or Decimal("0"),
        "count": sales.count(), "by_method": by_method,
    })


@login_required
def cash_up(request):
    """The cashier's own drawer: open it with a float, or count it and hand over.

    A cashier sees only their own drawer and only their own figures. The
    expected total is deliberately hidden until after they have submitted
    their count - see CashUpForm.
    """
    shift = current_shift(request.user)

    if request.method == "POST" and "open" in request.POST:
        form = OpenDrawerForm(request.POST)
        if form.is_valid():
            open_shift(user=request.user,
                       opening_float=form.cleaned_data["opening_float"])
            messages.success(request, "Change money recorded. You can start selling.")
            return redirect("cash_up")
        cashup_form = CashUpForm()
    elif request.method == "POST":
        cashup_form = CashUpForm(request.POST)
        form = OpenDrawerForm(initial={"opening_float": shift.opening_float})
        if cashup_form.is_valid():
            try:
                closed = close_shift(
                    shift=shift,
                    counted_cash=cashup_form.cleaned_data["counted_cash"],
                    closed_by=request.user,
                    note=cashup_form.cleaned_data["note"])
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect("cash_up")
            messages.success(request, "Drawer handed over. Show this page to the manager.")
            return redirect("shift_detail", pk=closed.pk)
    else:
        form = OpenDrawerForm(initial={"opening_float": shift.opening_float})
        cashup_form = CashUpForm()

    return render(request, "sales/cash_up.html", {
        "shift": shift, "form": form, "cashup_form": cashup_form,
        # A cashier must not see what the drawer *should* hold before counting.
        "show_expected": request.user.is_admin,
    })


@admin_required
def shift_list(request):
    """Every drawer, with what was short or over. The owner's theft report."""
    shifts = Shift.objects.select_related("user", "closed_by")

    who = request.GET.get("user") or ""
    if who:
        shifts = shifts.filter(user_id=who)
    state = request.GET.get("state") or ""
    if state in (Shift.Status.OPEN, Shift.Status.CLOSED):
        shifts = shifts.filter(status=state)

    page = Paginator(shifts, 40).get_page(request.GET.get("page"))
    closed = [s for s in page if s.variance is not None]
    return render(request, "sales/shift_list.html", {
        "page_obj": page, "shifts": page,
        "cashiers": get_user_model().objects.all(),
        "user_filter": who, "state": state,
        "short_total": sum((s.variance for s in closed if s.variance < 0), Decimal("0")),
        "over_total": sum((s.variance for s in closed if s.variance > 0), Decimal("0")),
    })


@login_required
def shift_detail(request, pk):
    """One drawer in full - the sheet a cashier hands over with the money."""
    shift = get_object_or_404(Shift.objects.select_related("user", "closed_by"), pk=pk)
    if not request.user.is_admin and shift.user_id != request.user.id:
        raise PermissionDenied("You can only open your own cash-up.")
    return render(request, "sales/shift_detail.html", {
        "shift": shift,
        "sales": shift.sale_set.select_related("customer").order_by("created_at"),
        "show_expected": True,
    })
