from django.apps import AppConfig


class ShopConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shop"
    verbose_name = "Shop & users"

    def ready(self):
        from . import audit  # noqa: F401  connects the sign-in signals
