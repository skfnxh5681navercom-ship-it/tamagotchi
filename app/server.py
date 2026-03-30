from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.office import OfficeState, Character
from app.agents import create_agent, EMOJI_OPTIONS
from app.chat import ChatManager
from app.claude_client import AgentBrain

app = FastAPI(title="Virtual Office")

# Global state
office = OfficeState()
chat_mgr = ChatManager()
agent_brains: dict[str, AgentBrain] = {}
active_connections: list[WebSocket] = []
user_character: Character | None = None


async def broadcast(data: dict):
    """Send a message to all connected WebSocket clients."""
    dead = []
    msg = json.dumps(data, ensure_ascii=False)
    for ws in active_connections:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        active_connections.remove(ws)


chat_mgr.set_broadcast(broadcast)


# --- REST Endpoints ---

STATIC_DIR = Path(__file__).parent.parent / "static"


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/office")
async def get_office():
    return office.get_state()


# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global user_character
    await ws.accept()
    active_connections.append(ws)

    try:
        # Send current state
        await ws.send_text(json.dumps({
            "type": "office_update",
            **office.get_state(),
        }, ensure_ascii=False))

        # Send emoji options
        await ws.send_text(json.dumps({
            "type": "emoji_options",
            "emojis": EMOJI_OPTIONS,
        }, ensure_ascii=False))

        # Send existing general chat
        await ws.send_text(json.dumps({
            "type": "history",
            "channel": "general",
            "messages": chat_mgr.get_messages("general"),
        }, ensure_ascii=False))

        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")

            if msg_type == "login":
                await handle_login(ws, data)
            elif msg_type == "chat":
                await handle_chat(ws, data)
            elif msg_type == "add_agent":
                await handle_add_agent(ws, data)
            elif msg_type == "remove_agent":
                await handle_remove_agent(ws, data)
            elif msg_type == "meeting_start":
                await handle_meeting_start(ws, data)
            elif msg_type == "meeting_end":
                await handle_meeting_end(ws, data)
            elif msg_type == "collab_start":
                await handle_collab_start(ws, data)
            elif msg_type == "collab_end":
                await handle_collab_end(ws, data)
            elif msg_type == "move":
                await handle_move(ws, data)

    except WebSocketDisconnect:
        active_connections.remove(ws)
    except Exception:
        if ws in active_connections:
            active_connections.remove(ws)


async def handle_login(ws: WebSocket, data: dict):
    global user_character
    name = data.get("name", "User")

    user_character = Character(
        id="user",
        name=name,
        role="Boss",
        emoji="\ud83d\udc64",
        x=320,
        y=180,
        is_user=True,
    )
    office.add_character(user_character)

    msg = chat_mgr.add_message(
        "general", "system", "System", "\u2699\ufe0f",
        f"{name} has entered the office!",
        msg_type="system",
    )
    await broadcast({"type": "office_update", **office.get_state()})
    await broadcast({"type": "chat", "message": msg.to_dict()})


async def handle_add_agent(ws: WebSocket, data: dict):
    name = data.get("name", "").strip()
    role = data.get("role", "").strip()
    emoji = data.get("emoji", "\ud83e\udd16")
    personality = data.get("personality", "").strip()

    if not name or not role:
        return

    index = len(agent_brains)
    agent = create_agent(name, role, emoji, personality or f"a skilled {role}")
    office.add_character(agent)
    agent_brains[agent.id] = AgentBrain(agent)

    # Reposition all agents neatly
    for i, aid in enumerate(agent_brains):
        from app.agents import generate_agent_position
        x, y = generate_agent_position(i)
        office.move_character(aid, x, y)

    msg = chat_mgr.add_message(
        "general", "system", "System", "\u2699\ufe0f",
        f"{emoji} {name} ({role}) has joined the office!",
        msg_type="system",
    )
    await broadcast({"type": "office_update", **office.get_state()})
    await broadcast({"type": "chat", "message": msg.to_dict()})


async def handle_remove_agent(ws: WebSocket, data: dict):
    agent_id = data.get("agent_id", "")
    if agent_id not in agent_brains:
        return

    agent = office.characters.get(agent_id)
    name = agent.name if agent else agent_id

    office.remove_character(agent_id)
    del agent_brains[agent_id]

    # Reposition remaining agents
    for i, aid in enumerate(agent_brains):
        from app.agents import generate_agent_position
        x, y = generate_agent_position(i)
        office.move_character(aid, x, y)

    msg = chat_mgr.add_message(
        "general", "system", "System", "\u2699\ufe0f",
        f"{name} has left the office.",
        msg_type="system",
    )
    await broadcast({"type": "office_update", **office.get_state()})
    await broadcast({"type": "chat", "message": msg.to_dict()})


