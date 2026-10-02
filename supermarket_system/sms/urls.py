from django.urls import path

from . import views

urlpatterns = [
    path("sign-in/code/", views.code_step, name="sms_code"),
    path("sms/", views.home, name="sms_home"),
    path("sms/buy/", views.buy, name="sms_buy"),
    path("sms/paid/", views.paid, name="sms_paid"),
    path("sms/send/", views.compose, name="sms_compose"),
    path("sms/sent/<int:pk>/", views.broadcast_detail, name="sms_broadcast"),
]
