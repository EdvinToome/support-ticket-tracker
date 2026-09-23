from storages.backends.s3 import S3Storage


class AttachmentStorage(S3Storage):
    """Request download disposition explicitly when signing private S3 URLs."""

    def url(self, name, parameters=None, expire=None, http_method=None):
        parameters = dict(parameters or {})
        parameters["ResponseContentDisposition"] = "attachment"
        return super().url(name, parameters=parameters, expire=expire, http_method=http_method)