async def handle_chat(ws: WebSocket, data: dict):
    channel = data.get("channel", "general")
    content = data.get("content", "")
    if not content or not user_character:
        return

    msg = chat_mgr.add_message(
        channel, user_character.id, user_character.name, user_character.emoji, content
    )
    await broadcast({"type": "chat", "message": msg.to_dict()})

    for aid, brain in agent_brains.items():
        brain.add_message(channel, "user", user_character.name, content)

    responding_agents = _get_responding_agents(channel)

    for agent_id in responding_agents:
        if agent_id not in agent_brains:
            continue
        brain = agent_brains[agent_id]
        agent = office.characters[agent_id]

        await broadcast({
            "type": "typing",
            "channel": channel,
            "sender_id": agent_id,
            "sender_name": agent.name,
        })

        full_text = ""
        async for chunk in brain.respond(channel):
            full_text += chunk
            await broadcast({
                "type": "chat_stream",
                "channel": channel,
                "sender_id": agent_id,
                "sender_name": agent.name,
                "sender_emoji": agent.emoji,
                "delta": chunk,
            })

        completed_msg = chat_mgr.add_message(
            channel, agent_id, agent.name, agent.emoji, full_text
        )
        await broadcast({
            "type": "chat_stream_end",
            "channel": channel,
            "sender_id": agent_id,
            "message": completed_msg.to_dict(),
        })

        for other_id, other_brain in agent_brains.items():
            if other_id != agent_id:
                other_brain.add_message(channel, "assistant", agent.name, full_text)


def _get_responding_agents(channel: str) -> list[str]:
    if not agent_brains:
        return []

    if channel == "general":
        import random
        agent_ids = list(agent_brains.keys())
        count = random.randint(1, min(2, len(agent_ids)))
        return random.sample(agent_ids, count)

    elif channel.startswith("dm:"):
        parts = channel.split(":")
        target = parts[2] if len(parts) > 2 else parts[1]
        return [target] if target in agent_brains else []

    elif channel.startswith("meeting:"):
        meeting_id = channel.split(":")[1]
        meeting = chat_mgr.meetings.get(meeting_id)
        if meeting and meeting.active:
            return [aid for aid in meeting.agent_ids if aid in agent_brains]
        return []

    return []


async def handle_meeting_start(ws: WebSocket, data: dict):
    topic = data.get("topic", "General Discussion")
    agent_ids = data.get("agents", [])

    if not agent_ids:
        agent_ids = list(agent_brains.keys())

    # Filter to only existing agents
    agent_ids = [aid for aid in agent_ids if aid in agent_brains]
    if not agent_ids:
        return

    meeting = chat_mgr.create_meeting(topic, agent_ids)

    all_ids = agent_ids + (["user"] if user_character else [])
    office.move_to_meeting(all_ids, "meeting-a")

    agent_names = ", ".join(
        office.characters[aid].name for aid in agent_ids if aid in office.characters
    )
    sys_msg = chat_mgr.add_message(
        meeting.channel, "system", "System", "\u2699\ufe0f",
        f"Meeting started: '{topic}'\nParticipants: {agent_names}",
        msg_type="system",
    )

    for aid in agent_ids:
        if aid in agent_brains:
            agent_brains[aid].add_message(
                meeting.channel, "user", "System",
                f"A meeting has started. Topic: '{topic}'. "
                f"Participants: {agent_names}. "
                f"Please contribute to the discussion from your perspective as a {office.characters[aid].role}."
            )

    await broadcast({"type": "office_update", **office.get_state()})
    await broadcast({
        "type": "meeting_started",
        "meeting": {
            "id": meeting.id,
            "topic": meeting.topic,
            "channel": meeting.channel,
            "agent_ids": meeting.agent_ids,
        },
    })
    await broadcast({"type": "chat", "message": sys_msg.to_dict()})


async def handle_meeting_end(ws: WebSocket, data: dict):
    meeting_id = data.get("meeting_id")
    if not meeting_id:
        return

    meeting = chat_mgr.end_meeting(meeting_id)
    if not meeting:
        return

    all_ids = meeting.agent_ids + (["user"] if user_character else [])
    office.return_from_meeting(all_ids)

    sys_msg = chat_mgr.add_message(
        meeting.channel, "system", "System", "\u2699\ufe0f",
        "Meeting ended.",
        msg_type="system",
    )

    await broadcast({"type": "office_update", **office.get_state()})
    await broadcast({"type": "chat", "message": sys_msg.to_dict()})
    await broadcast({"type": "meeting_ended", "meeting_id": meeting_id})


async def handle_collab_start(ws: WebSocket, data: dict):
    task = data.get("task", "")
    agent_ids = data.get("agents", [])
    rounds = data.get("rounds", 3)

    if not task or not agent_ids:
        return

    agent_ids = [aid for aid in agent_ids if aid in agent_brains]
    if not agent_ids:
        return

    collab = chat_mgr.create_collab(task, agent_ids, rounds)

    for aid in agent_ids:
        office.set_status(aid, "working")

    agent_names = ", ".join(
        office.characters[aid].name for aid in agent_ids if aid in office.characters
    )
    sys_msg = chat_mgr.add_message(
        collab.channel, "system", "System", "\u2699\ufe0f",
        f"Collaboration started!\nTask: {task}\nTeam: {agent_names}\nRounds: {rounds}",
        msg_type="system",
    )

    await broadcast({"type": "office_update", **office.get_state()})
    await broadcast({
        "type": "collab_started",
        "collab": {
            "id": collab.id,
            "task": collab.task,
            "channel": collab.channel,
            "agent_ids": collab.agent_ids,
            "total_rounds": collab.total_rounds,
        },
    })
    await broadcast({"type": "chat", "message": sys_msg.to_dict()})

    task_handle = asyncio.create_task(_run_collab(collab))
    chat_mgr._collab_tasks[collab.id] = task_handle


