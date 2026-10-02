"""Who gets a sign-in code, by which road, and what happens when a road is shut.

ONLINE ONLY, AND ONLY ONCE THE SHOP'S SMS CHANNEL IS SET UP. On the shop PC,
or before the channel's credentials are on the server, signing in is exactly
the password it always was.

THE OWNER (an ADMIN) gets the code by SMS and by email, both at once. Either is
enough. With no phone on his account it goes by email alone; he is never
locked out of his own shop because the SMS credit ran dry.

A CASHIER gets it by SMS to the phone on their account. Two roads can be shut:

* No phone on the account - the cashier is refused, and told to ask the owner
  to add their number. A code cannot go to "somewhere".

* The SMS cannot go (credit used up, or EGO down) - the code goes to the OWNER
  instead, by email, saying which cashier is signing in. The cashier is told to
  ask him for it. This is the safest of the three choices:
    - letting the cashier in without a code would make "credit ran out" the
      way round the lock - exactly the hole the codes exist to close;
    - refusing outright would close the till on a busy day over a top-up, and
      a till that cannot sell gets worked round with a notebook;
    - routing it through the owner keeps the second factor (him) and keeps the
      shop selling. He also learns at once that the credit needs topping up.
  If there is no owner email either, the cashier is refused with that reason.
"""
from django.conf import settings
from django.core.mail import send_mail

from . import services
from .models import Message, SignInCode

SESSION_KEY = "sms_pending_sign_in"


class Refused(Exception):
    """No code can reach anybody who should have it. The message says why."""


def required(user):
    return bool(getattr(settings, "ONLINE", False)) and services.is_configured()


def _owner_emails():
    return list(getattr(settings, "OWNER_ALERT_EMAILS", []) or [])


def _email(to, subject, body):
    if not to:
        return False
    try:
        send_mail(subject, body, None, to, fail_silently=False)
        return True
    except Exception:
        return False


def _sms_text(shop_name, code):
    return f"{code} is your {shop_name} sign-in code. It expires in 5 minutes. Never share it."


def send_code(user, shop_name="MAQAM"):
    """Issue a code and deliver it. Returns the SignInCode; raises Refused."""
    number = services.normalise_phone(getattr(user, "phone", ""))
    if not user.is_admin and not number:
        raise Refused(
            "Your account has no mobile number, so the sign-in code cannot reach "
            "you. Ask the owner to add your number under Users, then try again.")

    row, code = SignInCode.issue(user)
    roads = []

    sms_went = False
    if number:
        message = services.send(
            number, _sms_text(shop_name, code), kind=Message.Kind.CODE,
            recipient=user.display_name,
            logged_body=_sms_text(shop_name, "******"))
        # TEST mode counts as delivered: nothing leaves the building, and the
        # code is in the server log for whoever is setting the channel up.
        sms_went = message.status in (Message.Status.SENT, Message.Status.TEST)
        if message.status == Message.Status.TEST:
            import logging
            logging.getLogger(__name__).warning(
                "SMS test mode - sign-in code for %s is %s", user.get_username(), code)
        if sms_went:
            roads.append(f"SMS to {services.mask(number)}")

    if user.is_admin:
        to = [user.email] if user.email else _owner_emails()
        if _email(to, f"{shop_name} sign-in code",
                  f"Your sign-in code is {code}.\n\nIt expires in 5 minutes. If you "
                  f"did not just try to sign in, change your password now - "
                  f"somebody has it.\n\n- Your shop system"):
            roads.append("email")
        if not roads:
            raise Refused("The sign-in code could not be sent by SMS or email. "
                          "Call CampusNect on +256 708 646603.")
    elif not sms_went:
        if _email(_owner_emails(), f"{shop_name}: {user.display_name} is signing in",
                  f"{user.display_name} is signing in to a till and the code could not "
                  f"be sent to their phone (the SMS credit may be used up).\n\n"
                  f"If you agree, give them this code: {code}\n\n"
                  f"It expires in 5 minutes. Top up the SMS credit under SMS in the "
                  f"system so codes reach cashiers directly again.\n\n- Your shop system"):
            row.via_owner = True
            roads.append("the owner's email")
        else:
            raise Refused("The sign-in code could not be sent to your phone and the "
                          "owner could not be reached. Ask the owner to top up the "
                          "SMS credit.")

    row.sent_to = " and ".join(roads)
    row.save(update_fields=["sent_to", "via_owner"])
    return row
