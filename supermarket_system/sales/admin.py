from django.contrib import admin

from .models import Customer, Sale, SaleItem


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ["receipt_no", "created_at", "served_by", "customer", "total", "status"]
    list_filter = ["status", "payment_method", "served_by"]
    search_fields = ["receipt_no"]
    inlines = [SaleItemInline]


admin.site.register(Customer)
