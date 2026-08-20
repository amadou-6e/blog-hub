"""
Unit tests for backend.services.image_ingest.

No test makes a real network call. Safe-destination happy-path tests target
literal public IP addresses (which skip DNS) with an httpx.MockTransport
standing in for the network. DNS-based tests monkeypatch socket.getaddrinfo.
"""
from __future__ import annotations

import io
import socket

import httpx
import pytest
from PIL import Image

from backend.services.image_ingest import (
    ImageIngestReason,
    fetch_and_validate_image,
)

# A public, non-reserved IPv4 address used only as a URL host in tests. No
# request is ever sent over a real socket: transport is always mocked.
PUBLIC_IP = "93.184.216.34"


def _make_png_bytes(size=(100, 80), color=(255, 0, 0)) -> bytes:
    img = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _make_jpeg_bytes(size=(100, 80), color=(0, 255, 0)) -> bytes:
    img = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    return buffer.getvalue()


def _mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _ok_png_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "image/png"},
        content=_make_png_bytes(),
    )


# ── Happy path ───────────────────────────────────────────────────────────

class TestHappyPath:
    def test_valid_png_is_ingested_with_thumbnail(self):
        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/image.png",
            transport=_mock_transport(_ok_png_handler),
        )
        assert result.ok is True
        assert result.reason is None
        assert result.image_format == "PNG"
        assert result.content_type == "image/png"
        assert result.width == 100
        assert result.height == 80
        assert result.image_bytes
        assert result.thumbnail_bytes
        # Thumbnail is bounded and preserves aspect ratio (100x80 -> 400x320 max, capped at 400x400).
        thumb = Image.open(io.BytesIO(result.thumbnail_bytes))
        assert thumb.width <= 400 and thumb.height <= 400
        assert round(thumb.width / thumb.height, 2) == round(100 / 80, 2)

    def test_valid_jpeg_is_ingested(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "image/jpeg; charset=binary"},
                content=_make_jpeg_bytes(),
            )

        result = fetch_and_validate_image(
            f"https://{PUBLIC_IP}/photo.jpg",
            transport=_mock_transport(handler),
        )
        assert result.ok is True
        assert result.image_format == "JPEG"

    def test_exif_orientation_is_corrected(self):
        img = Image.new("RGB", (60, 30), (10, 20, 30))
        exif = img.getexif()
        exif[0x0112] = 6  # Orientation: rotate 270
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", exif=exif)
        raw = buffer.getvalue()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=raw)

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/rotated.jpg",
            transport=_mock_transport(handler),
        )
        assert result.ok is True
        # Orientation 6 swaps width/height for a 60x30 source.
        assert result.width == 30
        assert result.height == 60


# ── Scheme / URL validation ─────────────────────────────────────────────

class TestSchemeValidation:
    @pytest.mark.parametrize("url", [
        "ftp://example.com/image.png",
        "file:///etc/passwd",
        "data:image/png;base64,abcd",
        "javascript:alert(1)",
        "gopher://example.com/1",
    ])
    def test_unsupported_schemes_are_rejected(self, url):
        result = fetch_and_validate_image(url, transport=_mock_transport(_ok_png_handler))
        assert result.ok is False
        assert result.reason == ImageIngestReason.UNSUPPORTED_SCHEME

    def test_url_without_host_is_rejected(self):
        result = fetch_and_validate_image("http:///image.png", transport=_mock_transport(_ok_png_handler))
        assert result.ok is False
        assert result.reason == ImageIngestReason.INVALID_URL


# ── SSRF: unsafe network destinations ───────────────────────────────────

