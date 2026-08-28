from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import ShopSettings, User


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
        exclude = ["updated_at"]


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
