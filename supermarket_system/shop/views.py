import shutil
from datetime import timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from inventory.models import Product, StockBatch, expired_batches, expiring_batches
from sales.models import Sale

from .forms import PasswordResetForm, ShopSettingsForm, UserEditForm, UserForm
from .models import ShopSettings, User
from .permissions import admin_required


class LoginView(auth_views.LoginView):
    template_name = "shop/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["first_run"] = not User.objects.exists()
        return ctx


@login_required
def dashboard(request):
    today = timezone.localdate()
    start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))

    todays_sales = Sale.objects.filter(created_at__gte=start, status=Sale.Status.COMPLETED)
    my_sales = todays_sales.filter(served_by=request.user)

    ctx = {
        "today": today,
        "todays_total": todays_sales.aggregate(t=Sum("total"))["t"] or Decimal("0"),
        "todays_count": todays_sales.count(),
        "my_total": my_sales.aggregate(t=Sum("total"))["t"] or Decimal("0"),
        "my_count": my_sales.count(),
        "recent_sales": todays_sales.select_related("served_by", "customer")[:8],
    }

    if request.user.is_admin:
        products = Product.objects.active().with_stock()
        low = [p for p in products if p.stock <= p.effective_reorder_level]
        expired = expired_batches()
        expiring = expiring_batches()
        stock_value = StockBatch.objects.filter(quantity_remaining__gt=0).aggregate(
            v=Sum("quantity_remaining"))["v"] or Decimal("0")

        week_ago = timezone.now() - timedelta(days=7)
        week_sales = Sale.objects.filter(created_at__gte=week_ago, status=Sale.Status.COMPLETED)

        ctx.update({
            "product_count": products.count(),
            "low_stock": low[:8],
            "low_stock_count": len(low),
            "expired_count": expired.count(),
            "expired": expired[:8],
            "expiring_count": expiring.count(),
            "expiring": expiring[:8],
            "stock_units": stock_value,
            "stock_worth": sum((b.value for b in StockBatch.objects.filter(
                quantity_remaining__gt=0).only("quantity_remaining", "buying_price")), Decimal("0")),
            "week_total": week_sales.aggregate(t=Sum("total"))["t"] or Decimal("0"),
            "week_count": week_sales.count(),
            "top_sellers": (week_sales.values("served_by__first_name", "served_by__username")
                            .annotate(total=Sum("total"), n=Count("id")).order_by("-total")[:5]),
        })
    return render(request, "shop/dashboard.html", ctx)


# ---------------------------------------------------------------------------
# Shop settings - the 'Company name' the client asked for
# ---------------------------------------------------------------------------
@admin_required
def shop_settings_view(request):
    obj = ShopSettings.get()
    form = ShopSettingsForm(request.POST or None, request.FILES or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Shop details saved. They now appear on every receipt.")
        return redirect("shop_settings")
    return render(request, "shop/settings.html", {"form": form, "obj": obj})


# ---------------------------------------------------------------------------
# Users - so 'Served by' is a real person
# ---------------------------------------------------------------------------
@admin_required
def user_list(request):
    users = User.objects.annotate(sale_count=Count("sales"))
    return render(request, "shop/user_list.html", {"users": users})


@admin_required
def user_create(request):
    form = UserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, f"{user.display_name} can now sign in.")
        return redirect("user_list")
    return render(request, "shop/user_form.html", {"form": form, "title": "Add a user"})


@admin_required
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    form = UserEditForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "User updated.")
        return redirect("user_list")
    return render(request, "shop/user_form.html",
                  {"form": form, "title": f"Edit {user.display_name}", "object": user})


@admin_required
def user_password(request, pk):
    user = get_object_or_404(User, pk=pk)
    form = PasswordResetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user.set_password(form.cleaned_data["password1"])
        user.save()
        messages.success(request, f"New password set for {user.display_name}.")
        return redirect("user_list")
    return render(request, "shop/user_form.html",
                  {"form": form, "title": f"Reset password - {user.display_name}"})


# ---------------------------------------------------------------------------
# Backup - the one thing an offline shop cannot afford to skip
# ---------------------------------------------------------------------------
@admin_required
def backup(request):
    django_settings.BACKUP_DIR.mkdir(exist_ok=True)
    backups = sorted(django_settings.BACKUP_DIR.glob("*.sqlite3"), reverse=True)
    rows = [{"name": b.name, "size_kb": b.stat().st_size // 1024,
             "when": timezone.datetime.fromtimestamp(b.stat().st_mtime)} for b in backups]

    if request.method == "POST":
        stamp = timezone.localtime().strftime("%Y-%m-%d_%H%M%S")
        target = django_settings.BACKUP_DIR / f"backup_{stamp}.sqlite3"
        shutil.copy2(django_settings.BASE_DIR / "db.sqlite3", target)
        messages.success(request, f"Backup saved as {target.name}. Copy it to a flash disk today.")
        return redirect("backup")

    return render(request, "shop/backup.html", {"backups": rows,
                                                "folder": django_settings.BACKUP_DIR})


@admin_required
def backup_download(request, name):
    path = django_settings.BACKUP_DIR / name
    if not path.exists() or path.parent != django_settings.BACKUP_DIR:
        messages.error(request, "That backup no longer exists.")
        return redirect("backup")
    return FileResponse(open(path, "rb"), as_attachment=True, filename=name)
