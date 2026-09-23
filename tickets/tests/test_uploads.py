from io import BytesIO

import pytest
from django.core.exceptions import RequestDataTooBig, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from PIL import Image

from tickets.upload_handlers import (
    MAX_FILE_BYTES,
    MAX_REQUEST_BYTES,
    BoundedMemoryUploadHandler,
    UploadLimitMiddleware,
)
from tickets.validators import attachment_path, validate_attachment


def image_bytes(image_format):
    image = Image.new("RGB", (2, 2), "red")
    output = BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("report.pdf", b"%PDF-1.7\n1 0 obj\n"),
        ("picture.png", image_bytes("PNG")),
        ("photo.jpg", image_bytes("JPEG")),
        ("photo.jpeg", image_bytes("JPEG")),
    ],
)
def test_supported_attachment_content(filename, content):
    upload = SimpleUploadedFile(filename, content, content_type="application/octet-stream")
    validate_attachment(upload)
    assert upload.tell() == 0


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("script.exe", b"%PDF-1.7\n"),
        ("fake.pdf", b"not a PDF"),
        ("fake.png", image_bytes("JPEG")),
        ("broken.jpg", b"not an image"),
    ],
)
def test_rejects_unsupported_or_misleading_content(filename, content):
    with pytest.raises(ValidationError):
        validate_attachment(SimpleUploadedFile(filename, content))


def test_rejects_file_over_five_mebibytes():
    upload = SimpleUploadedFile("large.pdf", b"%PDF-1.7\n" + b"x" * MAX_FILE_BYTES)
    with pytest.raises(ValidationError, match="5 MiB"):
        validate_attachment(upload)


def test_storage_path_uses_generated_name():
    first = attachment_path(None, "secret customer statement.PDF")
    second = attachment_path(None, "secret customer statement.PDF")
    assert first != second
    assert first.startswith("attachments/")
    assert first.endswith(".pdf")
    assert "secret" not in first


def test_handler_rejects_declared_request_over_ten_mebibytes():
    handler = BoundedMemoryUploadHandler()
    with pytest.raises(RequestDataTooBig, match="10 MiB"):
        handler.handle_raw_input(None, {}, MAX_REQUEST_BYTES + 1, b"boundary")


def test_handler_rejects_streamed_file_over_five_mebibytes():
    handler = BoundedMemoryUploadHandler()
    handler.new_file("attachment", "large.pdf", "application/pdf", None, None, None)
    with pytest.raises(RequestDataTooBig, match="5 MiB"):
        handler.receive_data_chunk(b"x" * (MAX_FILE_BYTES + 1), 0)


def test_handler_rejects_aggregate_stream_over_ten_mebibytes():
    handler = BoundedMemoryUploadHandler()
    for index in range(3):
        handler.new_file("attachment", f"part{index}.pdf", "application/pdf", None, None, None)
        if index < 2:
            handler.receive_data_chunk(b"x" * (4 * 1024 * 1024), 0)
            handler.file_complete(4 * 1024 * 1024)
        else:
            with pytest.raises(RequestDataTooBig, match="10 MiB"):
                handler.receive_data_chunk(b"x" * (3 * 1024 * 1024), 0)


@override_settings(FILE_UPLOAD_HANDLERS=["tickets.upload_handlers.BoundedMemoryUploadHandler"])
def test_oversized_multipart_request_gets_readable_413():
    request = RequestFactory().post(
        "/upload/",
        {"attachment": SimpleUploadedFile("large.pdf", b"%PDF-1.7\n" + b"x" * MAX_REQUEST_BYTES)},
    )
    response = UploadLimitMiddleware(lambda request: HttpResponse("accepted"))(request)
    assert response.status_code == 413
    assert b"10 MiB" in response.content
