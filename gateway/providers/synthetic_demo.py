"""Deterministic local provider for the public governance demo.

This provider never performs network requests. Its output is intentionally
synthetic; responses still pass through the normal governance pipeline.
"""

from __future__ import annotations

import uuid
from typing import Any

from gateway.providers.base import Provider


class SyntheticDemoProvider(Provider):
    """Return deterministic OpenAI-compatible completions without an LLM API."""

    async def chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = payload.get("messages", [])
        prompt = " ".join(
            message.get("content", "")
            for message in messages
            if isinstance(message, dict) and isinstance(message.get("content"), str)
        ).lower()

        if "password" in prompt or "reset" in prompt:
            content = (
                "Use the official password-reset flow and verify identity through the "
                "registered recovery channel. Never share a password or one-time code "
                "with support staff. If recovery fails, escalate through the approved "
                "account-recovery process."
            )
        elif "financial transfer" in prompt or "unverified account" in prompt or "transfer" in prompt:
            content = (
                "Do not execute the transfer yet. Verify the account holder's identity, "
                "account ownership, and authorization using approved procedures. If any "
                "check fails or remains uncertain, pause the transaction and escalate "
                "for human review."
            )
        elif "unverified claim" in prompt or "established fact" in prompt or "claim" in prompt:
            content = (
                "An unverified claim should be labeled as unconfirmed, not stated as fact. "
                "Check the original source and corroborate it with independent evidence. "
                "For example, treat an unsourced sales estimate as a hypothesis until "
                "reliable records support it."
            )
        else:
            content = (
                "This is a synthetic ControlPlane demo response. Validate the relevant "
                "facts and authorization against approved sources before taking action."
            )

        return {
            "id": f"chatcmpl-demo-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": 0,
            "model": "controlplane-synthetic-demo",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
