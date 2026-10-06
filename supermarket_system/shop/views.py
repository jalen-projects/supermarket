import json
import os
import re
import socket
import sqlite3
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import resolve_url, get_object_or_404, redirect, render
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from inventory.models import Product, StockBatch, expired_batches, expiring_batches
from sales.models import Sale

from . import audit, brand, services, watch
from .forms import (GuardedAuthenticationForm, PasswordResetForm, ShopSettingsForm,
                    UserEditForm, UserForm)
from .models import AuditEvent, ShopSettings, Till, TillGap, User
from .permissions import admin_required

Action = AuditEvent.Action

PHONE_AGENT = re.compile(r"Android|iPhone|iPad|iPod|Mobile", re.I)


class LoginView(auth_views.LoginView):
    template_name = "shop/login.html"
    redirect_authenticated_user = True
    authentication_form = GuardedAuthenticationForm

    def get_success_url(self):
        # A cashier signs in to sell: straight to the till, not the dashboard.
        user = getattr(self.request, "user", None)
        form_user = getattr(self, "_signed_in", None) or user
        if (form_user is not None and not getattr(form_user, "is_admin", True)
                and not self.get_redirect_url()):
            return resolve_url("pos")
        return super().get_success_url()

    def form_valid(self, form):
        self._signed_in = form.get_user()
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["first_run"] = not User.objects.exists()
        ctx["online"] = django_settings.ONLINE
        hour = timezone.localtime().hour
        ctx["greeting"] = ("Good morning" if hour < 12 else
                           "Good afternoon" if hour < 17 else "Good evening")
        ctx["trading_day"] = timezone.localdate()
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
        # Today's copy, taken the first time the owner opens the system each
        # day. A backup nobody remembers to press is not a backup.
        try:
            services.auto_backup_if_due()
        except (OSError, sqlite3.Error):
            # A failed backup must never keep him out of his own till.
            pass
        ctx["backup_age_days"] = services.last_backup_age_days()

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
    ctx["till_rolls"] = till_rolls()
    return render(request, "shop/dashboard.html", ctx)


def till_rolls(columns=3, per_column=14):
    """The lines printed on the dashboard's moving till rolls.

    His own shelves - product names and SELLING prices only, the figures
    already printed on every shelf label, never what he paid for them. A shop
    with nothing entered yet prints its own name and address instead, rather
    than products it does not sell.
    """
    shop = ShopSettings.get()
    products = list(Product.objects.filter(is_active=True, selling_price__gt=0)
                    .order_by("name").values_list("name", "selling_price")[:columns * per_column])
    if products:
        lines = [(name, f"{price:,.0f}") for name, price in products]
    else:
        lines = [(shop.company_name, ""), (shop.tagline or "", ""),
                 (shop.address or "", ""), ("Thank you for shopping with us", "")]
        lines = [line for line in lines if line[0]] * 4
    return [lines[i::columns] or lines for i in range(columns)]


# ---------------------------------------------------------------------------
# Shop settings - the 'Company name' the client asked for
# ---------------------------------------------------------------------------
@admin_required
def shop_settings_view(request):
    obj = ShopSettings.get()
    form = ShopSettingsForm(request.POST or None, request.FILES or None, instance=obj)
    before = {f: getattr(obj, f) for f in form.fields if f != "logo"}
    if request.method == "POST" and form.is_valid():
        form.save()
        after = {f: getattr(obj, f) for f in before}
        changes = audit.diff(before, after, {f: form.fields[f].label for f in before})
        if changes:
            audit.record(Action.SETTINGS_CHANGED, "Shop details changed",
                         request=request, changes=changes)
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
        audit.record(Action.USER_CREATED,
                     f"Added {user.display_name} ({user.get_role_display()})",
                     request=request, reference=user.username)
        messages.success(request, f"{user.display_name} can now sign in.")
        return redirect("user_list")
    return render(request, "shop/user_form.html", {"form": form, "title": "Add a user"})


