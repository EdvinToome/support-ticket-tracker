import struct
import zlib
from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.management.base import CommandError
from django.forms import modelform_factory
from PIL import Image

from tickets.models import Agent, Comment, Ticket
from tickets.tests.test_seed import seed
from tickets.validators import validate_attachment


@pytest.mark.django_db
@pytest.mark.parametrize("data", [{}, {"user": "999999999"}])
def test_invalid_agent_user_is_a_form_error(data):
    form = modelform_factory(Agent, fields=["user"])(data=data)
    assert not form.is_valid()
    assert "user" in form.errors


def test_oversized_image_dimensions_are_a_validation_error():
    image = BytesIO()
    Image.new("RGB", (1, 1)).save(image, format="PNG")
    data = bytearray(image.getvalue())
    data[16:24] = struct.pack(">II", 20000, 20000)
    data[29:33] = struct.pack(">I", zlib.crc32(data[12:29]))
    with pytest.raises(ValidationError, match="invalid"):
        validate_attachment(ContentFile(bytes(data), name="huge.png"))


@pytest.mark.django_db
def test_failed_reset_keeps_existing_rows_and_attachments():
    seed()
    ticket_ids = list(Ticket.objects.values_list("pk", flat=True))
    attachment = Comment.objects.exclude(attachment="").first().attachment
    with pytest.raises(CommandError, match="resolved ticket"):
        seed(reset=True, tickets=100, comments=0, attachments=0)
    assert list(Ticket.objects.values_list("pk", flat=True)) == ticket_ids
    assert attachment.storage.exists(attachment.name)
