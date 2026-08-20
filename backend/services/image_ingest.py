"""
Bounded, SSRF-hardened remote image ingestion.

This module downloads a single remote image over HTTP(S), validates it end
to end (network destination, declared MIME type, decoded format, dimensions,
pixel count), and returns orientation-corrected image bytes plus a bounded
thumbnail. It performs no storage: callers own persistence.

Scope (see issue #46/#49): standalone ingestion + validation utility. It is
NOT wired into Hashnode sync, routers, or the article/asset store.

Security model
---------------
Untrusted URLs can point at internal infrastructure (SSRF) directly, via a
redirect chain, or via DNS rebinding (a hostname that resolves safely at
validation time and unsafely at connect time). To close all three paths:

- Only http/https schemes are accepted.
- Every hop (the original URL and each redirect target) has its hostname
  resolved to a concrete IP address, and that IP is checked against the
  loopback / link-local / private / multicast / reserved / unspecified
  ranges *before* any connection is made.
- The connection is pinned to the exact IP address that was validated (via
  a transport wrapper), so a hostname cannot resolve to a different,
  unsafe address between validation and connection (DNS rebinding).
- Redirects are followed manually, one hop at a time, up to a bounded
  count, with the same validation applied to each target.
"""
from __future__ import annotations

import io
import socket
from dataclasses import dataclass
from enum import Enum
from ipaddress import IPv4Address, IPv6Address, ip_address
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

# ── Policy ───────────────────────────────────────────────────────────────

ALLOWED_SCHEMES = {"http", "https"}

# Declared Content-Type -> expected Pillow format name. Both must agree.
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/gif": "GIF",
    "image/webp": "WEBP",
}
ALLOWED_IMAGE_FORMATS = set(ALLOWED_CONTENT_TYPES.values())

DEFAULT_MAX_BYTES = 8 * 1024 * 1024          # 8 MiB response cap
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_DIMENSION = 8000                 # px, per side
DEFAULT_MAX_PIXELS = 40_000_000              # ~40 MP decompression-bomb guard
DEFAULT_THUMBNAIL_SIZE = (400, 400)          # bounded card thumbnail (w, h)
DEFAULT_TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=5.0)


class ImageIngestReason(str, Enum):
    """Stable, non-secret failure categories safe to surface in sync reports."""

    UNSUPPORTED_SCHEME = "unsupported_scheme"
    INVALID_URL = "invalid_url"
    UNSAFE_DESTINATION = "unsafe_destination"
    DNS_RESOLUTION_FAILED = "dns_resolution_failed"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    MIME_NOT_ALLOWED = "mime_not_allowed"
    MIME_MISMATCH = "mime_mismatch"
    RESPONSE_TOO_LARGE = "response_too_large"
    DECODE_FAILED = "decode_failed"
    DIMENSIONS_TOO_LARGE = "dimensions_too_large"
    PIXEL_COUNT_TOO_LARGE = "pixel_count_too_large"
    NETWORK_ERROR = "network_error"


class ImageIngestError(Exception):
    """Internal control-flow exception. Never escapes fetch_and_validate_image."""

    def __init__(self, reason: ImageIngestReason):
        self.reason = reason
        super().__init__(reason.value)


@dataclass
class IngestedImage:
    """Result of an ingestion attempt. Bytes are held in memory only; nothing
    is written to disk or a database by this module."""

    ok: bool
    reason: ImageIngestReason | None = None
    source_url: str | None = None
    final_url: str | None = None
    content_type: str | None = None
    image_format: str | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    image_bytes: bytes | None = None
    thumbnail_bytes: bytes | None = None
    thumbnail_format: str | None = None
    thumbnail_width: int | None = None
    thumbnail_height: int | None = None


# ── Network safety ──────────────────────────────────────────────────────

