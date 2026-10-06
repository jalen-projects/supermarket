import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from inventory.models import Category, Product
from shop.models import ShopSettings
from shop import audit
from shop.models import AuditEvent
from shop.permissions import admin_required

from . import qr
from .forms import CashUpForm, CustomerForm, OpenDrawerForm
from .models import Customer, HeldSale, InsufficientStock, Sale, Shift
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
    shop = ShopSettings.get()
    width = request.GET.get("width") or shop.receipt_width
    return render(request, "sales/receipt.html", {
        "sale": sale, "items": sale.items.all(), "width": width,
        "qr_svg": qr.svg(receipt_qr_text(request, sale, shop)),
        "qr_is_link": bool(getattr(settings, "ONLINE", False)),
        "auto_print": request.GET.get("print") == "1"})


def receipt_qr_text(request, sale, shop):
    """What the QR code on a printed receipt says.

    ONLINE it is a link to the receipt's public check page, so a customer, a
    guard at the door or the owner can scan the slip and see it is genuine -
    and whether it was voided after it was printed, which is how a refunded
    receipt gets used twice. OFFLINE there is nothing on the internet to
    point at, so it carries the receipt's essentials as plain text instead;
    any phone camera shows them.
    """
    if getattr(settings, "ONLINE", False):
        if not sale.verify_token:
            sale.save(update_fields=["verify_token"])   # save() makes one
        path = reverse("receipt_verify", args=[sale.verify_token])
        host = getattr(settings, "PUBLIC_HOSTNAME", "")
        return f"https://{host}{path}" if host else request.build_absolute_uri(path)
    lines = [
        shop.company_name,
        f"Receipt {sale.receipt_no}",
        f"{timezone.localtime(sale.created_at):%d/%m/%Y %H:%M}",
        f"Total {shop.currency} {sale.total:,.0f}",
    ]
    if sale.status == Sale.Status.VOIDED:
        lines.append("VOIDED")
    return "\n".join(lines)


@never_cache
def receipt_verify(request, token):
    """The page the receipt's QR code opens. PUBLIC - no sign-in - and so it
    shows only what is already printed on the slip in the customer's hand:
    the shop, the receipt number, when, the items and the total, and whether
    it has been voided since. No buying prices, no customer, nothing about
    the cashier beyond a first name."""
    if not token or len(token) > 24:
        raise Http404
    sale = (Sale.objects.select_related("served_by")
            .filter(verify_token=token).first())
    if sale is None:
        raise Http404
    response = render(request, "sales/receipt_verify.html", {
        "sale": sale, "items": sale.items.all(),
        "served_by": (sale.served_by.first_name or "").strip() or None,
    })
    # A receipt is nobody's business but the holder's: keep it out of search
    # engines even if somebody posts the link.
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


# ---------------------------------------------------------------------------
# Held baskets - "Hold sale" at the till (see HeldSale)
# ---------------------------------------------------------------------------
#: A basket nobody came back for in two days is not coming back.
HELD_KEEP_HOURS = 48


def _held_row(hold, user):
    held_at = timezone.localtime(hold.held_at)
    return {
        "id": hold.id, "label": hold.label,
        "held_by": hold.held_by.display_name, "mine": hold.held_by_id == user.id,
        "held_at": held_at.strftime("%H:%M"),
        "today": held_at.date() == timezone.localdate(),
        "items": hold.item_count, "total": str(hold.total),
        "customer": hold.customer.name if hold.customer_id else "",
    }


def _next_auto_label():
    """'Held 1', 'Held 2' ... the lowest number not already on hold, so the
    labels stay short however busy the day gets."""
    taken = set()
    for label in HeldSale.objects.values_list("label", flat=True):
        head, _, number = label.partition(" ")
        if head == "Held" and number.isdigit():
            taken.add(int(number))
    n = 1
    while n in taken:
        n += 1
    return f"Held {n}"


