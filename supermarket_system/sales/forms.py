from django import forms

from shop.forms import BootstrapMixin

from .models import Customer


class CustomerForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "address", "notes", "is_active"]
