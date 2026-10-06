from django.conf import settings

from . import brand
from .models import ShopSettings

#: The hosting reminder appears this many days before the year runs out.
HOSTING_NOTICE_DAYS = 30


def shop_settings(request):
    """Makes the company name, logo and currency available on every page -
    including the printed receipt.
    """
    settings_obj = ShopSettings.get()
    online = getattr(settings, "ONLINE", False)
    ctx = {"shop": settings_obj, "currency": settings_obj.currency, "online": online,
           # The drawn half of the shop's identity - see shop/brand.py.
           "brand": brand.current(),
           "demo": getattr(settings, "DEMO", False)}

    # The yearly hosting reminder. Online only - the shop's own computer is
    # not hosted by anybody - and only for the owner, who is the one paying.
    user = getattr(request, "user", None)
    days = settings_obj.hosting_days_left
    if (online and days is not None and days <= HOSTING_NOTICE_DAYS
            and user is not None and user.is_authenticated and user.is_admin):
        ctx["hosting_days_left"] = days
    return ctx
