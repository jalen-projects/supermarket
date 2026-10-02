"""The watch on the tills, and the emails that tell the owner about it.

THE FEAR THIS ANSWERS. Mr. Mujuzi's objection to going online was that a
cashier can switch off the router - or the computer - while he is away, sell
for cash with the system blind, and switch it back on before he returns.

Offline he could never know. Online the server is not in the shop, so the shop
cannot switch it off. Every open till checks in once a minute; if every till
goes quiet while the shop should be trading, a check that runs on the server
every five minutes emails his phone. When the tills come back he gets a
second email saying how long they were gone. The router being off is exactly
what stops the tills checking in, so it is exactly what raises the alarm.

Nothing here can tell him WHY the tills went quiet - a power cut looks the
same as a cashier. That is said plainly in the email, so a blackout across
Kampala is not taken for theft.
"""
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Max, Sum
from django.utils import timezone

from .audit import record
from .models import AuditEvent, ShopSettings, Till, TillGap

logger = logging.getLogger(__name__)

Action = AuditEvent.Action


def alert_recipients():
    return list(getattr(settings, "OWNER_ALERT_EMAILS", []) or [])


def _send(subject, body, sms=None):
    """Email the owner - and text him `sms` too, where the shop's SMS channel
    is set up (online only, drawn from the shop's SMS credit). True if either
    reached him. The gap is recorded either way and shows on his phone."""
    emailed = False
    to = alert_recipients()
    if to:
        try:
            send_mail(subject, body, None, to, fail_silently=False)
            emailed = True
        except Exception:
            logger.exception("Owner alert could not be emailed: %s", subject)
    texted = False
    if sms:
        try:
            from sms.models import Message
            from sms.services import alert_owner
            texted = any(m.status in (Message.Status.SENT, Message.Status.TEST)
                         for m in alert_owner(sms))
        except Exception:  # a text that failed must never stop the watch
            logger.exception("Owner alert could not be texted: %s", subject)
    return emailed or texted


# ---------------------------------------------------------------------------
# A till checking in
# ---------------------------------------------------------------------------
def check_in(*, key, label="", user=None, ip=None, phone=False, now=None):
    """Record that this till is alive. Closes an open gap if it was silent.

    A phone checking in is remembered but proves nothing about the shop: the
    owner reading his phone at home must not count as a till being on.
    """
    now = now or timezone.now()
    key = (key or "")[:40]
    if not key:
        return None
    with transaction.atomic():
        till, made = Till.objects.get_or_create(
            key=key, defaults={"label": label[:120], "first_seen": now, "last_seen": now})
        till.last_seen = now
        till.last_user = user if (user is not None and user.is_authenticated) else None
        till.last_ip = ip
        till.is_phone = phone
        if label:
            till.label = label[:120]
        till.save()
        if phone:
            return till

        gap = TillGap.objects.filter(ended_at__isnull=True).first()
        if gap is not None:
            gap.ended_at = now
            gap.save(update_fields=["ended_at"])
            record(Action.TILLS_BACK,
                   f"Tills back after {gap.length_label} silent", user=user,
                   reference=f"gap-{gap.pk}")
    return till


# ---------------------------------------------------------------------------
# The five-minute check, run by cron on the server
# ---------------------------------------------------------------------------
def _at(day, clock):
    return timezone.make_aware(datetime.combine(day, clock))


def last_opening(shop, now):
    """When the shop most recently opened, at or before `now`."""
    today = timezone.localtime(now).date()
    opened = _at(today, shop.opens_at)
    if opened > now:
        opened = _at(today - timedelta(days=1), shop.opens_at)
    return opened


def trading_day_just_ended(shop, now):
    """The date whose trading has finished, or None while the shop is open."""
    if shop.is_open_at(now):
        return None
    local = timezone.localtime(now)
    if shop.opens_at <= shop.closes_at and local.time() >= shop.closes_at:
        return local.date()
    return local.date() - timedelta(days=1)


