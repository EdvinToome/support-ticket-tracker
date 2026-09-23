from io import BytesIO

from django.core.exceptions import RequestDataTooBig
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.files.uploadhandler import FileUploadHandler
from django.http import HttpResponse

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = 10 * 1024 * 1024


class UploadLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.content_type == "multipart/form-data":
            try:
                request.POST
            except RequestDataTooBig as error:
                return HttpResponse(str(error), status=413, content_type="text/plain")
        return self.get_response(request)


class BoundedMemoryUploadHandler(FileUploadHandler):
    """Keep accepted uploads in memory and reject excess before writing a chunk."""

    chunk_size = 64 * 1024

    def __init__(self, request=None):
        super().__init__(request)
        self.request_file_bytes = 0
        self.current_file_bytes = 0

    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        if content_length is not None and content_length > MAX_REQUEST_BYTES:
            raise RequestDataTooBig("The total upload request must be 10 MiB or smaller.")

    def new_file(
        self, field_name, file_name, content_type, content_length, charset, content_type_extra=None
    ):
        super().new_file(
            field_name, file_name, content_type, content_length, charset, content_type_extra
        )
        if content_length is not None and content_length > MAX_FILE_BYTES:
            raise RequestDataTooBig("Each attachment must be 5 MiB or smaller.")
        self.current_file_bytes = 0
        self.buffer = BytesIO()

    def receive_data_chunk(self, raw_data, start):
        file_bytes = self.current_file_bytes + len(raw_data)
        request_bytes = self.request_file_bytes + len(raw_data)
        if file_bytes > MAX_FILE_BYTES:
            raise RequestDataTooBig("Each attachment must be 5 MiB or smaller.")
        if request_bytes > MAX_REQUEST_BYTES:
            raise RequestDataTooBig("The total upload request must be 10 MiB or smaller.")
        self.current_file_bytes = file_bytes
        self.request_file_bytes = request_bytes
        self.buffer.write(raw_data)

    def file_complete(self, file_size):
        self.buffer.seek(0)
        return InMemoryUploadedFile(
            self.buffer,
            self.field_name,
            self.file_name,
            self.content_type,
            self.current_file_bytes,
            self.charset,
            self.content_type_extra,
        )
