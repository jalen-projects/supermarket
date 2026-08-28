import csv
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, F, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from inventory.models import Product, StockBatch, expired_batches, expiring_batches
from sales.models import Sale, SaleItem
from shop.permissions import admin_required


def _range(request, default_days=7):
    """Every report shares one date filter."""
    today = timezone.localdate()
    start = request.GET.get("from") or (today - timedelta(days=default_days)).isoformat()
    end = request.GET.get("to") or today.isoformat()
    return start, end


@admin_required
def index(request):
    return render(request, "reports/index.html")


@admin_required
def sales_report(request):
    start, end = _range(request)
    sales = (Sale.objects.filter(status=Sale.Status.COMPLETED,
                                 created_at__date__gte=start, created_at__date__lte=end)
             .select_related("served_by", "customer"))

    by_day = (sales.annotate(day=TruncDate("created_at")).values("day")
              .annotate(total=Sum("total"), n=Count("id")).order_by("day"))
    by_seller = (sales.values("served_by__first_name", "served_by__last_name",
                              "served_by__username")
                 .annotate(total=Sum("total"), n=Count("id")).order_by("-total"))
    by_method = (sales.values("payment_method")
                 .annotate(total=Sum("total"), n=Count("id")).order_by("-total"))

    total = sales.aggregate(t=Sum("total"))["t"] or Decimal("0")
    cost = sum((s.cost_total for s in sales.prefetch_related("items")), Decimal("0"))

    return render(request, "reports/sales.html", {
        "start": start, "end": end, "sales": sales[:200], "count": sales.count(),
        "total": total, "cost": cost, "profit": total - cost,
        "by_day": by_day, "by_seller": by_seller, "by_method": by_method,
        "method_labels": dict(Sale.Payment.choices),
        "peak_day": max(by_day, key=lambda d: d["total"], default=None),
    })


@admin_required
def profit_report(request):
    """Selling price minus buying price - the reason the client asked for both."""
    start, end = _range(request, 30)
    items = (SaleItem.objects.filter(sale__status=Sale.Status.COMPLETED,
                                     sale__created_at__date__gte=start,
                                     sale__created_at__date__lte=end)
             .select_related("product", "product__unit", "product__category"))

    rows = {}
    for item in items:
        row = rows.setdefault(item.product_id, {
            "name": item.product_name,
            "category": item.product.category.name if item.product else "",
            "qty": Decimal("0"), "revenue": Decimal("0"), "cost": Decimal("0")})
        row["qty"] += item.quantity
        row["revenue"] += item.line_total
        row["cost"] += item.cost_total

    table = sorted(rows.values(), key=lambda r: r["revenue"] - r["cost"], reverse=True)
    for row in table:
        row["profit"] = row["revenue"] - row["cost"]
        row["margin"] = (row["profit"] / row["revenue"] * 100) if row["revenue"] else Decimal("0")

    return render(request, "reports/profit.html", {
        "start": start, "end": end, "rows": table,
        "revenue": sum((r["revenue"] for r in table), Decimal("0")),
        "cost": sum((r["cost"] for r in table), Decimal("0")),
        "profit": sum((r["profit"] for r in table), Decimal("0")),
        "best": table[0] if table else None,
        "worst": table[-1] if table else None,
    })


@admin_required
def stock_report(request):
    """'Stock available' + 'Low stock' in one place, valued twice: what the
    shelves cost the owner, and what they will fetch.
    """
    products = (Product.objects.active().select_related("category", "unit").with_stock())
    rows = []
    for p in products:
        rows.append({
            "product": p, "stock": p.stock,
            "cost": p.stock * p.buying_price,
            "retail": p.stock * p.selling_price,
            "low": p.stock <= p.effective_reorder_level,
            "out": p.stock <= 0,
        })
    rows.sort(key=lambda r: (not r["out"], not r["low"], r["product"].name))

    return render(request, "reports/stock.html", {
        "rows": rows,
        "cost_total": sum((r["cost"] for r in rows), Decimal("0")),
        "retail_total": sum((r["retail"] for r in rows), Decimal("0")),
        "low_count": sum(1 for r in rows if r["low"]),
        "out_count": sum(1 for r in rows if r["out"]),
    })


@admin_required
def expiry_report(request):
    expired = list(expired_batches())
    expiring = list(expiring_batches())
    return render(request, "reports/expiry.html", {
        "expired": expired, "expiring": expiring,
        "expired_value": sum((b.value for b in expired), Decimal("0")),
        "expiring_value": sum((b.value for b in expiring), Decimal("0")),
    })


@admin_required
def top_products(request):
    start, end = _range(request, 30)
    rows = (SaleItem.objects
            .filter(sale__status=Sale.Status.COMPLETED,
                    sale__created_at__date__gte=start, sale__created_at__date__lte=end)
            .values("product_name")
            .annotate(qty=Sum("quantity"),
                      revenue=Sum(F("quantity") * F("unit_price")))
            .order_by("-qty")[:50])

    dead = (Product.objects.active()
            .exclude(sale_items__sale__created_at__date__gte=start)
            .select_related("category", "unit").with_stock())
    dead_rows = [{"product": p, "stock": p.stock, "tied_up": p.stock * p.buying_price}
                 for p in dead if p.stock > 0][:50]

    return render(request, "reports/top_products.html", {
        "start": start, "end": end, "rows": rows, "dead": dead_rows,
        "tied_up_total": sum((r["tied_up"] for r in dead_rows), Decimal("0")),
    })


@admin_required
def export_csv(request, kind):
    """Everything the owner sees on screen can leave as a spreadsheet."""
    response = HttpResponse(content_type="text/csv")
    stamp = timezone.localdate().isoformat()
    response["Content-Disposition"] = f'attachment; filename="{kind}_{stamp}.csv"'
    writer = csv.writer(response)

    if kind == "stock":
        writer.writerow(["Product", "Barcode", "Category", "Unit", "Stock available",
                         "Buying price", "Selling price", "Stock value (cost)",
                         "Stock value (retail)", "Reorder level", "Nearest expiry"])
        for p in Product.objects.active().select_related("category", "unit").with_stock():
            writer.writerow([p.name, p.barcode or "", p.category.name, p.unit.abbreviation,
                             p.stock, p.buying_price, p.selling_price,
                             p.stock * p.buying_price, p.stock * p.selling_price,
                             p.effective_reorder_level,
                             p.nearest_expiry.isoformat() if p.nearest_expiry else ""])

    elif kind == "sales":
        start, end = _range(request, 30)
        writer.writerow(["Receipt", "Date", "Served by", "Customer", "Items",
                         "Total", "Payment", "Status"])
        for s in (Sale.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
                  .select_related("served_by", "customer")):
            writer.writerow([s.receipt_no, timezone.localtime(s.created_at).strftime("%Y-%m-%d %H:%M"),
                             s.served_by.display_name, s.customer_name, s.item_count,
                             s.total, s.get_payment_method_display(), s.get_status_display()])

    elif kind == "expiry":
        writer.writerow(["Product", "Batch", "Quantity left", "Expiry date",
                         "Days left", "Value at cost", "State"])
        for b in list(expired_batches()) + list(expiring_batches()):
            writer.writerow([b.product.name, b.id, b.quantity_remaining,
                             b.expiry_date.isoformat() if b.expiry_date else "",
                             b.days_to_expiry, b.value,
                             "EXPIRED" if b.is_expired else "Expiring soon"])
    else:
        writer.writerow(["Unknown report"])

    return response
