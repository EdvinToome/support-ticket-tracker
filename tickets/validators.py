from pathlib import Path
from uuid import uuid4

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

MAX_FILE_BYTES = 5 * 1024 * 1024
IMAGE_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}
ALLOWED_EXTENSIONS = {".pdf", *IMAGE_FORMATS}


def attachment_path(instance, filename: str) -> str:
    extension = Path(filename).suffix.lower()
    return f"attachments/{uuid4().hex}{extension}"


def validate_attachment(value) -> None:
    extension = Path(value.name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError("Attach a PDF, PNG, or JPEG file.")
    if value.size > MAX_FILE_BYTES:
        raise ValidationError("Attachments must be 5 MiB or smaller.")

    position = value.tell()
    try:
        value.seek(0)
        if extension == ".pdf":
            if not value.read(5) == b"%PDF-":
                raise ValidationError("This file does not have a valid PDF header.")
        else:
            try:
                with Image.open(value) as image:
                    if image.format != IMAGE_FORMATS[extension]:
                        raise ValidationError(
                            "The image content does not match its file extension."
                        )
                    image.verify()
            except (UnidentifiedImageError, OSError, SyntaxError) as error:
                raise ValidationError("This image file is invalid.") from error
    finally:
        value.seek(position)
