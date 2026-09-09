"""Low-volume client for the BIS Standards Portal's observed metadata endpoints.

This client deliberately retrieves metadata only. It does not download or redistribute
full BIS standard text/PDFs. The endpoints are observed portal service contracts, not a
documented public developer API, so callers should keep traffic low and cache results.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import httpx

BASE_URL = "https://standardsadmin.bis.gov.in/review-service"
PORTAL_URL = "https://standards.bis.gov.in/"


class BISClientError(RuntimeError):
    """Raised when a BIS metadata request cannot be completed or validated."""


@dataclass(frozen=True)
class BISClientConfig:
    base_url: str = BASE_URL
    portal_url: str = PORTAL_URL
    timeout_seconds: float = 20.0
    max_retries: int = 2
    backoff_seconds: float = 0.75
    user_agent: str = "SIH-26108-BIS-Metadata-Client/2.0"


class BISClient:
    """Small, synchronous BIS metadata client suitable for one-off enrichment."""

    def __init__(self, config: BISClientConfig | None = None, client: httpx.Client | None = None) -> None:
        self.config = config or BISClientConfig()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=self.config.timeout_seconds,
            follow_redirects=True,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "BISClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json,text/plain,*/*",
            "Content-Type": "application/json",
            "Origin": self.config.portal_url.rstrip("/"),
            "Referer": self.config.portal_url,
            "User-Agent": self.config.user_agent,
        }

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.config.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._client.post(url, json=payload, headers=self._headers)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                else:
                    response.raise_for_status()
                body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt >= self.config.max_retries:
                    break
                time.sleep(self.config.backoff_seconds * (2**attempt))
                continue

            if not isinstance(body, dict):
                raise BISClientError(f"BIS {endpoint} returned a non-object JSON response")
            status = body.get("status")
            if status not in (None, "SUCCESS"):
                raise BISClientError(
                    f"BIS {endpoint} returned status={status!r}: {body.get('msg', '')}"
                )
            return body

        raise BISClientError(f"BIS request failed for {endpoint}: {last_error}") from last_error

    def search_standards(self, search_text: str) -> list[dict[str, Any]]:
        text = search_text.strip()
        if not text:
            raise ValueError("search_text must not be empty")
        body = self._post(
            "searchKnowStandards",
            {
                "searchText": text,
                "token": None,
                "refreshToken": None,
                "clientId": None,
                "clientSecret": None,
                "sub": None,
            },
        )
        data = body.get("data", [])
        if not isinstance(data, list):
            raise BISClientError("BIS search response has invalid 'data'")
        return [item for item in data if isinstance(item, dict)]

    def get_standard_details(self, encoded_id: str) -> dict[str, Any]:
        if not encoded_id:
            raise ValueError("encoded_id must not be empty")
        body = self._post(
            "getWebsiteStandardDetails",
            {
                "encId": encoded_id,
                "fromPage": "guestUserPage",
                "token": None,
                "refreshToken": None,
                "clientId": None,
                "clientSecret": None,
                "sub": None,
            },
        )
        data = body.get("data")
        if not isinstance(data, dict):
            raise BISClientError("BIS details response has invalid 'data'")
        return data

    def get_amendments(self, standard_id: str | int) -> list[dict[str, Any]]:
        if standard_id is None or str(standard_id).strip() == "":
            raise ValueError("standard_id must not be empty")
        body = self._post(
            "getAmendmentDetails",
            {
                "standardId": standard_id,
                "token": None,
                "refreshToken": None,
                "clientId": None,
                "clientSecret": None,
                "sub": None,
            },
        )
        data = body.get("data", [])
        if not isinstance(data, list):
            raise BISClientError("BIS amendment response has invalid 'data'")
        return [item for item in data if isinstance(item, dict)]
