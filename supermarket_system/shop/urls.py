from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),

    path("settings/", views.shop_settings_view, name="shop_settings"),
    path("help/", views.help_page, name="help"),
    path("tour/", views.tour_state, name="tour_state"),
    path("network/", views.network, name="network"),

    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/password/", views.user_password, name="user_password"),

    path("till/check-in/", views.till_check_in, name="till_check_in"),
    path("owner/", views.owner_view, name="owner"),
    path("audit/", views.audit_list, name="audit"),

    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("offline/", views.offline_page, name="offline"),

    path("backup/", views.backup, name="backup"),
    path("backup/<str:name>/", views.backup_download, name="backup_download"),
]