@admin_required
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    form = UserEditForm(request.POST or None, instance=user)
    before = {f: getattr(user, f) for f in form.fields}
    if request.method == "POST" and form.is_valid():
        form.save()
        changes = audit.diff(before, {f: getattr(user, f) for f in before},
                             {f: form.fields[f].label for f in before})
        if changes:
            audit.record(Action.USER_CHANGED, f"Changed {user.display_name}",
                         request=request, changes=changes, reference=user.username)
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
        audit.record(Action.PASSWORD_RESET, f"New password set for {user.display_name}",
                     request=request, reference=user.username)
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
    """Take a copy now, and get one off this computer onto a flash disk.

    The WAL-safe copy itself lives in shop/services.backup_database - see the
    comment there before changing anything about how the file is written.
    """
    if request.method == "POST":
        if request.POST.get("to_drive"):
            drive = request.POST["to_drive"]
            try:
                target = services.copy_backup_to(drive)
            except (OSError, FileNotFoundError) as exc:
                messages.error(
                    request,
                    f"Could not write to {drive}. Is the flash disk still plugged in? ({exc})")
            else:
                messages.success(
                    request,
                    f"Copied to {target}. That copy is now safe even if this computer is not.")
        else:
            target = services.backup_database(reason="manual")
            messages.success(
                request,
                f"Backup saved as {target.name}. Now copy it to a flash disk.")
        return redirect("backup")

    rows = [{"name": b.name, "size_kb": b.stat().st_size // 1024,
             "when": timezone.datetime.fromtimestamp(b.stat().st_mtime)}
            for b in services.list_backups()]

    return render(request, "shop/backup.html", {
        "backups": rows,
        "folder": django_settings.BACKUP_DIR,
        "drives": services.removable_drives(),
        "age_days": services.last_backup_age_days(),
    })


@admin_required
def backup_download(request, name):
    path = django_settings.BACKUP_DIR / name
    if not path.exists() or path.parent != django_settings.BACKUP_DIR:
        messages.error(request, "That backup no longer exists.")
        return redirect("backup")
    # A backup is the whole shop - every price, every sale, every login. Who
    # took a copy away is exactly the kind of thing the owner will ask.
    audit.record(Action.BACKUP_DOWNLOADED, f"Downloaded the backup {name}",
                 request=request, reference=name[:60])
    return FileResponse(open(path, "rb"), as_attachment=True, filename=name)