class TestUnsafeDestinations:
    @pytest.mark.parametrize("host", [
        "127.0.0.1",
        "127.0.0.53",
        "localhost",
        "169.254.169.254",   # cloud metadata endpoint (link-local)
        "10.0.0.5",           # private
        "172.16.0.1",         # private
        "192.168.1.1",        # private
        "0.0.0.0",             # unspecified
        "224.0.0.1",           # multicast
        "[::1]",                # IPv6 loopback
        "[fe80::1]",             # IPv6 link-local
        "[fc00::1]",              # IPv6 unique local (private)
    ])
    def test_malicious_destinations_are_rejected(self, host, monkeypatch):
        # "localhost" resolves via DNS in this implementation; everything
        # else is a literal IP and bypasses DNS entirely.
        if host == "localhost":
            monkeypatch.setattr(
                socket, "getaddrinfo",
                lambda *a, **k: [(socket.AF_INET, None, None, "", ("127.0.0.1", 0))],
            )
        url = f"http://{host}/image.png"
        result = fetch_and_validate_image(url, transport=_mock_transport(_ok_png_handler))
        assert result.ok is False
        assert result.reason in (
            ImageIngestReason.UNSAFE_DESTINATION,
            ImageIngestReason.INVALID_URL,
        )

    def test_dns_resolution_failure_is_reported(self, monkeypatch):
        def fail(*a, **k):
            raise socket.gaierror("name resolution failed")

        monkeypatch.setattr(socket, "getaddrinfo", fail)
        result = fetch_and_validate_image(
            "http://nonexistent.invalid/image.png",
            transport=_mock_transport(_ok_png_handler),
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.DNS_RESOLUTION_FAILED

    def test_dns_rebinding_hostname_with_mixed_answers_is_rejected(self, monkeypatch):
        # One public-looking answer and one internal answer: reject the
        # whole hostname rather than racing which one gets used.
        monkeypatch.setattr(
            socket, "getaddrinfo",
            lambda *a, **k: [
                (socket.AF_INET, None, None, "", (PUBLIC_IP, 0)),
                (socket.AF_INET, None, None, "", ("10.0.0.9", 0)),
            ],
        )
        result = fetch_and_validate_image(
            "http://rebinder.example/image.png",
            transport=_mock_transport(_ok_png_handler),
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.UNSAFE_DESTINATION


# ── Redirects ────────────────────────────────────────────────────────────

class TestRedirects:
    def test_safe_redirect_is_followed_and_revalidated(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if len(calls) == 1:
                return httpx.Response(302, headers={"location": f"http://{PUBLIC_IP}/final.png"})
            return httpx.Response(200, headers={"content-type": "image/png"}, content=_make_png_bytes())

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/start.png",
            transport=_mock_transport(handler),
        )
        assert result.ok is True
        assert len(calls) == 2

    def test_redirect_to_unsafe_destination_is_rejected(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == PUBLIC_IP:
                return httpx.Response(302, headers={"location": "http://127.0.0.1/evil.png"})
            # Should never be reached: the pinned transport must reject
            # the redirect target before issuing this request.
            return httpx.Response(200, headers={"content-type": "image/png"}, content=_make_png_bytes())

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/start.png",
            transport=_mock_transport(handler),
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.UNSAFE_DESTINATION

    def test_redirect_depth_is_bounded(self):
        counter = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            counter["n"] += 1
            return httpx.Response(
                302, headers={"location": f"http://{PUBLIC_IP}/hop{counter['n']}.png"}
            )

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/start.png",
            transport=_mock_transport(handler),
            max_redirects=3,
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.TOO_MANY_REDIRECTS
        assert counter["n"] <= 5

    def test_redirect_to_unsupported_scheme_is_rejected(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "file:///etc/passwd"})

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/start.png",
            transport=_mock_transport(handler),
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.UNSUPPORTED_SCHEME


# ── Size limits ──────────────────────────────────────────────────────────

class TestSizeLimits:
    def test_oversized_content_length_is_rejected_without_reading_body(self):
        read_calls = {"n": 0}

        class TrackingStream:
            def __iter__(self):
                read_calls["n"] += 1
                yield b"x" * 1000

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "image/png", "content-length": "999999999"},
                content=_make_png_bytes(),
            )

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/huge.png",
            transport=_mock_transport(handler),
            max_bytes=1000,
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.RESPONSE_TOO_LARGE

    def test_stream_exceeding_max_bytes_is_rejected(self):
        big_payload = b"\x89PNG\r\n" + b"0" * 5000  # not a valid PNG, but size check runs first

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "image/png"}, content=big_payload)

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/big.png",
            transport=_mock_transport(handler),
            max_bytes=1000,
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.RESPONSE_TOO_LARGE


# ── MIME validation ──────────────────────────────────────────────────────

class TestMimeValidation:
    def test_disallowed_content_type_is_rejected(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=b"%PDF-1.4",
            )

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/doc.pdf",
            transport=_mock_transport(handler),
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.MIME_NOT_ALLOWED

    def test_declared_mime_and_decoded_format_mismatch_is_rejected(self):
        # Declares PNG but the bytes are actually a JPEG.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "image/png"},
                content=_make_jpeg_bytes(),
            )

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/mismatch.png",
            transport=_mock_transport(handler),
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.MIME_MISMATCH


# ── Corrupt / malicious image payloads ──────────────────────────────────

class TestImageDecoding:
    def test_corrupt_image_bytes_are_rejected(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "image/png"},
                content=b"\x89PNG\r\n\x1a\nnot-actually-a-valid-png-body",
            )

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/corrupt.png",
            transport=_mock_transport(handler),
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.DECODE_FAILED

    def test_excessive_dimensions_are_rejected(self):
        img = Image.new("RGB", (9000, 100), (1, 1, 1))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "image/png"}, content=buffer.getvalue())

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/wide.png",
            transport=_mock_transport(handler),
            max_dimension=8000,
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.DIMENSIONS_TOO_LARGE

    def test_excessive_pixel_count_decompression_bomb_is_rejected(self):
        # A PNG that decodes within max_dimension per side but exceeds the
        # overall pixel-count budget (decompression-bomb shape).
        img = Image.new("RGB", (7000, 7000), (2, 2, 2))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG", compress_level=9)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "image/png"}, content=buffer.getvalue())

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/bomb.png",
            transport=_mock_transport(handler),
            max_bytes=200 * 1024 * 1024,
            max_dimension=8000,
            max_pixels=40_000_000,
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.PIXEL_COUNT_TOO_LARGE


# ── HTTP / timeout errors ────────────────────────────────────────────────

class TestNetworkErrors:
    def test_non_200_status_is_rejected(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/missing.png",
            transport=_mock_transport(handler),
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.HTTP_ERROR

    def test_connect_timeout_is_reported(self):
        class TimingOutTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                raise httpx.ConnectTimeout("connect timed out", request=request)

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/slow.png",
            transport=TimingOutTransport(),
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.TIMEOUT

    def test_read_timeout_is_reported(self):
        class ReadTimingOutTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                raise httpx.ReadTimeout("read timed out", request=request)

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/slow.png",
            transport=ReadTimingOutTransport(),
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.TIMEOUT

    def test_generic_network_error_is_reported_without_leaking_detail(self):
        class BrokenTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                raise httpx.ConnectError("connection refused by 10.9.9.9 secret-internal-host")

        result = fetch_and_validate_image(
            f"http://{PUBLIC_IP}/broken.png",
            transport=BrokenTransport(),
        )
        assert result.ok is False
        assert result.reason == ImageIngestReason.NETWORK_ERROR
        # The stable reason string must not embed exception text.
        assert "10.9.9.9" not in result.reason.value
        assert "secret" not in result.reason.value
