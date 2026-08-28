from .models import ShopSettings


def shop_settings(request):
    """Makes the company name, logo and currency available on every page -
    including the printed receipt.
    """
    settings_obj = ShopSettings.get()
    return {"shop": settings_obj, "currency": settings_obj.currency}
