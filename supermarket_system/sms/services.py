"""Sending a text, and everything that decides whether it may go.

The gateway is EGO SMS (Pahappa), the same company CampusNect uses for St
Lucia and Team, on a channel of the shop's own - so its traffic and its credit
are separate at the provider, not merely labelled. The client below is the one
proven there, cut down to what one shop needs.

Two things that look like details and are not, both learnt the hard way on
CampusNect:

* HTTP 200 IS NOT "SENT". EGO answers a refused message with 200 and the reason
  in the body ("Status": "Failed"). The Status field is read, never the code.
* THE NUMBER GOES BARE - 256700111222, no plus, no leading 0.
"""
import json
import logging
import re
import urllib.error
import urllib.request

from django.conf import settings
from django.db import transaction

from .models import Message, balance_pages

logger = logging.getLogger(__name__)

EGO_URL = "https://comms.egosms.co/api/v1/json/"

# The GSM 03.38 basic alphabet. A message using only these fits 160 to a page;
# one curly quote or an emoji turns the whole message into Unicode, 70 a page.
_GSM = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
           "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
_GSM_EXT = set("^{}\\[~]|€")  # these take two places each


def pages(body):
    """How many SMS one copy of `body` costs.

    160 characters is one page and 153 thereafter (a split message carries a
    header in each part); outside the GSM alphabet it is 70 and 67.
    """
    body = body or ""
    if not body:
        return 0
    if all(ch in _GSM or ch in _GSM_EXT for ch in body):
        length = sum(2 if ch in _GSM_EXT else 1 for ch in body)
        single, multi = 160, 153
    else:
        length = len(body)
        single, multi = 70, 67
    if length <= single:
        return 1
    return -(-length // multi)


def normalise_phone(raw):
    """'0772 123 456', '+256 772-123456', '772123456' -> '256772123456'.

    None for anything that is not a Ugandan mobile number: a text to a wrong
    number costs the same as one to the right one.
    """
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("256") and len(digits) == 12:
        number = digits
    elif digits.startswith("0") and len(digits) == 10:
        number = "256" + digits[1:]
    elif len(digits) == 9 and digits[0] == "7":
        number = "256" + digits
    else:
        return None
    return number if number[3] == "7" else None


def mask(number):
    """'256772123456' -> '0772 *** 456' - enough to recognise, not to copy."""
    if not number:
        return ""
    local = "0" + number[3:]
    return f"{local[:4]} *** {local[-3:]}"


def is_configured():
    return bool(getattr(settings, "SMS_CONFIGURED", False))


def is_live():
    return is_configured() and bool(getattr(settings, "SMS_LIVE", False))


def price():
    return int(getattr(settings, "SMS_PRICE", 45) or 45)


class GatewayError(Exception):
    pass


def ego_send(number, body):
    """Send one message through EGO. Returns EGO's reply text; raises
    GatewayError if it was refused."""
    payload = {
        "method": "SendSms",
        "userdata": {"username": settings.SMS_USERNAME, "password": settings.SMS_KEY},
        "msgdata": [{"number": number, "message": body,
                     "senderid": settings.SMS_SENDER, "priority": "0"}],
    }
    request = urllib.request.Request(
        EGO_URL, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            status, raw = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        raise GatewayError(f"EGO refused it (HTTP {exc.code}): {raw.strip()[:150]}")
    except (urllib.error.URLError, OSError) as exc:
        raise GatewayError(f"Could not reach EGO: {exc}")
    try:
        answer = json.loads(raw)
    except ValueError:
        raise GatewayError(f"EGO answered something unreadable: {raw.strip()[:150]}")
    if str(answer.get("Status", "")).strip().upper() != "OK" or not 200 <= status < 300:
        raise GatewayError(answer.get("Message") or raw.strip()[:150])
    return (answer.get("Message") or "OK")[:255]


def send(number, body, *, kind, recipient="", broadcast=None, logged_body=None):
    """Send `body` to `number` if there is credit for it. Returns the Message.

    The credit check and the record are one step, so two messages going at
    once cannot both spend the last page. `logged_body` is what the record
    keeps instead of the text - a sign-in code is never written down.
    """
    n = pages(body)
    record = dict(kind=kind, number=number, recipient=recipient[:120],
                  body=logged_body if logged_body is not None else body,
                  pages=n, cost=n * price(), broadcast=broadcast)

    if not is_live():
        return Message.objects.create(status=Message.Status.TEST, **record)

    with transaction.atomic():
        if balance_pages() < n:
            return Message.objects.create(status=Message.Status.NO_CREDIT, **record)
        # Counted as spent before it goes: if the gateway then refuses it, the
        # page is handed back below. The other way round, two sends at once
        # could both see the last page as free.
        message = Message.objects.create(status=Message.Status.SENT, **record)
    try:
        message.gateway_reply = ego_send(number, body)
        message.save(update_fields=["gateway_reply"])
    except GatewayError as exc:
        logger.warning("SMS to %s failed: %s", number, exc)
        message.status = Message.Status.FAILED
        message.gateway_reply = str(exc)[:255]
        message.save(update_fields=["status", "gateway_reply"])
    return message


def alert_owner(text):
    """The till alerts and the day summary, by SMS as well as email. Quietly
    skipped (and logged) when SMS is not set up or the credit has run out -
    the email has already gone."""
    if not is_configured():
        return []
    sent = []
    for raw in getattr(settings, "OWNER_ALERT_PHONES", []) or []:
        number = normalise_phone(raw)
        if not number:
            logger.warning("MAQAM_ALERT_PHONE %r is not a Ugandan mobile number", raw)
            continue
        message = send(number, text, kind=Message.Kind.ALERT, recipient="Owner")
        if message.status == Message.Status.NO_CREDIT:
            logger.warning("Owner alert not texted - SMS credit is used up: %s", text[:60])
        sent.append(message)
    return sent
