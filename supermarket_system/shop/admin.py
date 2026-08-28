from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ShopSettings, User


@admin.register(User)
class UserAdmin(UserAdmin):
    list_display = ["username", "first_name", "last_name", "role", "is_active"]
    list_filter = ["role", "is_active"]
    fieldsets = UserAdmin.fieldsets + (("Shop", {"fields": ("role", "phone")}),)


@admin.register(ShopSettings)
class ShopSettingsAdmin(admin.ModelAdmin):
    list_display = ["company_name", "phone", "currency", "updated_at"]
