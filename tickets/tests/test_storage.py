from urllib.parse import parse_qs, urlparse

from tickets.storage import AttachmentStorage


def test_signed_download_forces_attachment_and_expires():
    storage = AttachmentStorage(
        access_key="test-key",
        secret_key="test-secret",
        bucket_name="attachments",
        endpoint_url="http://127.0.0.1:59000",
        region_name="us-east-1",
        signature_version="s3v4",
        addressing_style="path",
        querystring_expire=300,
    )
    url = storage.url("sample.pdf", parameters={"ResponseContentDisposition": "inline"})
    query = parse_qs(urlparse(url).query)
    assert query["response-content-disposition"] == ["attachment"]
    assert query["X-Amz-Expires"] == ["300"]
    assert query["X-Amz-Signature"]
