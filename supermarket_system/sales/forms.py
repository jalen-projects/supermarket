from django import forms

from shop.forms import BootstrapMixin

from .models import Customer


class CustomerForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "address", "notes", "is_active"]


class OpenDrawerForm(BootstrapMixin, forms.Form):
    """Declaring the change money handed to a cashier at the start of a shift."""

    opening_float = forms.DecimalField(
        label="Change money in the drawer now", min_value=0, max_digits=12,
        decimal_places=2, initial=0,
        help_text="What the owner handed over to give change with. Enter 0 if none.")


class CashUpForm(BootstrapMixin, forms.Form):
    """Counting the drawer at handover.

    Only the counted total is asked for. The system must not show the cashier
    what it expects before they count - a cashier who can see the target will
    write the target down, and the whole control is worth nothing.
    """

    counted_cash = forms.DecimalField(
        label="Total cash counted in the drawer", min_value=0, max_digits=12,
        decimal_places=2,
        help_text="Count the notes and coins and type the total. Include the change money.")
    note = forms.CharField(
        label="Note (optional)", required=False, max_length=200,
        widget=forms.TextInput(attrs={
            "placeholder": "e.g. paid 20,000 to the boda for a delivery"}),
        help_text="Explain anything unusual, especially money taken out of the drawer.")
