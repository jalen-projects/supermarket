from django.contrib import admin

from .models import (Category, Product, Purchase, PurchaseItem, StockBatch,
                     StockMovement, Supplier, Unit)


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "barcode", "category", "unit", "buying_price",
                    "selling_price", "is_active"]
    list_filter = ["category", "is_active"]
    search_fields = ["name", "barcode"]


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ["reference", "date", "supplier", "status", "received_by"]
    list_filter = ["status", "supplier"]
    inlines = [PurchaseItemInline]


@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    list_display = ["product", "quantity_remaining", "expiry_date", "buying_price", "received_on"]
    list_filter = ["expiry_date"]
    search_fields = ["product__name"]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ["created_at", "product", "kind", "quantity", "reference", "user"]
    list_filter = ["kind"]
    search_fields = ["product__name", "reference"]


admin.site.register([Category, Unit, Supplier])
