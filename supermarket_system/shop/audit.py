"""The audit trail: one function every screen calls, and the sign-in signals.

Recording is deliberately explicit - a call in the view that did the thing -
rather than a signal on every model save. A save signal cannot tell a price
the owner changed from a total the till recalculated, and a trail that lists
both is a trail nobody reads.

Recording must never stop the shop. If writing the line fails, the sale is
still voided and the price is still changed; a lost audit line is bad, a till
that refuses to work because of one is worse.
"""
import logging

from django.conf import settings
from django.contrib.auth.signals import (user_logged_in, user_logged_out,
                                         user_login_failed)
from django.dispatch import receiver

from .models import AuditEvent

logger = logging.getLogger(__name__)

Action = AuditEvent.Action


def client_ip(request):
    """The address of the machine that made the request.

    Online the app sits behind nginx, so REMOTE_ADDR is always nginx itself.
    nginx's proxy_params sets X-Real-IP from the connection it accepted, and
    it overwrites whatever the browser sent - so that header can be trusted
    there, and only there. On the shop's own network there is no proxy and a
    browser could send any header it liked, so it is ignored.
    """
    if request is None:
        return None
    if getattr(settings, "ONLINE", False):
        real = request.META.get("HTTP_X_REAL_IP", "").strip()
        if real:
            return real
    return request.META.get("REMOTE_ADDR") or None


def diff(before, after, labels=None):
    """'Selling price: 1,500 -> 1,800' lines for the fields that changed."""
    labels = labels or {}
    lines = []
    for field, old in before.items():
        new = after.get(field)
        if _same(old, new):
            continue
        name = labels.get(field, field.replace("_", " ").capitalize())
        lines.append(f"{name}: {_show(old)} -> {_show(new)}")
    return "\n".join(lines)


def _same(a, b):
    # A price comes back from the database as Decimal("1500.00") and out of a
    # form as Decimal("1500"); compared as text they differ and every save
    # would log a change that never happened.
    try:
        return a == b
    except TypeError:
        return str(a) == str(b)


def _show(value):
    if value is None or value == "":
        return "(blank)"
    if isinstance(value, bool):
        return "yes" if value else "no"
    try:
        from decimal import Decimal
        if isinstance(value, Decimal):
            return f"{value:,.0f}" if value == value.to_integral() else f"{value:,}"
    except Exception:
        pass
    return str(value)


def record(action, summary, request=None, user=None, changes="", reference=""):
    """Write one line. Returns the event, or None if it could not be written."""
    if user is None and request is not None:
        candidate = getattr(request, "user", None)
        if candidate is not None and candidate.is_authenticated:
            user = candidate
    try:
        return AuditEvent.objects.create(
            action=action,
            summary=summary[:255],
            changes=changes or "",
            user=user if (user is not None and getattr(user, "pk", None)) else None,
            username=(user.get_username() if user is not None else "")[:150],
            ip_address=client_ip(request),
            reference=(reference or "")[:60],
        )
    except Exception:  # never let the trail stop the shop
        logger.exception("Could not write an audit line: %s", summary)
        return None


# ---------------------------------------------------------------------------
# Signing in and out
# ---------------------------------------------------------------------------
@receiver(user_logged_in)
def _signed_in(sender, request, user, **kwargs):
    record(Action.SIGN_IN, f"{user.display_name} signed in", request=request, user=user)


@receiver(user_logged_out)
def _signed_out(sender, request, user, **kwargs):
    if user is None:
        return
    record(Action.SIGN_OUT, f"{user.display_name} signed out", request=request, user=user)


@receiver(user_login_failed)
def _sign_in_failed(sender, credentials, request=None, **kwargs):
    # The password typed is never recorded - not even a wrong one, which is
    # very often the right password for something else.
    name = (credentials or {}).get("username", "")[:60]
    record(Action.SIGN_IN_FAILED, f"Wrong password for '{name}'",
           request=request, reference=name)