def check_tills(now=None):
    """Open a gap and alert, or close a stale one, or send the 'back' email.

    Returns a short description of what it did, for the cron log.
    """
    now = now or timezone.now()
    shop = ShopSettings.get()
    done = []

    # The back-online emails are owed whatever time it is now.
    for gap in TillGap.objects.filter(ended_at__isnull=False, alert_sent_at__isnull=False,
                                      back_alert_sent_at__isnull=True):
        _send(f"{shop.company_name}: tills back online",
              _back_body(shop, gap),
              sms=f"{_short(shop)}: tills back online. Silent "
                  f"{timezone.localtime(gap.started_at):%H:%M}-"
                  f"{timezone.localtime(gap.ended_at):%H:%M} ({gap.length_label}). "
                  f"Check the cash against the cash-up.")
        gap.back_alert_sent_at = now
        gap.save(update_fields=["back_alert_sent_at"])
        done.append(f"told owner tills are back ({gap.length_label})")

    open_gap = TillGap.objects.filter(ended_at__isnull=True).first()

    if not shop.is_open_at(now):
        # Closing time. A gap still open runs out here rather than overnight -
        # otherwise the morning's first till would report "silent 9 hours"
        # for a night when the shop was simply shut.
        if open_gap is not None:
            open_gap.ended_at = now
            open_gap.back_alert_sent_at = now
            open_gap.save(update_fields=["ended_at", "back_alert_sent_at"])
            done.append("closed a gap at closing time")
        done.extend(_maybe_send_summary(shop, now))
        return "; ".join(done) or "shop closed - nothing to check"

    if open_gap is not None:
        return "; ".join(done) or f"still silent ({open_gap.length_label})"

    last_seen = Till.objects.filter(is_phone=False).aggregate(t=Max("last_seen"))["t"]
    quiet_since = max(filter(None, [last_seen, last_opening(shop, now)]))
    if now - quiet_since < timedelta(minutes=shop.silence_alert_minutes):
        return "; ".join(done) or "tills checking in"

    gap = TillGap.objects.create(started_at=quiet_since)
    record(Action.TILLS_SILENT,
           f"No till has reached the system since "
           f"{timezone.localtime(quiet_since):%H:%M}",
           reference=f"gap-{gap.pk}")
    _send(f"{shop.company_name}: no till has been online since "
          f"{timezone.localtime(quiet_since):%H:%M}",
          _silent_body(shop, gap, now),
          sms=f"{_short(shop)} ALERT: no till has reached the system since "
              f"{timezone.localtime(quiet_since):%H:%M}. Power, internet or a "
              f"switched-off router - a call to the shop will tell.")
    # Stamped even if the mail failed: the gap is on his phone screen either
    # way, and the 'back' email still owes him the length of it.
    gap.alert_sent_at = now
    gap.save(update_fields=["alert_sent_at"])
    done.append(f"tills silent since {timezone.localtime(quiet_since):%H:%M} - owner alerted")
    return "; ".join(done)


def _silent_body(shop, gap, now):
    started = timezone.localtime(gap.started_at)
    return (
        f"No till at {shop.company_name} has reached the system since "
        f"{started:%H:%M} today - {gap.length_label} ago, while the shop "
        f"should be open (until {shop.closes_at:%H:%M}).\n\n"
        f"Any sale made in that time is not in the system.\n\n"
        f"It can be: the router or the internet switched off, the power off, or "
        f"the tills simply closed. The system cannot tell which - a call to the "
        f"shop can.\n\n"
        f"You will get another email the moment a till comes back, saying how "
        f"long they were gone.\n\n"
        f"See it live: https://{_host()}/owner/\n\n"
        f"- Sent automatically by your shop system (CampusNect Smart Technologies)")


def _back_body(shop, gap):
    started = timezone.localtime(gap.started_at)
    ended = timezone.localtime(gap.ended_at)
    return (
        f"A till at {shop.company_name} is back online.\n\n"
        f"Silent from {started:%H:%M} to {ended:%H:%M} - {gap.length_label}.\n\n"
        f"Sales rung up in that gap are not in the system. Compare the cash in "
        f"the drawer with the cash-up when the cashier hands over.\n\n"
        f"Every sign-in, voided sale and price change is in the audit trail: "
        f"https://{_host()}/audit/\n\n"
        f"- Sent automatically by your shop system (CampusNect Smart Technologies)")


def _short(shop):
    """'MAQAM' - a text is paid for by the page, so the name goes short."""
    return (shop.company_name or "Shop").split()[0]


def _host():
    return getattr(settings, "PUBLIC_HOSTNAME", "") or "maqam.campusnect.com"


