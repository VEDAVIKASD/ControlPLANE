from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from gateway.providers.base import Provider, ProviderError


class AntigravityProvider(Provider):
    """Adapts the Antigravity Interactions API to ControlPlane's chat interface.

    Antigravity selects an agent, so model-routing requests cannot be assumed
    to switch underlying models unless the upstream service confirms that.
    """

    provider_name = "antigravity"
    supports_model_routing = False

    def __init__(
        self,
        api_key: str,
        agent: str = "antigravity-preview-09-2026",
        model: str | None = None,
        max_total_tokens: int = 12000,
        timeout_s: float = 120.0,
    ):
        self._api_key = api_key.strip()
        self._agent = agent.strip()
        self._model = model.strip() if model else None
        self._max_total_tokens = max_total_tokens
        self._timeout_s = timeout_s
        self._url = "https://generativelanguage.googleapis.com/v1beta/interactions"

    async def chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            raise ProviderError(
                "Antigravity is not configured: UPSTREAM_API_KEY is missing."
            )

        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ProviderError("Antigravity requires a non-empty messages list.")

        # Convert the chat history to a plain-text transcript.
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
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and isinstance(item.get("text"), str)
                ]
                if parts:
                    transcript.append(f"{role}: {' '.join(parts)}")

        if not transcript:
            raise ProviderError("Antigravity received no supported text content.")

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
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(
                    self._url,
                    json=request_body,
                    headers=headers,
                )
            response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            # Do not expose upstream response bodies or credentials to clients.
            raise ProviderError(f"Antigravity returned HTTP {status}.") from exc

        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Antigravity request failed: {type(exc).__name__}."
            ) from exc

        try:
            result = response.json()
        except ValueError as exc:
            raise ProviderError("Antigravity returned a non-JSON response.") from exc

        if not isinstance(result, dict):
            raise ProviderError("Antigravity returned an invalid response format.")

        status = result.get("status")
        if status != "completed":
            raise ProviderError(
                f"Antigravity interaction did not complete (status={status!r})."
            )

        # Extract text only from model-output steps. Do not expose tool results
        # or treat an incomplete interaction as a valid assistant answer.
        output_parts: list[str] = []
        steps = result.get("steps", [])

        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict) or step.get("type") != "model_output":
                    continue

                content = step.get("content", [])
                if not isinstance(content, list):
                    continue

                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        output_parts.append(item["text"])

        output_text = "\n".join(part for part in output_parts if part.strip()).strip()

        if not output_text:
            raise ProviderError(
                "Antigravity completed without returning assistant text."
            )

        now = int(time.time())
        # The Interactions response identifies the agent, not necessarily the
        # internal model selected by that agent. Keep those concepts separate.
        response_agent = result.get("agent")
        configured_model = self._model
        upstream_usage = result.get("usage")
        usage = upstream_usage if isinstance(upstream_usage, dict) else {}

        def token_count(*keys: str) -> int:
            for key in keys:
                value = usage.get(key)
                if isinstance(value, int) and value >= 0:
                    return value
            return 0

        input_tokens = token_count("input_tokens", "prompt_tokens")
        output_tokens = token_count("output_tokens", "completion_tokens")
        total_tokens = token_count("total_tokens") or (input_tokens + output_tokens)

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": now,
            # OpenAI-compatible field; this is the configured agent/model label,
            # not proof of the internal model used by Antigravity.
            "model": configured_model or str(response_agent or self._agent),
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
                "agent": str(response_agent or self._agent),
                "configured_model": configured_model,
                "actual_model": None,
                "model_identity_verified": False,
                "usage_available": bool(usage),
            },
        }
