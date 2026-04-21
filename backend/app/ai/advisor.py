"""
AI client for the Options Screener — runs on your Claude Max subscription
via the Claude Agent SDK (no API key or separate billing required).

Note: The advisor_20260301 server-side tool from the Anthropic blog post
requires direct API access and cannot be used here. This module provides
equivalent functionality using the Agent SDK, which is covered by your
Max subscription through the Claude Code CLI.

Usage:
    import asyncio
    from app.ai.advisor import ask

    result = asyncio.run(ask("Screen for high-IV options expiring this week."))
    print(result)
"""

import anyio
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage  # pip install claude-agent-sdk


SYSTEM_PROMPT = (
    "You are an expert options trading assistant. "
    "You help screen, analyse, and explain options strategies. "
    "Be concise and precise. Always state assumptions and data limitations."
)


async def _run(prompt: str, system: str | None = None) -> str:
    """Internal async runner."""
    collected = []
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            system_prompt=system or SYSTEM_PROMPT,
        ),
    ):
        if isinstance(message, ResultMessage):
            collected.append(message.result)
    return "\n".join(collected)


def ask(prompt: str, system: str | None = None) -> str:
    """
    Send a prompt to Claude and return the response as a string.

    Runs on your Max subscription — no API key needed.

    Args:
        prompt: The question or instruction.
        system: Optional system prompt override.

    Returns:
        Claude's response as a plain string.

    Example:
        from app.ai.advisor import ask
        print(ask("What is a good IV rank threshold for selling covered calls?"))
    """
    return anyio.run(_run, prompt, system)