def _is_safe_ip(ip: IPv4Address | IPv6Address) -> bool:
    if isinstance(ip, IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_safe_ip(hostname: str) -> str:
    """Resolve hostname to an IP and reject it if unsafe. Raises ImageIngestError."""
    try:
        literal = ip_address(hostname.strip("[]"))
    except ValueError:
        literal = None

    if literal is not None:
        if not _is_safe_ip(literal):
            raise ImageIngestError(ImageIngestReason.UNSAFE_DESTINATION)
        return str(literal)

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ImageIngestError(ImageIngestReason.DNS_RESOLUTION_FAILED) from exc

    resolved: list[IPv4Address | IPv6Address] = []
    for info in infos:
        addr = info[4][0]
        try:
            resolved.append(ip_address(addr.split("%")[0]))
        except ValueError:
            continue

    if not resolved:
        raise ImageIngestError(ImageIngestReason.DNS_RESOLUTION_FAILED)

    # Reject the whole hostname if *any* resolved address is unsafe. A host
    # that answers with a mix of public and private addresses is exactly
    # the DNS-rebinding shape we're defending against.
    for candidate in resolved:
        if not _is_safe_ip(candidate):
            raise ImageIngestError(ImageIngestReason.UNSAFE_DESTINATION)

    return str(resolved[0])


def _validate_scheme(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise ImageIngestError(ImageIngestReason.UNSUPPORTED_SCHEME)
    if not parts.hostname:
        raise ImageIngestError(ImageIngestReason.INVALID_URL)
    return url


class _PinnedTransport(httpx.BaseTransport):
    """Wraps a transport so every request (including redirect hops handled by
    the caller) is DNS-resolved and safety-checked immediately before the
    connection is made, and the connection is pinned to that exact address.

    This closes the DNS-rebinding gap: resolving a hostname once during
    validation and connecting to it separately later would let an attacker
    change the answer in between.
    """

    def __init__(self, wrapped: httpx.BaseTransport):
        self._wrapped = wrapped

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        hostname = request.url.host
        ip = _resolve_safe_ip(hostname)
        pinned_url = request.url.copy_with(host=ip)
        pinned_request = httpx.Request(
            method=request.method,
            url=pinned_url,
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": hostname},
        )
        response = self._wrapped.handle_request(pinned_request)
        response.request = request
        return response

    def close(self) -> None:
        self._wrapped.close()


def _normalize_content_type(header_value: str | None) -> str | None:
    if not header_value:
        return None
    return header_value.split(";")[0].strip().lower()


# ── Download ─────────────────────────────────────────────────────────────

def _download(
    url: str,
    *,
    max_bytes: int,
    max_redirects: int,
    timeout: httpx.Timeout,
    transport: httpx.BaseTransport,
) -> tuple[bytes, str, str]:
    """Stream a single image, following bounded, revalidated redirects.

    Returns (bytes, normalized_content_type, final_url).
    """
    current_url = _validate_scheme(url)
    pinned = _PinnedTransport(transport)

    with httpx.Client(transport=pinned, timeout=timeout, follow_redirects=False) as client:
        redirects = 0
        while True:
            try:
                with client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        redirects += 1
                        if redirects > max_redirects:
                            raise ImageIngestError(ImageIngestReason.TOO_MANY_REDIRECTS)
                        location = response.headers.get("location")
                        if not location:
                            raise ImageIngestError(ImageIngestReason.HTTP_ERROR)
                        next_url = str(httpx.URL(current_url).join(location))
                        current_url = _validate_scheme(next_url)
                        continue

                    if response.status_code != 200:
                        raise ImageIngestError(ImageIngestReason.HTTP_ERROR)

                    content_type = _normalize_content_type(response.headers.get("content-type"))
                    if content_type not in ALLOWED_CONTENT_TYPES:
                        raise ImageIngestError(ImageIngestReason.MIME_NOT_ALLOWED)

                    declared_length = response.headers.get("content-length")
                    if declared_length is not None and declared_length.isdigit():
                        if int(declared_length) > max_bytes:
                            raise ImageIngestError(ImageIngestReason.RESPONSE_TOO_LARGE)

                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > max_bytes:
                            raise ImageIngestError(ImageIngestReason.RESPONSE_TOO_LARGE)

                    return bytes(chunks), content_type, current_url
            except ImageIngestError:
                raise
            except httpx.TimeoutException as exc:
                raise ImageIngestError(ImageIngestReason.TIMEOUT) from exc
            except httpx.HTTPError as exc:
                raise ImageIngestError(ImageIngestReason.NETWORK_ERROR) from exc


# ── Decode & thumbnail ──────────────────────────────────────────────────

def _decode_and_build(
    image_bytes: bytes,
    *,
    content_type: str,
    max_dimension: int,
    max_pixels: int,
    thumbnail_size: tuple[int, int],
) -> tuple[Image.Image, Image.Image, str]:
    """Validate, orientation-correct, and thumbnail decoded image bytes.

    Returns (corrected_full_image, thumbnail_image, pillow_format).
    Raises ImageIngestError on any validation failure.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img_format = img.format
        width, height = img.size
    except Image.DecompressionBombError as exc:
        raise ImageIngestError(ImageIngestReason.PIXEL_COUNT_TOO_LARGE) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageIngestError(ImageIngestReason.DECODE_FAILED) from exc

    if img_format not in ALLOWED_IMAGE_FORMATS:
        raise ImageIngestError(ImageIngestReason.MIME_MISMATCH)

    expected_format = ALLOWED_CONTENT_TYPES[content_type]
    if img_format != expected_format:
        raise ImageIngestError(ImageIngestReason.MIME_MISMATCH)

    # Dimension / pixel-count checks happen before the full pixel decode
    # (Image.open only parses headers) to guard against decompression bombs.
    if width > max_dimension or height > max_dimension:
        raise ImageIngestError(ImageIngestReason.DIMENSIONS_TOO_LARGE)
    if width * height > max_pixels:
        raise ImageIngestError(ImageIngestReason.PIXEL_COUNT_TOO_LARGE)

    try:
        img.load()
    except Image.DecompressionBombError as exc:
        raise ImageIngestError(ImageIngestReason.PIXEL_COUNT_TOO_LARGE) from exc
    except (OSError, ValueError) as exc:
        raise ImageIngestError(ImageIngestReason.DECODE_FAILED) from exc

    corrected = ImageOps.exif_transpose(img) or img

    thumb = corrected.copy()
    thumb.thumbnail(thumbnail_size, Image.LANCZOS)

    return corrected, thumb, img_format


def _encode(img: Image.Image, fmt: str) -> bytes:
    if fmt == "JPEG" and img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format=fmt)
    return buffer.getvalue()


def _encode_thumbnail(img: Image.Image) -> bytes:
    if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        img = img.convert("RGBA")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


# ── Public API ───────────────────────────────────────────────────────────

def fetch_and_validate_image(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    max_dimension: int = DEFAULT_MAX_DIMENSION,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    thumbnail_size: tuple[int, int] = DEFAULT_THUMBNAIL_SIZE,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    transport: httpx.BaseTransport | None = None,
) -> IngestedImage:
    """Download and validate a single remote image.

    This function performs no storage: it returns bytes and metadata only.
    `transport` overrides the underlying HTTP transport (used by tests to
    avoid real network calls); production callers should leave it unset.

    On any failure, returns IngestedImage(ok=False, reason=<stable enum>)
    with no exception raised and no internal detail exposed.
    """
    base_transport = transport if transport is not None else httpx.HTTPTransport()

    try:
        image_bytes, content_type, final_url = _download(
            url,
            max_bytes=max_bytes,
            max_redirects=max_redirects,
            timeout=timeout,
            transport=base_transport,
        )
        corrected, thumb, img_format = _decode_and_build(
            image_bytes,
            content_type=content_type,
            max_dimension=max_dimension,
            max_pixels=max_pixels,
            thumbnail_size=thumbnail_size,
        )
        normalized_bytes = _encode(corrected, img_format)
        thumbnail_bytes = _encode_thumbnail(thumb)
    except ImageIngestError as exc:
        return IngestedImage(ok=False, reason=exc.reason, source_url=url)
    except Exception:
        # Anything unanticipated is reported generically; no raw exception
        # text or stack trace crosses this boundary.
        return IngestedImage(ok=False, reason=ImageIngestReason.DECODE_FAILED, source_url=url)

    return IngestedImage(
        ok=True,
        source_url=url,
        final_url=final_url,
        content_type=content_type,
        image_format=img_format,
        width=corrected.width,
        height=corrected.height,
        size_bytes=len(normalized_bytes),
        image_bytes=normalized_bytes,
        thumbnail_bytes=thumbnail_bytes,
        thumbnail_format="PNG",
        thumbnail_width=thumb.width,
        thumbnail_height=thumb.height,
    )
