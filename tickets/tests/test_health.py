from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.test import RequestFactory

from config.views import healthz, server_error


@pytest.mark.django_db
def test_healthz_reports_database_availability():
    request = RequestFactory().get("/healthz")
    assert healthz(request).status_code == 200
    with patch("config.views.connection.cursor", side_effect=OperationalError):
        assert healthz(request).status_code == 503


@pytest.mark.parametrize(("error", "status"), [(OperationalError, 503), (ValueError, 500)])
def test_error_page_distinguishes_database_outages(error, status):
    try:
        raise error("boom")
    except error:
        response = server_error(RequestFactory().get("/"))
    assert response.status_code == status
    assert b"boom" not in response.content