async def _run_collab(collab):
    try:
        for aid in collab.agent_ids:
            if aid in agent_brains:
                agent_brains[aid].add_message(
                    collab.channel, "user", "System",
                    f"You are participating in a collaboration session.\n"
                    f"Task: {collab.task}\n"
                    f"You will take turns contributing. Build on what others say. "
                    f"Be constructive and add concrete value with each contribution."
                )

        for round_num in range(1, collab.total_rounds + 1):
            if not collab.active:
                break

            collab.current_round = round_num
            await broadcast({
                "type": "collab_round",
                "collab_id": collab.id,
                "round": round_num,
                "total": collab.total_rounds,
            })

            for agent_id in collab.agent_ids:
                if not collab.active:
                    break
                if agent_id not in agent_brains:
                    continue

                brain = agent_brains[agent_id]
                agent = office.characters[agent_id]

                await broadcast({
                    "type": "typing",
                    "channel": collab.channel,
                    "sender_id": agent_id,
                    "sender_name": agent.name,
                })

                full_text = ""
                async for chunk in brain.respond(collab.channel):
                    full_text += chunk
                    await broadcast({
                        "type": "chat_stream",
                        "channel": collab.channel,
                        "sender_id": agent_id,
                        "sender_name": agent.name,
                        "sender_emoji": agent.emoji,
                        "delta": chunk,
                    })

                completed_msg = chat_mgr.add_message(
                    collab.channel, agent_id, agent.name, agent.emoji, full_text
                )
                await broadcast({
                    "type": "chat_stream_end",
                    "channel": collab.channel,
                    "sender_id": agent_id,
                    "message": completed_msg.to_dict(),
                })

                for other_id in collab.agent_ids:
                    if other_id != agent_id and other_id in agent_brains:
                        agent_brains[other_id].add_message(
                            collab.channel, "user", agent.name, full_text
                        )

                await asyncio.sleep(0.5)

        # Summarize - use the first agent
        if collab.active:
            summarizer_id = collab.agent_ids[0]
            brain = agent_brains[summarizer_id]
            agent = office.characters[summarizer_id]

            brain.add_message(
                collab.channel, "user", "System",
                "The collaboration rounds are complete. "
                "Please provide a final summary/deliverable that consolidates "
                "everything discussed. Format it clearly with sections and action items."
            )

            await broadcast({
                "type": "typing",
                "channel": collab.channel,
                "sender_id": summarizer_id,
                "sender_name": agent.name,
            })

            full_text = ""
            async for chunk in brain.respond(collab.channel):
                full_text += chunk
                await broadcast({
                    "type": "chat_stream",
                    "channel": collab.channel,
                    "sender_id": summarizer_id,
                    "sender_name": agent.name,
                    "sender_emoji": agent.emoji,
                    "delta": chunk,
                })

            deliverable_msg = chat_mgr.add_message(
                collab.channel, summarizer_id, agent.name, agent.emoji,
                full_text, msg_type="deliverable",
            )
            await broadcast({
                "type": "chat_stream_end",
                "channel": collab.channel,
                "sender_id": summarizer_id,
                "message": deliverable_msg.to_dict(),
            })

            collab.deliverable = full_text
            collab.active = False

            for aid in collab.agent_ids:
                office.set_status(aid, "idle")

            await broadcast({"type": "office_update", **office.get_state()})
            await broadcast({
                "type": "collab_complete",
                "collab_id": collab.id,
                "deliverable": full_text,
            })

    except asyncio.CancelledError:
        pass
    except Exception as e:
        error_msg = chat_mgr.add_message(
            collab.channel, "system", "System", "\u2699\ufe0f",
            f"Collaboration error: {str(e)}",
            msg_type="system",
        )
        await broadcast({"type": "chat", "message": error_msg.to_dict()})


async def handle_collab_end(ws: WebSocket, data: dict):
    collab_id = data.get("collab_id")
    if not collab_id:
        return

    collab = chat_mgr.end_collab(collab_id)
    if not collab:
        return

    for aid in collab.agent_ids:
        office.set_status(aid, "idle")

    await broadcast({"type": "office_update", **office.get_state()})
    await broadcast({"type": "collab_ended", "collab_id": collab_id})


async def handle_move(ws: WebSocket, data: dict):
    if not user_character:
        return
    x = data.get("x", user_character.x)
    y = data.get("y", user_character.y)
    office.move_character("user", x, y)
    await broadcast({"type": "office_update", **office.get_state()})
