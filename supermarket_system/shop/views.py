import json
import os
import socket
import sqlite3
from datetime import timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.http import FileResponse, JsonResponse
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
# The guided tour
# ---------------------------------------------------------------------------
@login_required
def tour_state(request):
    """Remember whether this person has been through the tour.

    POST {"done": true} when they finish or dismiss it, {"done": false} to
    start it again from the Help page. Kept on the user, not in the browser,
    so the second till does not offer the tour to somebody who already sat
    through it on the first.
    """
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)

    try:
        done = bool(json.loads(request.body.decode() or "{}").get("done", True))
    except (ValueError, UnicodeDecodeError):
        done = True

    request.user.has_taken_tour = done
    request.user.save(update_fields=["has_taken_tour"])
    return JsonResponse({"ok": True, "has_taken_tour": done})


# ---------------------------------------------------------------------------
# Help - written from the questions the shop owner actually asked
# ---------------------------------------------------------------------------
@login_required
def help_page(request):
    """Every question on this page is one the client wrote on a piece of paper
    and sent back. It is deliberately in his words, not the software's: he
    asked how to "cash out", so the answer is filed under cashing out.

    A cashier sees only the selling half. The rest needs an admin account, and
    showing a cashier instructions for a screen they cannot open is just
    confusing.
    """
    return render(request, "shop/help.html", {})


# ---------------------------------------------------------------------------
# Other computers - using the system from a second and third till
# ---------------------------------------------------------------------------
def _server_addresses():
    """Every address on this machine that another till could type in.

    A shop PC often has both a cable and wi-fi, and only one of them is on the
    same network as the other tills. Guessing wrong wastes an afternoon, so
    list them all and let him try each one.
    """
    port = os.environ.get("SMMS_PORT", "8000")
    addresses = []
    seen = set()

    # The address that would be used to reach the outside world is almost
    # always the one on the shop's own network.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            primary = probe.getsockname()[0]
    except OSError:
        primary = None

    if primary:
        addresses.append({"ip": primary, "port": port, "primary": True})
        seen.add(primary)

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip in seen or ip.startswith("127."):
                continue
            seen.add(ip)
            addresses.append({"ip": ip, "port": port, "primary": False})
    except OSError:
        pass

    return addresses, port


@admin_required
def network(request):
    """How to put the system on a second computer - the client's question.

    Everything here is read-only. It exists because the answer is a specific
    address that changes with the router, and telling someone to "find your IP
    address" over the phone does not work.
    """
    addresses, port = _server_addresses()
    host = request.get_host()
    return render(request, "shop/network.html", {
        "addresses": addresses,
        "port": port,
        "hostname": socket.gethostname(),
        "this_request_host": host,
        # If this page was opened as 127.0.0.1 or localhost, he is sitting at
        # the server itself and the instructions below are for the OTHER
        # machine. If not, he is already on a second till and it is working.
        "viewing_from_server": host.split(":")[0] in ("127.0.0.1", "localhost", "::1"),
    })


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

        # NOT a file copy. The database runs in WAL mode so a second till never
        # freezes the first, and in WAL mode the newest committed sales may
        # still be sitting in db.sqlite3-wal rather than in db.sqlite3 itself.
        # Copying the one file would silently produce a backup missing this
        # morning's takings - and nobody finds out until they need it.
        # SQLite's own backup API takes a consistent copy of everything while
        # the shop keeps trading.
        source = sqlite3.connect(django_settings.BASE_DIR / "db.sqlite3")
        try:
            destination = sqlite3.connect(target)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()

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
