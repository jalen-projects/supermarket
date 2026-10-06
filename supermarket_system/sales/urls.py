from django.urls import path

from . import views

urlpatterns = [
    path("", views.pos, name="pos"),
    path("checkout/", views.pos_checkout, name="pos_checkout"),
    path("held/", views.held_sales, name="held_sales"),
    path("held/<int:pk>/recall/", views.held_recall, name="held_recall"),
    path("held/<int:pk>/discard/", views.held_discard, name="held_discard"),

    path("list/", views.sale_list, name="sale_list"),
    path("day/", views.day_summary, name="day_summary"),
    path("cashup/", views.cash_up, name="cash_up"),
    path("shifts/", views.shift_list, name="shift_list"),
    path("shifts/<int:pk>/", views.shift_detail, name="shift_detail"),
    path("<int:pk>/", views.sale_detail, name="sale_detail"),
    path("<int:pk>/receipt/", views.receipt, name="receipt"),
    path("<int:pk>/void/", views.sale_void, name="sale_void"),

    path("customers/", views.customer_list, name="customer_list"),
    path("customers/new/", views.customer_create, name="customer_create"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("customers/<int:pk>/edit/", views.customer_edit, name="customer_edit"),
]
