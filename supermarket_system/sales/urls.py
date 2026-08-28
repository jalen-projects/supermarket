from django.urls import path

from . import views

urlpatterns = [
    path("", views.pos, name="pos"),
    path("checkout/", views.pos_checkout, name="pos_checkout"),

    path("list/", views.sale_list, name="sale_list"),
    path("day/", views.day_summary, name="day_summary"),
    path("<int:pk>/", views.sale_detail, name="sale_detail"),
    path("<int:pk>/receipt/", views.receipt, name="receipt"),
    path("<int:pk>/void/", views.sale_void, name="sale_void"),

    path("customers/", views.customer_list, name="customer_list"),
    path("customers/new/", views.customer_create, name="customer_create"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("customers/<int:pk>/edit/", views.customer_edit, name="customer_edit"),
]
