from __future__ import annotations
import os
import anthropic
from typing import AsyncIterator
from app.office import Character


class AgentBrain:
    def __init__(self, agent: Character):
        self.agent = agent
        self.client = anthropic.AsyncAnthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        )
        self.histories: dict[str, list[dict]] = {}
        self.max_history = 40

    def _get_history(self, channel_id: str) -> list[dict]:
        if channel_id not in self.histories:
            self.histories[channel_id] = []
        return self.histories[channel_id]

    def _trim_history(self, channel_id: str):
        history = self._get_history(channel_id)
        if len(history) > self.max_history:
            self.histories[channel_id] = history[-self.max_history:]

    def add_message(self, channel_id: str, role: str, name: str, content: str):
        history = self._get_history(channel_id)
        if role == "assistant" and name == self.agent.name:
            history.append({"role": "assistant", "content": content})
        else:
            prefix = f"[{name}]: " if name else ""
            history.append({"role": "user", "content": f"{prefix}{content}"})
        self._trim_history(channel_id)

    async def respond(self, channel_id: str) -> AsyncIterator[str]:
        history = self._get_history(channel_id)
        if not history:
            return

        messages = list(history)
        # Ensure messages alternate properly - merge consecutive same-role messages
        merged = []
        for msg in messages:
            if merged and merged[-1]["role"] == msg["role"]:
                merged[-1]["content"] += "\n" + msg["content"]
            else:
                merged.append(dict(msg))

        # Ensure first message is from user
        if merged and merged[0]["role"] == "assistant":
            merged.insert(0, {"role": "user", "content": "[System]: Conversation started."})

        try:
            async with self.client.messages.stream(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=self.agent.system_prompt,
                messages=merged,
            ) as stream:
                full_response = ""
                async for text in stream.text_stream:
                    full_response += text
                    yield text

                # Add the full response to history
                history.append({"role": "assistant", "content": full_response})
                self._trim_history(channel_id)

        except anthropic.APIError as e:
            error_msg = f"(I'm having trouble responding right now: {e.message})"
            history.append({"role": "assistant", "content": error_msg})
            yield error_msg

    async def respond_once(self, channel_id: str) -> str:
        """Non-streaming response, returns full text."""
        chunks = []
        async for chunk in self.respond(channel_id):
            chunks.append(chunk)
        return "".join(chunks)
