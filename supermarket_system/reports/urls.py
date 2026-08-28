from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="reports"),
    path("sales/", views.sales_report, name="report_sales"),
    path("profit/", views.profit_report, name="report_profit"),
    path("stock/", views.stock_report, name="report_stock"),
    path("expiry/", views.expiry_report, name="report_expiry"),
    path("top-products/", views.top_products, name="report_top_products"),
    path("export/<str:kind>/", views.export_csv, name="report_export"),
]
