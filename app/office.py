from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import time


@dataclass
class Room:
    id: str
    name: str
    x: int
    y: int
    width: int
    height: int
    room_type: str  # workspace, meeting, lounge

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.width and self.y <= py < self.y + self.height

    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


@dataclass
class Character:
    id: str
    name: str
    role: str
    emoji: str
    x: int
    y: int
    is_user: bool = False
    personality: str = ""
    status: str = "idle"  # idle, in-meeting, working
    system_prompt: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "system_prompt"}


OFFICE_ROOMS = [
    Room("workspace", "Main Workspace", 20, 20, 360, 260, "workspace"),
    Room("meeting-a", "Meeting Room A", 400, 20, 200, 120, "meeting"),
    Room("meeting-b", "Meeting Room B", 400, 160, 200, 120, "meeting"),
    Room("lounge", "Lounge", 20, 300, 580, 100, "lounge"),
]


class OfficeState:
    def __init__(self):
        self.rooms: list[Room] = list(OFFICE_ROOMS)
        self.characters: dict[str, Character] = {}
        self._saved_positions: dict[str, tuple[int, int]] = {}

    def add_character(self, char: Character):
        self.characters[char.id] = char

    def remove_character(self, char_id: str):
        self.characters.pop(char_id, None)

    def move_character(self, char_id: str, x: int, y: int):
        if char_id in self.characters:
            self.characters[char_id].x = x
            self.characters[char_id].y = y

    def set_status(self, char_id: str, status: str):
        if char_id in self.characters:
            self.characters[char_id].status = status

    def move_to_meeting(self, char_ids: list[str], room_id: str = "meeting-a"):
        room = next((r for r in self.rooms if r.id == room_id), None)
        if not room:
            return
        cx, cy = room.center()
        for i, cid in enumerate(char_ids):
            if cid in self.characters:
                self._saved_positions[cid] = (self.characters[cid].x, self.characters[cid].y)
                offset_x = (i % 3 - 1) * 50
                offset_y = (i // 3) * 40 - 20
                self.move_character(cid, cx + offset_x, cy + offset_y)
                self.set_status(cid, "in-meeting")

    def return_from_meeting(self, char_ids: list[str]):
        for cid in char_ids:
            if cid in self._saved_positions:
                x, y = self._saved_positions.pop(cid)
                self.move_character(cid, x, y)
            self.set_status(cid, "idle")

    def get_state(self) -> dict:
        return {
            "rooms": [asdict(r) for r in self.rooms],
            "characters": [c.to_dict() for c in self.characters.values()],
        }
