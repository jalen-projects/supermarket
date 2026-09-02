from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as serve_media

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("shop.urls")),
    path("inventory/", include("inventory.urls")),
    path("sales/", include("sales.urls")),
    path("reports/", include("reports.urls")),
]

# The shop's logo is an upload, so it lives in media/ rather than static/ and
# whitenoise will not touch it. django.conf.urls.static.static() is no help
# here: it quietly returns nothing once DEBUG is off, which is exactly how the
# shop runs, so the logo would 404 on the till and on the printed receipt.
# One explicit route, deliberately, in both modes - it is a handful of small
# files on a single-shop server.
_media_prefix = settings.MEDIA_URL.lstrip("/")
urlpatterns += [
    re_path(rf"^{_media_prefix}(?P<path>.*)$", serve_media,
            {"document_root": settings.MEDIA_ROOT}),
]
