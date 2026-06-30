"""Thin Etsy Open API v3 client (SPEC-P13 External deps).

Stdlib-only (`urllib.request`) so P13 adds no dependency — consistent with P12's stdlib-`http.server`
choice (CLAUDE §6.5). Covers exactly the five calls the publish flow needs (CHANNEL-SPEC §4), plus a
draft delete used by the creds-gated acceptance test to clean up after itself:

  create_draft_listing(payload)            POST   /shops/{shop_id}/listings
  upload_listing_image(listing_id, path)   POST   /shops/{shop_id}/listings/{id}/images   (multipart)
  upload_listing_file(listing_id, path)    POST   /shops/{shop_id}/listings/{id}/files    (multipart)
  activate_listing(listing_id)             PATCH  /shops/{shop_id}/listings/{id}          state=active
  get_listing(listing_id)                  GET    /listings/{id}
  delete_listing(listing_id)               DELETE /listings/{id}

Auth on every call: `Authorization: Bearer <oauth_token>` + `x-api-key: <api_key>` (scopes
`listings_r listings_w`). Errors are typed so the orchestrator can branch per the spec's edge cases:
  EtsyAuthError      401/403 — surface to the human, offer reconnect; never blind-retry.
  EtsyRateLimitError 429     — retried here with bounded linear backoff, then raised.
  EtsyAPIError       any other non-2xx / transport failure.

This module performs raw HTTP only; it makes no compliance or sequencing decisions (the orchestrator
owns those). The exact field names are verified against Etsy's current v3 reference per CHANNEL-SPEC.
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


class EtsyError(Exception):
    """Base class for Etsy API failures."""


class EtsyAuthError(EtsyError):
    """OAuth/auth failure (401/403) — surface to a human; do not retry blindly (SPEC-P13)."""


class EtsyRateLimitError(EtsyError):
    """Rate limited (429) after exhausting bounded backoff (SPEC-P13)."""


class EtsyAPIError(EtsyError):
    """Any other non-2xx response or transport error."""


class EtsyClient:
    """Minimal authenticated Etsy v3 client for one shop."""

    def __init__(
        self,
        *,
        api_key: str,
        oauth_token: str,
        shop_id: str,
        api_base: str = "https://api.etsy.com/v3/application",
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        _sleep=time.sleep,
    ) -> None:
        if not (api_key and oauth_token and shop_id):
            raise EtsyAuthError(
                "EtsyClient needs api_key, oauth_token and shop_id — set ETSY_* in .env"
            )
        self.api_key = api_key
        self.oauth_token = oauth_token
        self.shop_id = str(shop_id)
        self.api_base = api_base.rstrip("/")
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._sleep = _sleep

    # -- low-level request --------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.oauth_token}",
            "x-api-key": self.api_key,
        }

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
                    raise EtsyAuthError(f"{method} {url} -> {exc.code}: {detail}") from exc
                if exc.code == 429:
                    if attempt <= self.max_retries:
                        self._sleep(self.backoff_seconds * attempt)
                        continue
                    raise EtsyRateLimitError(
                        f"{method} {url} -> 429 after {self.max_retries} retries: {detail}"
                    ) from exc
                raise EtsyAPIError(f"{method} {url} -> {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                raise EtsyAPIError(f"{method} {url} transport error: {exc.reason}") from exc

    # -- endpoints ----------------------------------------------------------
    def create_draft_listing(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST a draft listing. Returns the created listing (incl. `listing_id`)."""
        url = f"{self.api_base}/shops/{self.shop_id}/listings"
        body = _urlencode(payload).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        return self._request("POST", url, data=body, headers=headers)

    def upload_listing_image(self, listing_id: str, image_path: str, rank: int = 1) -> dict[str, Any]:
        """Upload one mockup/preview image to a listing (multipart/form-data)."""
        url = f"{self.api_base}/shops/{self.shop_id}/listings/{listing_id}/images"
        body, content_type = _multipart(
            fields={"rank": str(rank)},
            file_field="image",
            file_path=image_path,
        )
        return self._request("POST", url, data=body, headers={"Content-Type": content_type})

    def upload_listing_file(self, listing_id: str, file_path: str, name: str | None = None) -> dict[str, Any]:
        """Upload the digital file (the print-ready PDF) to a listing (multipart/form-data)."""
        url = f"{self.api_base}/shops/{self.shop_id}/listings/{listing_id}/files"
        body, content_type = _multipart(
            fields={"name": name or Path(file_path).name},
            file_field="file",
            file_path=file_path,
        )
        return self._request("POST", url, data=body, headers={"Content-Type": content_type})

    def activate_listing(self, listing_id: str) -> dict[str, Any]:
        """PATCH the listing to `state='active'` — go live (CHANNEL-SPEC §4 step 5)."""
        url = f"{self.api_base}/shops/{self.shop_id}/listings/{listing_id}"
        body = _urlencode({"state": "active"}).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        return self._request("PATCH", url, data=body, headers=headers)

    def get_listing(self, listing_id: str) -> dict[str, Any]:
        url = f"{self.api_base}/listings/{listing_id}"
        return self._request("GET", url)

    def delete_listing(self, listing_id: str) -> dict[str, Any]:
        """Delete a (draft) listing — used by the creds-gated test to clean up its real draft."""
        url = f"{self.api_base}/listings/{listing_id}"
        return self._request("DELETE", url)


# ---------------------------------------------------------------------------
# encoding helpers
# ---------------------------------------------------------------------------
def _urlencode(payload: dict[str, Any]) -> str:
    """Form-encode a payload. List values become repeated keys (Etsy v3 accepts repeated `tags`);
    booleans are lowercased to true/false."""
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
