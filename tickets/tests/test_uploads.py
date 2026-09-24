import struct
import zlib
from io import BytesIO

import pytest
from django.core.exceptions import RequestDataTooBig, ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile, SimpleUploadedFile
from django.test import RequestFactory
from PIL import Image

from tickets.validators import MAX_FILE_BYTES, attachment_path, validate_attachment

MIB = 1024 * 1024


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


def test_image_with_bomb_dimensions_is_a_validation_error():
    image = BytesIO()
    Image.new("RGB", (1, 1)).save(image, format="PNG")
    data = bytearray(image.getvalue())
    data[16:24] = struct.pack(">II", 20000, 20000)
    data[29:33] = struct.pack(">I", zlib.crc32(data[12:29]))
    with pytest.raises(ValidationError, match="invalid"):
        validate_attachment(ContentFile(bytes(data), name="huge.png"))


def test_storage_path_uses_generated_name():
    first = attachment_path(None, "secret customer statement.PDF")
    second = attachment_path(None, "secret customer statement.PDF")
    assert first != second
    assert first.startswith("attachments/")
    assert first.endswith(".pdf")
    assert "secret" not in first


def upload_request(size):
    return RequestFactory().post("/", {"attachment": SimpleUploadedFile("a.pdf", b"x" * size)})


def test_uploads_stay_in_memory_until_the_request_limit():
    # A 6 MiB file is buffered in memory so the validator can report it as a form error.
    assert isinstance(upload_request(6 * MIB).FILES["attachment"], InMemoryUploadedFile)
    with pytest.raises(RequestDataTooBig, match="10 MiB"):
        upload_request(10 * MIB).POST
