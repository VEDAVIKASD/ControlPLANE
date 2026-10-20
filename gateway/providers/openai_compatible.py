from __future__ import annotations

from typing import Any

import httpx

from gateway.providers.base import Provider, ProviderError


class OpenAICompatibleProvider(Provider):
    """Forwards requests to an OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_s: float = 30.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key.strip()
        self._timeout_s = timeout_s

    async def chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            raise ProviderError(
                "AI provider is not configured: UPSTREAM_API_KEY is missing."
            )

        if not self._base_url:
            raise ProviderError(
                "AI provider is not configured: UPSTREAM_BASE_URL is missing."
            )

        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                )
            response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"Upstream returned HTTP {exc.response.status_code}."
            ) from exc

        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Upstream request failed: {type(exc).__name__}."
            ) from exc

        try:
            result = response.json()
        except ValueError as exc:
            raise ProviderError("Upstream returned a non-JSON response.") from exc

        if not isinstance(result, dict):
            raise ProviderError("Upstream returned an invalid response format.")

        return result
