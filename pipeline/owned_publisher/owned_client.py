"""Thin owned-storefront clients — Payhip & Gumroad (SPEC-P14 External deps).

Stdlib-only (`urllib.request`) so P14 adds no dependency — consistent with P13's Etsy client and
P12's stdlib-`http.server` choice (CLAUDE §6.5). Both platforms expose the same uniform interface the
orchestrator drives (create -> upload file -> upload images -> publish), so the orchestrator is
channel-agnostic and the acceptance test can inject one fake for either platform:

  create_product(payload)            -> {"product_id", "url"?, "email_capture_enabled", "state"}
  upload_file(product_id, path)         the digital file (print-ready PDF)
  upload_image(product_id, path, rank)  a preview/cover image
  publish_product(product_id)        -> {"product_id", "url", "state": "published"}
  delete_product(product_id)            cleanup (used by the creds-gated acceptance test)

`create_product` echoes `email_capture_enabled` from the request so the orchestrator can VERIFY the
list opt-in is actually on before going live (CHANNEL-SPEC §5 step 4) — never sent-and-assumed.

Auth: Payhip sends `payhip-api-key: <key>`; Gumroad sends the OAuth `access_token` (Bearer). Errors
are typed so the orchestrator can branch per the spec's edge cases:
  OwnedAuthError      401/403 — surface to the human, offer reconnect; never blind-retry.
  OwnedRateLimitError 429     — retried here with bounded linear backoff, then raised.
  OwnedAPIError       any other non-2xx / transport failure.

RECENCY CAVEAT (SPEC-P14 + CHANNEL-SPEC §5): the Payhip/Gumroad product-CREATION API surface is
limited and shifts — the endpoints/field names below are a best-effort mapping and MUST be verified
against each platform's current docs before a live publish (some plans require a manual/UI create
step). This module performs raw HTTP only; it makes no compliance or sequencing decisions (the
orchestrator owns those). Part 2 of the acceptance test (injected fake) is the authoritative proof of
the orchestration; Part 3 (real API) is creds-gated + optional.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


class OwnedError(Exception):
    """Base class for owned-storefront API failures."""


class OwnedAuthError(OwnedError):
    """Auth failure (401/403) or missing credentials — surface to a human; no blind retry (SPEC-P14)."""


class OwnedRateLimitError(OwnedError):
    """Rate limited (429) after exhausting bounded backoff (SPEC-P14)."""


class OwnedAPIError(OwnedError):
    """Any other non-2xx response or transport error."""


class _BaseOwnedClient:
    """Shared HTTP plumbing + the uniform publish interface. Subclasses set the platform base URL,
    auth header, and the per-endpoint request shaping."""

    platform = "owned"

    def __init__(
        self,
        *,
        api_base: str,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        _sleep=time.sleep,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._sleep = _sleep

    # -- low-level request --------------------------------------------------
    def _headers(self) -> dict[str, str]:  # pragma: no cover - overridden
        raise NotImplementedError

    def _request(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Issue one HTTP request, retrying 429 with bounded linear backoff. Returns parsed JSON
        ({} for an empty body). Maps auth/rate-limit/other failures to typed errors."""
        all_headers = {**self._headers(), **(headers or {})}
        attempt = 0
        while True:
            attempt += 1
            req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
            try:
                with urllib.request.urlopen(req) as resp:
                    body = resp.read()
                    return json.loads(body) if body else {}
            except urllib.error.HTTPError as exc:
                detail = _safe_read(exc)
                if exc.code in (401, 403):
                    raise OwnedAuthError(f"{method} {url} -> {exc.code}: {detail}") from exc
                if exc.code == 429:
                    if attempt <= self.max_retries:
                        self._sleep(self.backoff_seconds * attempt)
                        continue
                    raise OwnedRateLimitError(
                        f"{method} {url} -> 429 after {self.max_retries} retries: {detail}"
                    ) from exc
                raise OwnedAPIError(f"{method} {url} -> {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                raise OwnedAPIError(f"{method} {url} transport error: {exc.reason}") from exc

    # -- uniform interface (subclasses implement) ---------------------------
    def create_product(self, payload: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def upload_file(self, product_id: str, file_path: str, name: str | None = None) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def upload_image(self, product_id: str, image_path: str, rank: int = 1) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def publish_product(self, product_id: str) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def delete_product(self, product_id: str) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


class PayhipClient(_BaseOwnedClient):
    """Payhip owned-storefront client. Auth: `payhip-api-key: <key>` (server-side only)."""

    platform = "payhip"

    def __init__(self, *, api_key: str, api_base: str, **kw) -> None:
        if not api_key:
            raise OwnedAuthError("PayhipClient needs api_key — set PAYHIP_API_KEY in .env")
        self.api_key = api_key
        super().__init__(api_base=api_base, **kw)

    def _headers(self) -> dict[str, str]:
        return {"payhip-api-key": self.api_key}

    def create_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.api_base}/product"
        body = _urlencode({
            "name": payload.get("title"),
            "description": payload.get("description"),
            "price": payload.get("price"),
            "currency": payload.get("currency"),
            # Payhip "email subscribers" opt-in on the product (list opt-in).
            "enable_email_capture": payload.get("enable_email_capture"),
        }).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = self._request("POST", url, data=body, headers=headers)
        return _normalize_created(resp, requested_email_capture=payload.get("enable_email_capture"))

    def upload_file(self, product_id: str, file_path: str, name: str | None = None) -> dict[str, Any]:
        url = f"{self.api_base}/product/{product_id}/file"
        body, content_type = _multipart(
            fields={"name": name or Path(file_path).name}, file_field="file", file_path=file_path
        )
        return self._request("POST", url, data=body, headers={"Content-Type": content_type})

    def upload_image(self, product_id: str, image_path: str, rank: int = 1) -> dict[str, Any]:
        url = f"{self.api_base}/product/{product_id}/image"
        body, content_type = _multipart(
            fields={"rank": str(rank)}, file_field="image", file_path=image_path
        )
        return self._request("POST", url, data=body, headers={"Content-Type": content_type})

    def publish_product(self, product_id: str) -> dict[str, Any]:
        url = f"{self.api_base}/product/{product_id}"
        body = _urlencode({"published": True}).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        return self._request("PATCH", url, data=body, headers=headers)

    def delete_product(self, product_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"{self.api_base}/product/{product_id}")


class GumroadClient(_BaseOwnedClient):
    """Gumroad owned-storefront client. Auth: OAuth `access_token` (Bearer)."""

    platform = "gumroad"

    def __init__(self, *, access_token: str, api_base: str, **kw) -> None:
        if not access_token:
            raise OwnedAuthError("GumroadClient needs access_token — set GUMROAD_ACCESS_TOKEN in .env")
        self.access_token = access_token
        super().__init__(api_base=api_base, **kw)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def create_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.api_base}/products"
        body = _urlencode({
            "name": payload.get("title"),
            "description": payload.get("description"),
            # Gumroad prices are in cents.
            "price": int(round(float(payload.get("price") or 0) * 100)),
            "currency": payload.get("currency"),
            # Gumroad "customize receipt / email subscribers" list opt-in.
            "enable_email_capture": payload.get("enable_email_capture"),
        }).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = self._request("POST", url, data=body, headers=headers)
        return _normalize_created(resp, requested_email_capture=payload.get("enable_email_capture"))

    def upload_file(self, product_id: str, file_path: str, name: str | None = None) -> dict[str, Any]:
        url = f"{self.api_base}/products/{product_id}/files"
        body, content_type = _multipart(
            fields={"name": name or Path(file_path).name}, file_field="file", file_path=file_path
        )
        return self._request("POST", url, data=body, headers={"Content-Type": content_type})

    def upload_image(self, product_id: str, image_path: str, rank: int = 1) -> dict[str, Any]:
        url = f"{self.api_base}/products/{product_id}/images"
        body, content_type = _multipart(
            fields={"rank": str(rank)}, file_field="image", file_path=image_path
        )
        return self._request("POST", url, data=body, headers={"Content-Type": content_type})

    def publish_product(self, product_id: str) -> dict[str, Any]:
        url = f"{self.api_base}/products/{product_id}/enable"
        return self._request("PUT", url, data=b"")

    def delete_product(self, product_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"{self.api_base}/products/{product_id}")


