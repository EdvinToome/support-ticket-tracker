from storages.backends.s3 import S3Storage


class AttachmentStorage(S3Storage):
    """Sign every download as an attachment so browsers never render uploads inline.

    Supabase ignores the stored ContentDisposition metadata, so it goes in the signed URL.
    """

    def url(self, name, parameters=None, expire=None, http_method=None):
        parameters = dict(parameters or {})
        parameters["ResponseContentDisposition"] = "attachment"
        return super().url(name, parameters=parameters, expire=expire, http_method=http_method)
