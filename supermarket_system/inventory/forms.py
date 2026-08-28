from django import forms
from django.forms import inlineformset_factory

from shop.forms import BootstrapMixin

from .models import Category, Product, Purchase, PurchaseItem, StockMovement, Supplier, Unit


class ProductForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "barcode", "category", "unit", "buying_price",
                  "selling_price", "reorder_level", "is_active"]
        widgets = {
            "barcode": forms.TextInput(attrs={"placeholder": "Scan the item or type the number"}),
        }

    def clean_barcode(self):
        # An empty barcode must be NULL, not "", or the second blank one
        # would collide with the unique index.
        return self.cleaned_data.get("barcode") or None

    def clean(self):
        data = super().clean()
        buying, selling = data.get("buying_price"), data.get("selling_price")
        if buying is not None and selling is not None and selling < buying:
            self.add_error("selling_price",
                           "The selling price is below the buying price - this item would "
                           "lose money on every sale. Change it, or confirm it is deliberate.")
        return data


class CategoryForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "description"]


class UnitForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Unit
        fields = ["name", "abbreviation", "allow_decimals"]


class SupplierForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_person", "phone", "email", "address", "notes", "is_active"]


class PurchaseForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ["supplier", "invoice_no", "date", "notes"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class PurchaseItemForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = PurchaseItem
        fields = ["product", "quantity", "buying_price", "selling_price", "expiry_date"]
        widgets = {"expiry_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.active().select_related("unit")


PurchaseItemFormSet = inlineformset_factory(
    Purchase, PurchaseItem, form=PurchaseItemForm, extra=5, can_delete=True)


class StockAdjustmentForm(BootstrapMixin, forms.Form):
    KIND_CHOICES = [
        (StockMovement.Kind.OPENING, "Opening stock (first time counting)"),
        (StockMovement.Kind.ADJUST, "Correction after a physical count"),
        (StockMovement.Kind.WRITE_OFF, "Write off - damaged, expired or stolen"),
    ]
    quantity = forms.DecimalField(
        max_digits=12, decimal_places=3,
        help_text="Use a minus sign to take stock out, e.g. -3")
    kind = forms.ChoiceField(choices=KIND_CHOICES)
    reason = forms.CharField(max_length=200,
                             help_text="Say why. This is what the owner reads later.")
