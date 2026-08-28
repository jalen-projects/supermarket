from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied


def admin_required(view_func):
    """Cashiers may sell. Only the owner/manager may see cost prices, edit
    products, receive deliveries, manage users or open the reports.
    """

    def check(user):
        if not user.is_authenticated:
            return False
        if not user.is_admin:
            raise PermissionDenied(
                "Only an administrator can open this page. Ask the manager to sign in.")
        return True

    return user_passes_test(check)(view_func)