# ---------------------------------------------------------------------------
# The end-of-day summary
# ---------------------------------------------------------------------------
def day_summary(day):
    """The numbers the owner reads at night, as a dict - shared by the email
    and the tests."""
    from sales.models import Sale, Shift

    start = _at(day, datetime.min.time())
    end = start + timedelta(days=1)
    sales = Sale.objects.filter(created_at__gte=start, created_at__lt=end)
    done = sales.filter(status=Sale.Status.COMPLETED)
    voided = sales.filter(status=Sale.Status.VOIDED).select_related("voided_by")
    by_method = {row["payment_method"]: row["t"] for row in
                 done.values("payment_method").annotate(t=Sum("total"))}
    shifts = Shift.objects.filter(closed_at__gte=start, closed_at__lt=end).select_related("user")
    gaps = TillGap.objects.filter(started_at__gte=start, started_at__lt=end)
    failed = AuditEvent.objects.filter(at__gte=start, at__lt=end,
                                       action=Action.SIGN_IN_FAILED).count()
    return {
        "day": day,
        "total": done.aggregate(t=Sum("total"))["t"] or Decimal("0"),
        "count": done.count(),
        "by_method": by_method,
        "voided": list(voided),
        "voided_total": voided.aggregate(t=Sum("total"))["t"] or Decimal("0"),
        "shifts": list(shifts),
        "gaps": list(gaps),
        "failed_sign_ins": failed,
        "sellers": list(done.values("served_by__first_name", "served_by__username")
                        .annotate(t=Sum("total"), n=Count("id")).order_by("-t")),
    }


def summary_body(shop, s):
    cur = shop.currency
    lines = [f"{shop.company_name} - {s['day']:%A %d %B %Y}", ""]
    lines.append(f"Sales: {cur} {s['total']:,.0f} from {s['count']} receipt(s)")
    labels = {"CASH": "Cash", "MOBILE": "Mobile money", "CARD": "Card", "CREDIT": "Credit"}
    for method, total in s["by_method"].items():
        lines.append(f"  {labels.get(method, method)}: {cur} {total:,.0f}")
    for row in s["sellers"]:
        who = row["served_by__first_name"] or row["served_by__username"]
        lines.append(f"  Sold by {who}: {cur} {row['t']:,.0f} ({row['n']})")
    lines.append("")
    if s["voided"]:
        lines.append(f"VOIDED: {len(s['voided'])} receipt(s), {cur} {s['voided_total']:,.0f}")
        for sale in s["voided"]:
            who = sale.voided_by.display_name if sale.voided_by else "?"
            lines.append(f"  {sale.receipt_no} {cur} {sale.total:,.0f} by {who}"
                         f" - {sale.void_reason or 'no reason given'}")
    else:
        lines.append("Voided: none")
    for shift in s["shifts"]:
        v = shift.variance
        if v is None:
            continue
        state = "balanced" if v == 0 else (f"SHORT {cur} {-v:,.0f}" if v < 0
                                           else f"over {cur} {v:,.0f}")
        lines.append(f"Cash-up, {shift.user.display_name}: {state}")
    if s["gaps"]:
        lines.append("")
        for gap in s["gaps"]:
            lines.append(f"TILLS SILENT from {timezone.localtime(gap.started_at):%H:%M}"
                         f" for {gap.length_label}")
    if s["failed_sign_ins"]:
        lines.append(f"Failed sign-ins: {s['failed_sign_ins']}")
    lines += ["", f"Details: https://{_host()}/owner/",
              "- Sent automatically by your shop system (CampusNect Smart Technologies)"]
    return "\n".join(lines)


def _maybe_send_summary(shop, now):
    day = trading_day_just_ended(shop, now)
    if day is None or shop.summary_sent_for == day or not (
            alert_recipients() or getattr(settings, "OWNER_ALERT_PHONES", [])):
        return []
    s = day_summary(day)
    text = (f"{_short(shop)} {s['day']:%a %d %b}: {shop.currency} {s['total']:,.0f} "
            f"from {s['count']} receipts. Voided: {len(s['voided'])}. "
            f"Till gaps: {len(s['gaps'])}. Failed sign-ins: {s['failed_sign_ins']}.")
    if _send(f"{shop.company_name}: {s['day']:%a %d %b} - "
             f"{shop.currency} {s['total']:,.0f} sold", summary_body(shop, s), sms=text):
        ShopSettings.objects.filter(pk=shop.pk).update(summary_sent_for=day)
        return [f"sent the summary for {day}"]
    return []
