import sys

from django.db import OperationalError, connection
from django.http import HttpResponse


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError:
        return HttpResponse("temporarily unavailable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")


def server_error(request):
    database_down = isinstance(sys.exception(), OperationalError)
    title = "Temporarily unavailable" if database_down else "Something went wrong"
    return HttpResponse(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title><body><h1>{title}</h1>"
        "<p>Please retry shortly.</p></body></html>",
        status=503 if database_down else 500,
    )
