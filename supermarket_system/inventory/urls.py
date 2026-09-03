from django.urls import path

from . import views

urlpatterns = [
    # Products
    path("products/", views.product_list, name="product_list"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("products/<int:pk>/restore/", views.product_restore, name="product_restore"),
    path("products/<int:pk>/adjust/", views.product_adjust, name="product_adjust"),
    path("lookup/", views.product_lookup, name="product_lookup"),

    # Reference data
    path("categories/", views.category_list, name="category_list"),
    path("categories/<int:pk>/edit/", views.category_edit, name="category_edit"),
    path("units/", views.unit_list, name="unit_list"),
    path("suppliers/", views.supplier_list, name="supplier_list"),
    path("suppliers/new/", views.supplier_create, name="supplier_create"),
    path("suppliers/<int:pk>/edit/", views.supplier_edit, name="supplier_edit"),

    # Purchases
    path("purchases/", views.purchase_list, name="purchase_list"),
    path("purchases/new/", views.purchase_create, name="purchase_create"),
    path("purchases/<int:pk>/", views.purchase_detail, name="purchase_detail"),
    path("purchases/<int:pk>/receive/", views.purchase_receive, name="purchase_receive"),
    path("purchases/<int:pk>/delete/", views.purchase_delete, name="purchase_delete"),

    # Stock
    path("stock/", views.stock_list, name="stock_list"),
    path("stock/take/", views.stock_take, name="stock_take"),
    path("stock/counts/", views.stock_count_list, name="stock_count_list"),
    path("stock/counts/<int:pk>/", views.stock_count_detail, name="stock_count_detail"),
    path("expiry/", views.expiry_list, name="expiry_list"),
    path("batches/<int:pk>/write-off/", views.batch_write_off, name="batch_write_off"),
    path("movements/", views.movement_list, name="movement_list"),
]
