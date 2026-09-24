from django.core.exceptions import RequestDataTooBig
from django.core.files.uploadhandler import MemoryFileUploadHandler


class BoundedMemoryUploadHandler(MemoryFileUploadHandler):
    """Keep uploads in memory and refuse requests too large to hold there.

    Django's default handlers spool large files to a temporary file on local disk. This
    handler caps a request at FILE_UPLOAD_MAX_MEMORY_SIZE instead; the attachment
    validator reports per-file size and type problems as form errors.
    """

    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        super().handle_raw_input(input_data, META, content_length, boundary, encoding)
        if not self.activated:
            raise RequestDataTooBig("Upload requests must be 10 MiB or smaller.")
