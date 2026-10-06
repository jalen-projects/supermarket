"""The sign-in code step, and the owner's SMS screens."""
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from sales.models import Customer, Sale
from shop import audit
from shop.forms import is_locked_out
from shop.models import AuditEvent, ShopSettings, User
from shop.permissions import admin_required
from shop.views import LoginView

from . import credit, flutterwave, services, signin
from .models import Broadcast, Message, SignInCode, TopUp, balance_pages

Action = AuditEvent.Action


# ---------------------------------------------------------------------------
# Signing in: password first, then the code
# ---------------------------------------------------------------------------
class CodeLoginView(LoginView):
    """The ordinary sign-in, with a second step when the shop is online and
    its SMS channel is set up. The password is checked exactly as before -
    including the lock after five wrong ones - and only then is a code sent."""

    def form_valid(self, form):
        user = form.get_user()
        if not signin.required(user):
            return super().form_valid(form)
        shop = ShopSettings.get()
        try:
            row = signin.send_code(user, shop_name=_short_name(shop))
        except signin.Refused as why:
            audit.record(Action.OTP_FAILED, f"No sign-in code could reach {user.display_name}",
                         request=self.request, user=user, reference=user.get_username())
            form.add_error(None, str(why))
            return self.form_invalid(form)
        self.request.session[signin.SESSION_KEY] = {
            "user": user.pk,
            "backend": getattr(user, "backend", "django.contrib.auth.backends.ModelBackend"),
            "next": self.get_success_url(),
            "code": row.pk,
        }
        audit.record(Action.OTP_SENT,
                     f"Sign-in code sent to {user.display_name} ({row.sent_to})",
                     request=self.request, user=user, reference=user.get_username())
        return redirect("sms_code")


def _short_name(shop):
    return (shop.company_name or "Shop").split()[0]


def code_step(request):
    pending = request.session.get(signin.SESSION_KEY)
    if not pending:
        return redirect("login")
    user = User.objects.filter(pk=pending["user"], is_active=True).first()
    row = SignInCode.objects.filter(pk=pending["code"], user=user).first() if user else None
    if user is None or row is None:
        request.session.pop(signin.SESSION_KEY, None)
        return redirect("login")

    def start_again(text):
        request.session.pop(signin.SESSION_KEY, None)
        messages.error(request, text)
        return redirect("login")

    error = ""
    if request.method == "POST":
        if is_locked_out(request, user.get_username()):
            return start_again("Too many wrong attempts. Sign-in is paused for 15 minutes.")

        if request.POST.get("resend"):
            if not row.may_resend:
                error = "Please wait a minute before asking for another code."
            else:
                try:
                    row = signin.send_code(user, shop_name=_short_name(ShopSettings.get()))
                except signin.Refused as why:
                    return start_again(str(why))
                pending["code"] = row.pk
                request.session[signin.SESSION_KEY] = pending
                audit.record(Action.OTP_SENT, f"Sign-in code sent again to "
                             f"{user.display_name} ({row.sent_to})",
                             request=request, user=user, reference=user.get_username())
        elif row.matches(request.POST.get("code", "")):
            request.session.pop(signin.SESSION_KEY, None)
            audit.record(Action.OTP_PASSED, f"{user.display_name} entered the right sign-in code",
                         request=request, user=user, reference=user.get_username())
            login(request, user, backend=pending["backend"])
            target = pending.get("next") or "/"
            if not url_has_allowed_host_and_scheme(target, {request.get_host()},
                                                   require_https=request.is_secure()):
                target = "/"
            return redirect(target)
        else:
            audit.record(Action.OTP_FAILED, f"Wrong sign-in code for '{user.get_username()}'",
                         request=request, user=user, reference=user.get_username())
            if not row.is_live:
                return start_again("That code has expired or was entered wrongly too many "
                                   "times. Sign in again for a new one.")
            error = "That code is not right. Check the message and try again."

    return render(request, "sms/code.html", {
        "who": user, "row": row, "error": error,
        "online": getattr(settings, "ONLINE", False),
        "trading_day": timezone.localdate(),
    })


# ---------------------------------------------------------------------------
# The owner's SMS screens
# ---------------------------------------------------------------------------
def _sms_screen(view):
    """Owner only, and only where SMS exists at all."""
    @login_required
    @admin_required
    def wrapped(request, *args, **kwargs):
        if not getattr(settings, "ONLINE", False):
            raise Http404("SMS is only available online.")
        return view(request, *args, **kwargs)
    wrapped.__name__ = view.__name__
    return wrapped