@login_required
def held_sales(request):
    """GET: every basket on hold in the shop, oldest first - a customer may
    come back to a different till. POST: hold the basket sent as JSON."""
    HeldSale.objects.filter(
        held_at__lt=timezone.now() - timedelta(hours=HELD_KEEP_HOURS)).delete()

    if request.method == "POST":
        try:
            payload = json.loads(request.body.decode())
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"ok": False, "error": "Could not read the basket."}, status=400)
        lines, total = [], Decimal("0")
        for raw in payload.get("lines") or []:
            product = Product.objects.filter(pk=raw.get("product_id")).first()
            try:
                qty = Decimal(str(raw.get("quantity")))
                price = Decimal(str(raw.get("unit_price")))
            except (InvalidOperation, TypeError):
                continue
            if product is None or not qty.is_finite() or not price.is_finite() \
                    or qty <= 0 or price < 0:
                continue
            lines.append({"id": product.id, "qty": str(qty), "price": str(price),
                          "list_price": str(product.selling_price)})
            total += qty * price
        if not lines:
            return JsonResponse({"ok": False, "error": "There is nothing to hold."}, status=400)
        customer = None
        if payload.get("customer_id"):
            customer = Customer.objects.filter(pk=payload["customer_id"]).first()
        label = " ".join(str(payload.get("label") or "").split())[:60] or _next_auto_label()
        hold = HeldSale.objects.create(
            label=label, held_by=request.user, customer=customer, lines=lines,
            item_count=len(lines), total=total.quantize(Decimal("0.01")))
        return JsonResponse({"ok": True, "held": _held_row(hold, request.user)})

    holds = HeldSale.objects.select_related("held_by", "customer")
    return JsonResponse({"ok": True,
                         "held": [_held_row(h, request.user) for h in holds]})


@login_required
@require_POST
def held_recall(request, pk):
    """Bring a held basket back to the till. It is deleted in the same
    transaction, so a second till pressing the same button a moment later
    is told it has gone rather than getting a copy to charge again. From
    here the basket is the till's live basket, which the browser keeps
    through a reload until it is cashed out or cleared.

    Prices come back as TODAY's price unless the cashier had typed a
    different one when it was held; anything taken off sale since is left
    out and named, so the cashier can tell the customer. Stock is checked,
    as for every sale, when it is cashed out."""
    with transaction.atomic():
        hold = HeldSale.objects.filter(pk=pk).select_related("customer").first()
        if hold is None or not HeldSale.objects.filter(pk=hold.pk).delete()[0]:
            return JsonResponse({"ok": False, "error": (
                "That basket is no longer on hold - it was brought back on "
                "another till, or discarded.")}, status=404)

    products = {p.id: p for p in Product.objects.select_related("unit")
                .filter(pk__in=[line.get("id") for line in hold.lines])}
    lines, notes = [], []
    for line in hold.lines:
        product = products.get(line.get("id"))
        if product is None or not product.is_active:
            notes.append(f"{product.name if product else 'An item'} is no longer on sale "
                         "and was left out.")
            continue
        price = Decimal(line["price"])
        if Decimal(line.get("list_price", line["price"])) == price \
                and price != product.selling_price:
            notes.append(f"{product.name}: the price is now "
                         f"{product.selling_price:,.0f} (it was {price:,.0f} when held).")
            price = product.selling_price
        lines.append({"id": product.id, "name": product.name, "price": float(price),
                      "qty": float(Decimal(line["qty"])), "unit": str(product.unit),
                      "dec": product.unit.allow_decimals,
                      "stock": str(product.sellable_quantity)})
    return JsonResponse({"ok": True, "label": hold.label, "lines": lines,
                         "customer_id": hold.customer_id, "notes": notes})


@login_required
@require_POST
def held_discard(request, pk):
    """The customer is not coming back. Only the cashier who held it, or the
    owner, can throw it away."""
    hold = HeldSale.objects.filter(pk=pk).select_related("held_by").first()
    if hold is None:
        return JsonResponse({"ok": True})
    if hold.held_by_id != request.user.id and not request.user.is_admin:
        return JsonResponse({"ok": False, "error": (
            f"Only {hold.held_by.display_name} or the manager can discard this basket.")},
            status=403)
    hold.delete()
    return JsonResponse({"ok": True})


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
            reason = request.POST.get("reason", "")[:200]
            sale.void(request.user, reason)
            audit.record(
                AuditEvent.Action.SALE_VOIDED,
                f"Voided {sale.receipt_no} ({sale.total:,.0f}), sold by "
                f"{sale.served_by.display_name}",
                request=request, reference=sale.receipt_no,
                changes=f"Reason: {reason or '(none given)'}")
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
            variance = closed.variance
            state = ("balanced" if variance == 0 else
                     f"SHORT {-variance:,.0f}" if variance < 0 else f"over {variance:,.0f}")
            audit.record(
                AuditEvent.Action.DRAWER_HANDED_OVER,
                f"{closed.user.display_name} handed over the drawer - {state}",
                request=request, reference=f"shift-{closed.pk}",
                changes=(f"Expected cash: {closed.expected_cash:,.0f}\n"
                         f"Counted cash: {closed.counted_cash:,.0f}"))
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
