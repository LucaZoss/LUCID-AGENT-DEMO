"""
LiteLLMAdapter — LLMProvider backed by LiteLLM.

LiteLLM is the ONLY place in this file that touches a vendor SDK; it handles
provider routing internally. The rest of the app never sees anthropic/openai/…
imports because they stay inside LiteLLM's own modules.

Usage
-----
    from llm.adapters.litellm_adapter import LiteLLMAdapter

    llm = LiteLLMAdapter(model="claude-sonnet-4-6")
    response = llm.complete(system="...", messages=[...], tools=[...])

The model string follows LiteLLM conventions:
    "claude-sonnet-4-6"         → Anthropic Claude Sonnet 4.6 (via ANTHROPIC_API_KEY)
    "gpt-4o"                    → OpenAI (via OPENAI_API_KEY)
    "ollama/llama3"             → local Ollama instance

Set the appropriate API-key environment variable before calling.
"""

from __future__ import annotations

import json

import litellm

from llm.provider import LLMProvider, LLMResponse, ToolCall

# Silence LiteLLM's verbose success logging by default.
litellm.success_callback = []
litellm.failure_callback = []


class LiteLLMAdapter(LLMProvider):

    def __init__(self, model: str = "claude-sonnet-4-6", **default_kwargs):
        self.model = model
        self._default_kwargs = default_kwargs

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        all_messages = [{"role": "system", "content": system}, *messages]

        call_kwargs: dict = {**self._default_kwargs, **kwargs}
        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = "auto"

        response = litellm.completion(
            model=self.model,
            messages=all_messages,
            **call_kwargs,
        )

        choice = response.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                ))

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
        )
