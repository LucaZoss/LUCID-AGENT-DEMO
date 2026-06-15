"""
LLMProvider — the ONLY interface through which the agent talks to any LLM.

Vendor SDK imports (anthropic, openai, …) are permitted ONLY inside
llm/adapters/<name>_adapter.py. Nothing else in the codebase should import
a vendor SDK directly.

Contract
--------
  complete(system, messages, tools=None, **kwargs) -> LLMResponse

  * system   — the full system prompt as a single string
  * messages — list of {role, content} dicts in OpenAI-style format;
               tool results use role="tool" with a "tool_call_id" key
  * tools    — optional list of JSON-schema function definitions
               (OpenAI tool-calling format; adapters translate as needed)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    # 'end_turn' when the model is done; 'tool_use' when it wants to call tools
    stop_reason: str = "end_turn"


class LLMProvider(ABC):

    @abstractmethod
    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Send a request to the LLM and return a structured response.

        Implementations must translate vendor-specific response shapes into
        LLMResponse so the rest of the agent never sees vendor types.
        """
