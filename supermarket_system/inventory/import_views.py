"""Uploading a shop's existing product list.

Kept in its own module because the import is a two-step conversation - check
first, then commit - and mixing that into the ordinary product views would
bury it.

Between the two steps the uploaded file is held on disk under a random name
rather than in the session. A supermarket list runs to thousands of rows, and
pushing that through the session means writing the whole spreadsheet into the
database on every page view.
"""
import secrets

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render

from shop.permissions import admin_required

from . import importer

UPLOAD_DIR = settings.BASE_DIR / "imports"
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def _token_path(token):
    """Resolve a token to its file, refusing anything that is not a plain name.

    The token comes back from the browser, so it is treated as hostile: without
    this check a crafted token could walk out of the folder and read any file
    on the shop's computer.
    """
    if not token or not token.isalnum():
        raise Http404("No such upload.")
    path = (UPLOAD_DIR / f"{token}.csv").resolve()
    if path.parent != UPLOAD_DIR.resolve() or not path.exists():
        raise Http404("That upload has expired. Please choose the file again.")
    return path


@admin_required
def product_import(request):
    """Step one: take the file, read it, and show what would happen."""
    if request.method != "POST":
        return render(request, "inventory/product_import.html", {})

    upload = request.FILES.get("file")
    if upload is None:
        messages.error(request, "Choose a file first.")
        return redirect("product_import")
    if upload.size > MAX_UPLOAD_BYTES:
        messages.error(request, "That file is too big. Split it into a few smaller ones.")
        return redirect("product_import")

    raw = upload.read()
    try:
        records, columns = importer.read_rows(raw)
    except importer.ImportProblem as exc:
        messages.error(request, str(exc))
        return redirect("product_import")

    add_stock = bool(request.POST.get("add_stock_to_existing"))
    plans = importer.plan(records, add_stock_to_existing=add_stock)

    UPLOAD_DIR.mkdir(exist_ok=True)
    token = secrets.token_hex(16)
    (UPLOAD_DIR / f"{token}.csv").write_bytes(raw)

    return render(request, "inventory/product_import.html", {
        "plans": plans,
        "columns": columns,
        "token": token,
        "add_stock": add_stock,
        "filename": upload.name,
        "total": len(plans),
        "good": [p for p in plans if p.ok],
        "bad": [p for p in plans if not p.ok],
        "warned": [p for p in plans if p.ok and p.warnings],
        "creating": [p for p in plans if p.ok and p.action == "create"],
        "updating": [p for p in plans if p.ok and p.action == "update"],
    })


@admin_required
def product_import_confirm(request):
    """Step two: write it. Only reachable by POST from the preview."""
    if request.method != "POST":
        return redirect("product_import")

    path = _token_path(request.POST.get("token", ""))
    add_stock = bool(request.POST.get("add_stock_to_existing"))

    try:
        records, _ = importer.read_rows(path.read_bytes())
        plans = importer.plan(records, add_stock_to_existing=add_stock)
        result = importer.apply_plan(plans, user=request.user,
                                     add_stock_to_existing=add_stock)
    except importer.ImportProblem as exc:
        messages.error(request, str(exc))
        return redirect("product_import")
    finally:
        path.unlink(missing_ok=True)

    messages.success(
        request,
        f"Imported: {result['created']} new product(s), "
        f"{result['updated']} updated, opening stock added for {result['stocked']}."
        + (f" {result['skipped']} row(s) had errors and were left out."
           if result["skipped"] else ""))
    return redirect("product_list")


@admin_required
def product_import_template(request):
    """The blank stock entry sheet: an Excel workbook built so that Excel cannot
    damage it - barcodes stored as text, expiry only accepting real dates,
    numbers only accepting numbers, drop-downs for category and unit, and an
    instructions tab. The CSV template stays available with ?format=csv for
    anyone without Excel."""
    from django.conf import settings
    from django.http import FileResponse
    sheet = settings.BASE_DIR / "static" / "sheets" / "stock-entry-sheet.xlsx"
    if request.GET.get("format") == "csv" or not sheet.exists():
        response = HttpResponse(importer.template_csv(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="product list template.csv"'
        return response
    return FileResponse(
        open(sheet, "rb"), as_attachment=True, filename="stock entry sheet.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
