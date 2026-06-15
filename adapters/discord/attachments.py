from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.events import AttachmentRef, CanonicalEvent
from workout.ingest import is_supported_gpx_attachment


UrlOpener = Callable[..., Any]


class AttachmentDownloadError(RuntimeError):
    pass


class AttachmentTooLargeError(AttachmentDownloadError):
    pass


class UnsupportedAttachmentDownloadError(AttachmentDownloadError):
    pass


def hydrate_attachment_content(
    event: CanonicalEvent,
    *,
    max_size_bytes: int,
    opener: UrlOpener = urlopen,
    timeout_s: float = 30.0,
) -> CanonicalEvent:
    if max_size_bytes <= 0:
        raise ValueError("max_size_bytes must be positive")
    hydrated = tuple(
        _hydrate_attachment(
            attachment,
            max_size_bytes=max_size_bytes,
            opener=opener,
            timeout_s=timeout_s,
        )
        for attachment in event.attachments
    )
    return replace(event, attachments=hydrated)


def _hydrate_attachment(
    attachment: AttachmentRef,
    *,
    max_size_bytes: int,
    opener: UrlOpener,
    timeout_s: float,
) -> AttachmentRef:
    if "content" in attachment.metadata:
        return attachment
    if not is_supported_gpx_attachment(attachment.filename, attachment.content_type):
        return attachment
    if attachment.size_bytes is not None and attachment.size_bytes > max_size_bytes:
        raise AttachmentTooLargeError(f"Attachment {attachment.attachment_id} exceeds configured size limit")
    if not attachment.url:
        raise UnsupportedAttachmentDownloadError(f"Attachment {attachment.attachment_id} has no download URL")

    http_request = Request(attachment.url, headers={"User-Agent": "Aimo/3 attachment downloader"})
    try:
        with opener(http_request, timeout=timeout_s) as response:
            content_type = _response_content_type(response) or attachment.content_type
            size = _response_content_length(response)
            if size is not None and size > max_size_bytes:
                raise AttachmentTooLargeError(f"Attachment {attachment.attachment_id} exceeds configured size limit")
            content = response.read(max_size_bytes + 1)
    except AttachmentDownloadError:
        raise
    except (HTTPError, URLError, OSError) as exc:
        raise AttachmentDownloadError(f"Could not download attachment {attachment.attachment_id}: {exc}") from exc

    if len(content) > max_size_bytes:
        raise AttachmentTooLargeError(f"Attachment {attachment.attachment_id} exceeds configured size limit")
    if not is_supported_gpx_attachment(attachment.filename, content_type):
        raise UnsupportedAttachmentDownloadError(f"Attachment {attachment.attachment_id} is not a supported GPX file")

    metadata = dict(attachment.metadata)
    metadata["content"] = content
    metadata["downloaded_content_type"] = content_type
    return replace(
        attachment,
        content_type=attachment.content_type or content_type,
        size_bytes=attachment.size_bytes if attachment.size_bytes is not None else len(content),
        metadata=metadata,
    )


def _response_content_type(response: Any) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    if hasattr(headers, "get_content_type"):
        return str(headers.get_content_type())
    value = headers.get("Content-Type", "") if hasattr(headers, "get") else ""
    return str(value).split(";", 1)[0].strip().lower()


def _response_content_length(response: Any) -> int | None:
    headers = getattr(response, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return None
    value = headers.get("Content-Length")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
