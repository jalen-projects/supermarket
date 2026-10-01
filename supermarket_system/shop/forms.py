from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils import timezone

from .models import AuditEvent, ShopSettings, User

#: Online, this many wrong passwords for one username inside the window
#: closes that username for the rest of the window...
MAX_FAILURES_PER_NAME = 5
#: ...and this many from one address closes that address, whatever names it tries.
MAX_FAILURES_PER_ADDRESS = 30
FAILURE_WINDOW = timedelta(minutes=15)


class GuardedAuthenticationForm(AuthenticationForm):
    """The sign-in form, with a lock on it once the shop is on the internet.

    Offline, the only people who can reach the sign-in screen are standing in
    the shop. Online, anybody can - and a four-character password falls to a
    guessing script in minutes. Counting the failures already written to the
    audit trail means the lock survives a restart and needs no new table.
    """

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": ("That username and password do not match. Check the caps "
                          "lock key and try again."),
        "locked": ("Too many wrong passwords. Sign-in is paused for 15 minutes - "
                   "ask the owner if you have forgotten yours."),
    }

    def clean(self):
        if getattr(settings, "ONLINE", False):
            from .audit import client_ip
            since = timezone.now() - FAILURE_WINDOW
            failures = AuditEvent.objects.filter(
                action=AuditEvent.Action.SIGN_IN_FAILED, at__gte=since)
            name = (self.data.get("username") or "")[:60]
            ip = client_ip(self.request)
            if (failures.filter(reference=name).count() >= MAX_FAILURES_PER_NAME
                    or (ip and failures.filter(ip_address=ip).count()
                        >= MAX_FAILURES_PER_ADDRESS)):
                raise forms.ValidationError(self.error_messages["locked"], code="locked")
        return super().clean()


class BootstrapMixin:
    """Every form field gets the same class so the CSS stays in one place."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput,)):
                widget.attrs.setdefault("class", "check")
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", "input select")
            else:
                widget.attrs.setdefault("class", "input")
            if isinstance(widget, forms.DateInput):
                widget.input_type = "date"


class ShopSettingsForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ShopSettings
        # hosting_paid_until is when the next hosting payment falls due -
        # CampusNect's record, set on the server, not a choice the shop makes.
        exclude = ["updated_at", "hosting_paid_until", "summary_sent_for"]
        widgets = {
            "opens_at": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "closes_at": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }


class UserForm(BootstrapMixin, UserCreationForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "phone", "role", "is_active"]


class UserEditForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "phone", "role", "is_active"]


class PasswordResetForm(BootstrapMixin, forms.Form):
    password1 = forms.CharField(label="New password", widget=forms.PasswordInput, min_length=4)
    password2 = forms.CharField(label="Repeat password", widget=forms.PasswordInput, min_length=4)

    def clean(self):
        data = super().clean()
        if data.get("password1") != data.get("password2"):
            raise forms.ValidationError("The two passwords do not match.")
        return data
