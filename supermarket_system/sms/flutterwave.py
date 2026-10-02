"""Buying SMS credit online - Flutterwave v3, standard library only.

The account is CampusNect's, so the money for credit lands with the company
that pays EGO for it. Keys come from the server's environment.

WHY PAYMENTS ARE CONFIRMED BY ASKING, NOT BY WAITING TO BE TOLD. A Flutterwave
account has ONE webhook address, and CampusNect's already points at
pay.campusnect.com. So this shop never hears a webhook; it confirms a payment
when the payer comes back to the return page, and again whenever the owner
opens the SMS page, by asking Flutterwave for the transaction by its
reference. A payer who closed the browser early is credited the next time
anyone looks.
"""
import json
import urllib.parse
import urllib.request

from django.conf import settings

BASE = "https://api.flutterwave.com/v3"


def configured():
    return bool(getattr(settings, "FLW_SECRET_KEY", ""))


def _request(method, path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        BASE + path, data=body, method=method,
        headers={"Authorization": f"Bearer {settings.FLW_SECRET_KEY}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def create_payment(tx_ref, amount, redirect_url, customer, title, description):
    data = _request("POST", "/payments", {
        "tx_ref": tx_ref, "amount": str(amount), "currency": "UGX",
        "redirect_url": redirect_url, "payment_options": "mobilemoneyuganda, card",
        "customer": customer,
        "customizations": {"title": title, "description": description},
    })
    if data.get("status") != "success":
        raise RuntimeError(data.get("message") or "Flutterwave refused the payment.")
    return data["data"]["link"]


def verify_reference(tx_ref):
    """Flutterwave's record of this payment, or {} if it has none."""
    path = "/transactions/verify_by_reference?" + urllib.parse.urlencode({"tx_ref": tx_ref})
    try:
        answer = _request("GET", path)
    except Exception:
        return {}
    return answer.get("data") or {} if answer.get("status") == "success" else {}