def build_client(platform: str, cfg: dict, *, settings=None) -> _BaseOwnedClient:
    """Build the real client for `platform` from .env credentials. Raises OwnedAuthError if creds are
    absent (so the acceptance test injects a fake instead — mirrors P13's _build_client)."""
    if settings is None:
        from pipeline.lib.config import get_settings
        settings = get_settings()

    platforms = cfg.get("platforms") or {}
    if platform not in platforms:
        raise ValueError(f"unknown owned platform '{platform}' (configured: {list(platforms)})")
    api_base = platforms[platform]["api_base"]
    common = {
        "api_base": api_base,
        "max_retries": int(cfg.get("max_retries", 3)),
        "backoff_seconds": float(cfg.get("backoff_seconds", 2)),
    }
    if platform == "payhip":
        return PayhipClient(api_key=settings.payhip_api_key, **common)
    if platform == "gumroad":
        return GumroadClient(access_token=settings.gumroad_access_token, **common)
    raise ValueError(f"no client implementation for owned platform '{platform}'")


# ---------------------------------------------------------------------------
# response normalization
# ---------------------------------------------------------------------------
def _normalize_created(resp: dict[str, Any], *, requested_email_capture: Any) -> dict[str, Any]:
    """Map a platform create-product response onto the uniform shape the orchestrator expects. The
    product id field differs per platform (`product_id` / `id` / nested `product.id`); email capture
    is read back from the response when present, else falls back to what was requested."""
    product = resp.get("product") if isinstance(resp.get("product"), dict) else resp
    product_id = (
        product.get("product_id")
        or product.get("id")
        or resp.get("product_id")
        or resp.get("id")
    )
    email_capture = product.get("email_capture_enabled")
    if email_capture is None:
        email_capture = product.get("enable_email_capture")
    if email_capture is None:
        email_capture = bool(requested_email_capture)
    return {
        "product_id": str(product_id) if product_id is not None else "",
        "url": product.get("url") or product.get("short_url") or resp.get("url"),
        "email_capture_enabled": bool(email_capture),
        "state": product.get("state") or "draft",
    }