# ---------------------------------------------------------------------------
# The watch on the tills
# ---------------------------------------------------------------------------
@require_POST
def till_check_in(request):
    """A till saying it is alive. Called once a minute by every open screen.

    Signed-in only: an anonymous ping would let anyone on the internet keep
    the alarm quiet while the shop's own tills were switched off.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False}, status=403)
    try:
        data = json.loads(request.body.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        data = {}
    agent = request.META.get("HTTP_USER_AGENT", "")
    till = watch.check_in(
        key=str(data.get("till", "")), label=str(data.get("label", "")),
        user=request.user, ip=audit.client_ip(request),
        phone=bool(PHONE_AGENT.search(agent)))
    return JsonResponse({"ok": till is not None})


@admin_required
def owner_view(request):
    """The owner's shop on his phone: what was sold, are the tills alive, and
    what happened that he would want to know about."""
    shop = ShopSettings.get()
    now = timezone.now()
    today = timezone.localdate()
    start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
    todays = Sale.objects.filter(created_at__gte=start)
    done = todays.filter(status=Sale.Status.COMPLETED)
    by_method = {row["payment_method"]: row["t"] for row in
                 done.values("payment_method").annotate(t=Sum("total"))}
    tills = list(Till.objects.filter(is_phone=False).select_related("last_user")[:8])
    last_seen = tills[0].last_seen if tills else None
    return render(request, "shop/owner.html", {
        "now": now,
        "total": done.aggregate(t=Sum("total"))["t"] or Decimal("0"),
        "count": done.count(),
        "cash": by_method.get(Sale.Payment.CASH, Decimal("0")),
        "mobile": by_method.get(Sale.Payment.MOBILE, Decimal("0")),
        "card": by_method.get(Sale.Payment.CARD, Decimal("0")),
        "credit": by_method.get(Sale.Payment.CREDIT, Decimal("0")),
        "voided": todays.filter(status=Sale.Status.VOIDED).count(),
        "tills": tills,
        "alive": bool(last_seen and (now - last_seen).total_seconds() < 180),
        "last_seen": last_seen,
        "shop_open": shop.is_open_at(now),
        "open_gap": TillGap.objects.filter(ended_at__isnull=True).first(),
        "gaps_today": TillGap.objects.filter(started_at__gte=start),
        "events": AuditEvent.objects.select_related("user")[:12],
    })


@admin_required
def audit_list(request):
    """Every line of the trail, newest first, filterable by what happened."""
    events = AuditEvent.objects.select_related("user")
    action = request.GET.get("action", "")
    if action in Action.values:
        events = events.filter(action=action)
    who = request.GET.get("who", "").strip()
    if who:
        events = events.filter(username__icontains=who)
    day = request.GET.get("day", "")
    if day:
        try:
            d = timezone.datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError:
            d = None
        if d:
            start = timezone.make_aware(timezone.datetime.combine(d, timezone.datetime.min.time()))
            events = events.filter(at__gte=start, at__lt=start + timedelta(days=1))
    page = Paginator(events, 50).get_page(request.GET.get("page"))
    return render(request, "shop/audit.html", {
        "page": page, "actions": Action.choices, "action": action,
        "who": who, "day": day,
        "qs": "".join(urlencode({k: v}) + "&" for k, v in
                      (("action", action), ("who", who), ("day", day)) if v),
    })


# ---------------------------------------------------------------------------
# The phone app - a web app he installs from the browser, nothing to download
# ---------------------------------------------------------------------------
def manifest(request):
    shop = ShopSettings.get()
    name = shop.company_name
    response = JsonResponse({
        "name": name,
        "short_name": name.split()[0][:12] if name else "Shop",
        "description": "Your shop on your phone - takings, tills and the audit trail.",
        "start_url": "/owner/?source=app",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#1d1612",
        "theme_color": "#1d1612",
        "icons": [
            # This shop's own icons (shop/brand.py), through static() so
            # that online they carry the fingerprinted names.
            {"src": static(brand.icon("app-192.png")), "sizes": "192x192", "type": "image/png"},
            {"src": static(brand.icon("app-512.png")), "sizes": "512x512", "type": "image/png"},
            {"src": static(brand.icon("app-maskable-512.png")), "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    })
    response["Content-Type"] = "application/manifest+json"
    return response


@never_cache
def service_worker(request):
    """Served from the root rather than /static/, because a service worker can
    only look after pages at or below the address it was loaded from."""
    path = django_settings.BASE_DIR / "static" / "js" / "sw.js"
    response = HttpResponse(
        path.read_text(encoding="utf-8").replace("__STAMP__", _static_stamp())
        .replace("__BRAND__", brand.current()["key"]),
        content_type="application/javascript")
    # Never kept: a phone must always be able to learn there is a new version.
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response


def _static_stamp():
    """A short fingerprint of the app's look, for the service worker's cache
    name. Taken from the collected manifest online (it changes whenever any
    style, script or picture does), else from the source files themselves."""
    import hashlib
    digest = hashlib.sha1()
    manifest = django_settings.STATIC_ROOT / "staticfiles.json"
    if manifest.exists():
        digest.update(manifest.read_bytes())
    else:
        for sub in ("css", "js", "brand", "img"):
            for f in sorted((django_settings.BASE_DIR / "static" / sub).glob("*")):
                if f.is_file():
                    digest.update(f.name.encode())
                    digest.update(str(f.stat().st_mtime_ns).encode())
    return digest.hexdigest()[:10]


def offline_page(request):
    """What the phone shows when it has no connection. Cached by the service
    worker; carries no figures, so nothing stale can be mistaken for today."""
    return render(request, "shop/offline.html", {})
