
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import httpx

from gateway.providers.base import Provider, ProviderError

logger = logging.getLogger(__name__)


class AntigravityProvider(Provider):
    """Adapt the Antigravity Interactions API to ControlPlane's chat interface."""

    provider_name = "antigravity"
    supports_model_routing = False

    def __init__(
        self,
        api_key: str,
        agent: str = "antigravity-preview-09-2026",
        model: str | None = None,
        max_total_tokens: int = 12000,
        timeout_s: float = 120.0,
    ) -> None:
        self._api_key = api_key.strip()
        self._agent = agent.strip()
        self._model = model.strip() if model else None
        self._max_total_tokens = max_total_tokens
        self._timeout_s = timeout_s
        self._url = (
            "https://generativelanguage.googleapis.com/v1beta/interactions"
        )

    async def chat_completion(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if not self._api_key:
            raise ProviderError(
                "Antigravity is not configured: UPSTREAM_API_KEY is missing."
            )

        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ProviderError(
                "Antigravity requires a non-empty messages list."
            )

        # Convert supported chat messages into a plain-text transcript.
        transcript: list[str] = []

        for message in messages:
            if not isinstance(message, dict):
                continue

            role = str(message.get("role", "user")).strip().upper()
            content = message.get("content", "")

            if isinstance(content, str):
                transcript.append(f"{role}: {content}")

            elif isinstance(content, list):
                parts = [
                    item["text"]
                    for item in content
                    if isinstance(item, dict)
                    and isinstance(item.get("text"), str)
                ]
                if parts:
                    transcript.append(f"{role}: {' '.join(parts)}")

        if not transcript:
            raise ProviderError(
                "Antigravity received no supported text content."
            )

        user_input = (
            "Respond to the conversation below as a text assistant. "
            "Do not execute code, access files, browse the web, or call tools. "
            "Provide the answer directly.\n\n"
            + "\n\n".join(transcript)
        )

        agent_config: dict[str, Any] = {
            "type": "antigravity",
            "max_total_tokens": self._max_total_tokens,
        }

        if self._model:
            agent_config["model"] = self._model

        request_body = {
            "agent": self._agent,
            "input": user_input,
            "environment": "remote",
            "agent_config": agent_config,
        }

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_s
            ) as client:
                response = await client.post(
                    self._url,
                    json=request_body,
                    headers=headers,
                )
                response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code

            # Do not log the response body, API key, or prompt.
            logger.warning(
                "Antigravity returned HTTP %s.",
                status_code,
            )
            raise ProviderError(
                f"Antigravity returned HTTP {status_code}."
            ) from exc

        except httpx.HTTPError as exc:
            logger.warning(
                "Antigravity transport failure: %s.",
                type(exc).__name__,
            )
            raise ProviderError(
                f"Antigravity request failed: {type(exc).__name__}."
            ) from exc

        try:
            result = response.json()
        except ValueError as exc:
            raise ProviderError(
                "Antigravity returned a non-JSON response."
            ) from exc

        if not isinstance(result, dict):
            raise ProviderError(
                "Antigravity returned an invalid response format."
            )

        status = result.get("status")

        if status != "completed":
            # Log only bounded diagnostic metadata, not prompt contents.
            logger.warning(
                "Antigravity interaction incomplete: status=%r, "
                "usage=%r, error_present=%s",
                status,
                result.get("usage"),
                bool(result.get("error")),
            )

            raise ProviderError(
                f"Antigravity interaction did not complete "
                f"(status={status!r}). Check gateway logs for diagnostics."
            )

        # Extract text only from model-output steps.
        output_parts: list[str] = []
        steps = result.get("steps", [])

        if isinstance(steps, list):
            for step in steps:
                if (
                    not isinstance(step, dict)
                    or step.get("type") != "model_output"
                ):
                    continue

                content = step.get("content", [])
                if not isinstance(content, list):
                    continue

                for item in content:
                    if (
                        isinstance(item, dict)
                        and isinstance(item.get("text"), str)
                    ):
                        output_parts.append(item["text"])

        output_text = "\n".join(
            part for part in output_parts if part.strip()
        ).strip()

        if not output_text:
            raise ProviderError(
                "Antigravity completed without returning assistant text."
            )

        # Antigravity usage fields use total_input_tokens and
        # total_output_tokens. Support alternate names defensively.
        upstream_usage = result.get("usage")
        usage = upstream_usage if isinstance(upstream_usage, dict) else {}

        def token_count(*keys: str) -> int:
            for key in keys:
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    if value >= 0:
                        return value
            return 0

        input_tokens = token_count(
            "total_input_tokens",
            "input_tokens",
            "prompt_tokens",
        )
        output_tokens = token_count(
            "total_output_tokens",
            "output_tokens",
            "completion_tokens",
        )
        total_tokens = token_count("total_tokens")

        if total_tokens == 0:
            total_tokens = input_tokens + output_tokens

        response_agent = result.get("agent")
        agent_label = (
            response_agent
            if isinstance(response_agent, str) and response_agent
            else self._agent
        )

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            # This identifies the configured agent/model label, not
            # independently verified identity of the internal model.
            "model": self._model or agent_label,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": output_text,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": total_tokens,
            },
            "provider_metadata": {
                "provider": self.provider_name,
                "agent": agent_label,
                "configured_model": self._model,
                "actual_model": None,
                "model_identity_verified": False,
                "usage_available": bool(usage),
            },
        }
