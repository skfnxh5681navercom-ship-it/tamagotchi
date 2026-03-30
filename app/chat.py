from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable, Awaitable
import asyncio
import time
import uuid


@dataclass
class ChatMessage:
    id: str
    channel: str
    sender_id: str
    sender_name: str
    sender_emoji: str
    content: str
    timestamp: float
    msg_type: str = "text"  # text, system, deliverable

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Meeting:
    id: str
    topic: str
    agent_ids: list[str]
    channel: str
    active: bool = True
    round_count: int = 0


@dataclass
class CollabSession:
    id: str
    task: str
    agent_ids: list[str]
    channel: str
    total_rounds: int = 3
    current_round: int = 0
    active: bool = True
    deliverable: str = ""


BroadcastFn = Callable[[dict], Awaitable[None]]


class ChatManager:
    def __init__(self):
        self.channels: dict[str, list[ChatMessage]] = {"general": []}
        self.meetings: dict[str, Meeting] = {}
        self.collabs: dict[str, CollabSession] = {}
        self._broadcast: Optional[BroadcastFn] = None
        self._collab_tasks: dict[str, asyncio.Task] = {}

    def set_broadcast(self, fn: BroadcastFn):
        self._broadcast = fn

    def add_message(
        self,
        channel: str,
        sender_id: str,
        sender_name: str,
        sender_emoji: str,
        content: str,
        msg_type: str = "text",
    ) -> ChatMessage:
        if channel not in self.channels:
            self.channels[channel] = []

        msg = ChatMessage(
            id=str(uuid.uuid4()),
            channel=channel,
            sender_id=sender_id,
            sender_name=sender_name,
            sender_emoji=sender_emoji,
            content=content,
            timestamp=time.time(),
            msg_type=msg_type,
        )
        self.channels[channel].append(msg)

        # Keep channel history manageable
        if len(self.channels[channel]) > 200:
            self.channels[channel] = self.channels[channel][-200:]

        return msg

    def get_messages(self, channel: str, limit: int = 50) -> list[dict]:
        msgs = self.channels.get(channel, [])
        return [m.to_dict() for m in msgs[-limit:]]

    def create_meeting(self, topic: str, agent_ids: list[str]) -> Meeting:
        meeting_id = str(uuid.uuid4())[:8]
        channel = f"meeting:{meeting_id}"
        self.channels[channel] = []
        meeting = Meeting(
            id=meeting_id,
            topic=topic,
            agent_ids=agent_ids,
            channel=channel,
        )
        self.meetings[meeting_id] = meeting
        return meeting

    def end_meeting(self, meeting_id: str) -> Optional[Meeting]:
        meeting = self.meetings.get(meeting_id)
        if meeting:
            meeting.active = False
        return meeting

    def create_collab(self, task: str, agent_ids: list[str], rounds: int = 3) -> CollabSession:
        collab_id = str(uuid.uuid4())[:8]
        channel = f"collab:{collab_id}"
        self.channels[channel] = []
        collab = CollabSession(
            id=collab_id,
            task=task,
            agent_ids=agent_ids,
            channel=channel,
            total_rounds=rounds,
        )
        self.collabs[collab_id] = collab
        return collab

    def end_collab(self, collab_id: str) -> Optional[CollabSession]:
        collab = self.collabs.get(collab_id)
        if collab:
            collab.active = False
            task = self._collab_tasks.pop(collab_id, None)
            if task:
                task.cancel()
        return collab
