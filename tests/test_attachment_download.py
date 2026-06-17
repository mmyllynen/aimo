from __future__ import annotations

import unittest

from adapters.discord.attachments import (
    AttachmentTooLargeError,
    UnsupportedAttachmentDownloadError,
    hydrate_attachment_content,
)
from core.events import AttachmentRef, CanonicalEvent, EventKind, EventSource


class FakeHeaders(dict):
    def get_content_type(self) -> str:
        return str(self.get("Content-Type", "")).split(";", 1)[0]


class FakeResponse:
    def __init__(self, content: bytes, headers: dict[str, str] | None = None) -> None:
        self.content = content
        self.headers = FakeHeaders(headers or {})
        self.read_sizes: list[int] = []

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self.content if size < 0 else self.content[:size]


class FakeOpener:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests = []
        self.timeouts = []

    def __call__(self, request, *, timeout: float):
        self.requests.append(request)
        self.timeouts.append(timeout)
        return self.response


class AttachmentDownloadTests(unittest.TestCase):
    def test_hydrates_supported_gpx_attachment_content(self) -> None:
        response = FakeResponse(b"<gpx></gpx>", {"Content-Type": "application/gpx+xml", "Content-Length": "11"})
        opener = FakeOpener(response)

        hydrated = hydrate_attachment_content(
            _event(_attachment(size_bytes=11)),
            max_size_bytes=100,
            opener=opener,
            timeout_s=5,
        )

        self.assertEqual(hydrated.attachments[0].metadata["content"], b"<gpx></gpx>")
        self.assertEqual(hydrated.attachments[0].metadata["downloaded_content_type"], "application/gpx+xml")
        self.assertEqual(opener.requests[0].full_url, "https://example.test/run.gpx")
        self.assertEqual(opener.timeouts, [5])
        self.assertEqual(response.read_sizes, [101])

    def test_skips_unsupported_attachment_without_download(self) -> None:
        opener = FakeOpener(FakeResponse(b"ignored"))

        hydrated = hydrate_attachment_content(
            _event(_attachment(filename="notes.txt", content_type="text/plain")),
            max_size_bytes=100,
            opener=opener,
        )

        self.assertEqual(hydrated.attachments[0].metadata, {})
        self.assertEqual(opener.requests, [])

    def test_hydrates_supported_image_attachment_content(self) -> None:
        response = FakeResponse(b"image-bytes", {"Content-Type": "image/png", "Content-Length": "11"})
        opener = FakeOpener(response)

        hydrated = hydrate_attachment_content(
            _event(_attachment(filename="photo.png", content_type="image/png", url="https://example.test/photo.png")),
            max_size_bytes=100,
            opener=opener,
        )

        self.assertEqual(hydrated.attachments[0].metadata["content"], b"image-bytes")
        self.assertEqual(hydrated.attachments[0].metadata["downloaded_content_type"], "image/png")

    def test_rejects_declared_size_over_limit_before_download(self) -> None:
        opener = FakeOpener(FakeResponse(b"ignored"))

        with self.assertRaises(AttachmentTooLargeError):
            hydrate_attachment_content(_event(_attachment(size_bytes=101)), max_size_bytes=100, opener=opener)

        self.assertEqual(opener.requests, [])

    def test_rejects_stream_that_exceeds_limit(self) -> None:
        opener = FakeOpener(FakeResponse(b"x" * 101, {"Content-Type": "application/gpx+xml"}))

        with self.assertRaises(AttachmentTooLargeError):
            hydrate_attachment_content(_event(_attachment(size_bytes=None)), max_size_bytes=100, opener=opener)

    def test_rejects_supported_attachment_without_url(self) -> None:
        with self.assertRaises(UnsupportedAttachmentDownloadError):
            hydrate_attachment_content(
                _event(_attachment(url="")),
                max_size_bytes=100,
                opener=FakeOpener(FakeResponse(b"ignored")),
            )

    def test_preserves_existing_content_without_download(self) -> None:
        opener = FakeOpener(FakeResponse(b"ignored"))
        attachment = _attachment(metadata={"content": b"already"})

        hydrated = hydrate_attachment_content(_event(attachment), max_size_bytes=100, opener=opener)

        self.assertEqual(hydrated.attachments[0].metadata["content"], b"already")
        self.assertEqual(opener.requests, [])


def _event(attachment: AttachmentRef) -> CanonicalEvent:
    return CanonicalEvent(
        event_id="event-1",
        source=EventSource.DISCORD_MESSAGE,
        kind=EventKind.MENTION,
        guild_id="guild-1",
        channel_id="channel-1",
        user_id="user-1",
        user_name="runner",
        text="tallenna",
        attachments=(attachment,),
    )


def _attachment(
    *,
    filename: str = "run.gpx",
    content_type: str = "application/gpx+xml",
    size_bytes: int | None = 10,
    url: str = "https://example.test/run.gpx",
    metadata: dict[str, object] | None = None,
) -> AttachmentRef:
    return AttachmentRef(
        attachment_id="attachment-1",
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        url=url,
        metadata=metadata or {},
    )


if __name__ == "__main__":
    unittest.main()