# ---------------------------------------------------------------------------
# encoding helpers (mirror pipeline/etsy_publisher/etsy_client.py)
# ---------------------------------------------------------------------------
def _urlencode(payload: dict[str, Any]) -> str:
    """Form-encode a payload. List values become repeated keys; booleans are lowercased to
    true/false; None values are dropped."""
    pairs: list[tuple[str, str]] = []
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, bool):
            pairs.append((key, "true" if value else "false"))
        elif isinstance(value, (list, tuple)):
            for item in value:
                pairs.append((key, str(item)))
        else:
            pairs.append((key, str(value)))
    return urllib.parse.urlencode(pairs)


def _multipart(*, fields: dict[str, str], file_field: str, file_path: str) -> tuple[bytes, str]:
    """Build a multipart/form-data body with one file part. Returns (body, content_type)."""
    path = Path(file_path)
    data = path.read_bytes()
    boundary = f"----publishly{uuid.uuid4().hex}"
    crlf = b"\r\n"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(b"--" + boundary.encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        parts.append(b"")
        parts.append(str(value).encode())
    parts.append(b"--" + boundary.encode())
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{path.name}"'.encode()
    )
    parts.append(b"Content-Type: application/octet-stream")
    parts.append(b"")
    parts.append(data)
    parts.append(b"--" + boundary.encode() + b"--")
    parts.append(b"")
    body = crlf.join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


def _safe_read(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:500]
    except Exception:  # noqa: BLE001 — diagnostic only
        return "<no body>"