@_sms_screen
def home(request):
    credited = credit.confirm_pending()
    if credited:
        messages.success(request, "Your SMS payment has arrived - the credit is added.")
    unit = services.price()
    left = balance_pages()
    return render(request, "sms/home.html", {
        "pages_left": left,
        "money_left": max(left, 0) * unit,
        "price": unit,
        "bundles": [{"amount": a, "pages": a // unit} for a in credit.BUNDLES],
        "topups": TopUp.objects.all()[:12],
        "recent": Message.objects.select_related("broadcast")[:30],
        "configured": services.is_configured(),
        "live": services.is_live(),
        "can_pay": flutterwave.configured(),
    })


@_sms_screen
@require_POST
def buy(request):
    try:
        amount = int(request.POST.get("amount") or 0)
    except ValueError:
        amount = 0
    if amount not in credit.BUNDLES:
        messages.error(request, "Choose one of the bundles.")
        return redirect("sms_home")
    if not flutterwave.configured():
        messages.error(request, "Online payment is not switched on yet. Pay by Mobile "
                                "Money to +256 708 646603 and CampusNect will add the credit.")
        return redirect("sms_home")
    topup = credit.new_topup(amount)
    shop = ShopSettings.get()
    try:
        link = flutterwave.create_payment(
            topup.reference, amount,
            request.build_absolute_uri(reverse("sms_paid")),
            {"email": request.user.email or "payer@campusnect.com",
             "phonenumber": request.user.phone or shop.phone,
             "name": request.user.display_name},
            f"{shop.company_name} - SMS credit",
            f"{topup.pages} SMS pages at UGX {topup.price_per_page}")
    except Exception:
        topup.status = TopUp.Status.FAILED
        topup.save(update_fields=["status"])
        messages.error(request, "The payment could not be started just now. Try again in a moment.")
        return redirect("sms_home")
    return redirect(link)


@_sms_screen
def paid(request):
    """Where Flutterwave sends the payer back. Confirmed by asking, never by
    believing the address bar."""
    topup = TopUp.objects.filter(reference=request.GET.get("tx_ref", "")).first()
    if topup and credit.confirm(topup):
        messages.success(request, f"Paid - {topup.pages} SMS pages added.")
    elif topup and topup.status == TopUp.Status.PAID:
        messages.success(request, "That payment is already added.")
    else:
        messages.warning(request, "We could not confirm the payment yet. If you were "
                                  "charged it will be added when you next open this page.")
    return redirect("sms_home")


def top_customers(days, limit):
    since = timezone.now() - timedelta(days=days)
    return (Customer.objects.filter(is_active=True)
            .exclude(phone="")
            .annotate(spent=Sum("sales__total", filter=Q(
                sales__status=Sale.Status.COMPLETED, sales__created_at__gte=since)),
                visits=Count("sales", filter=Q(
                    sales__status=Sale.Status.COMPLETED, sales__created_at__gte=since)))
            .filter(spent__gt=0)
            .order_by("-spent")[:limit])


@_sms_screen
def compose(request):
    try:
        days = max(1, min(365, int(request.GET.get("days") or 30)))
        limit = max(1, min(500, int(request.GET.get("top") or 20)))
    except ValueError:
        days, limit = 30, 20
    customers = list(top_customers(days, limit))
    cashiers = list(User.objects.filter(role=User.Role.CASHIER, is_active=True)
                    .exclude(phone="").order_by("first_name", "username"))
    body = (request.POST.get("body") or "").strip()
    chosen_c = set(request.POST.getlist("customer"))
    chosen_u = set(request.POST.getlist("cashier"))

    recipients = []
    for c in customers:
        if str(c.pk) in chosen_c:
            recipients.append((c.name, c.phone))
    for u in cashiers:
        if str(u.pk) in chosen_u:
            recipients.append((u.display_name, u.phone))
    valid, invalid, seen = [], [], set()
    for name, phone in recipients:
        number = services.normalise_phone(phone)
        if not number:
            invalid.append(name)
        elif number not in seen:
            seen.add(number)
            valid.append((name, number))

    per = services.pages(body)
    total_pages = per * len(valid)
    ctx = {
        "customers": customers, "cashiers": cashiers, "days": days, "top": limit,
        "body": body, "chosen_c": chosen_c, "chosen_u": chosen_u,
        "valid": valid, "invalid": invalid, "per": per,
        "total_pages": total_pages, "total_cost": total_pages * services.price(),
        "pages_left": balance_pages(), "price": services.price(),
        "live": services.is_live(),
    }

    if request.method == "POST" and request.POST.get("step") == "send":
        if not body or not valid:
            messages.error(request, "Write the message and choose at least one person.")
        elif services.is_live() and total_pages > balance_pages():
            messages.error(request, f"That needs {total_pages} pages and there are "
                                    f"{balance_pages()} left. Buy a bundle first.")
        else:
            parts = []
            if chosen_c:
                parts.append(f"{len(chosen_c)} customer(s)")
            if chosen_u:
                parts.append(f"{len(chosen_u)} cashier(s)")
            batch = Broadcast.objects.create(created_by=request.user, body=body,
                                             audience=" and ".join(parts)[:200])
            results = [services.send(number, body, kind=Message.Kind.BROADCAST,
                                     recipient=name, broadcast=batch)
                       for name, number in valid]
            went = sum(m.status in (Message.Status.SENT, Message.Status.TEST) for m in results)
            messages.success(request, f"Sent to {went} of {len(results)}."
                             + ("" if services.is_live() else " (Test mode - nothing really left.)"))
            return redirect("sms_broadcast", pk=batch.pk)
    elif request.method == "POST":
        ctx["preview"] = bool(body and valid)
    return render(request, "sms/compose.html", ctx)


@_sms_screen
def broadcast_detail(request, pk):
    batch = get_object_or_404(Broadcast, pk=pk)
    return render(request, "sms/broadcast.html", {
        "batch": batch, "rows": batch.messages.all()})
