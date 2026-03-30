from app.office import Character


EMOJI_OPTIONS = [
    "\ud83d\udcbb", "\ud83c\udfa8", "\ud83d\udccb", "\ud83d\udd0d", "\ud83d\udcca",
    "\ud83d\ude80", "\ud83e\udde0", "\ud83d\udca1", "\ud83d\udd27", "\ud83c\udfaf",
    "\ud83d\udcdd", "\ud83e\udd16", "\ud83e\uddea", "\ud83d\udce6", "\ud83c\udf10",
]

_agent_counter = 0


def generate_agent_position(index: int) -> tuple[int, int]:
    """Generate a position in the workspace for a new agent."""
    col = index % 3
    row = index // 3
    return 80 + col * 120, 80 + row * 100


def build_system_prompt(name: str, role: str, personality: str) -> str:
    return (
        f"You are {name}, a {role} in a virtual office. "
        f"Your personality: {personality}. "
        f"Stay in character. In meetings, contribute from your role's perspective. "
        f"In collaboration, add concrete value based on your expertise. "
        f"Keep responses concise (2-4 sentences in chat, longer for deliverables). "
        f"Respond in the same language the user or other agents are using."
    )


def create_agent(name: str, role: str, emoji: str, personality: str, index: int) -> Character:
    global _agent_counter
    agent_id = f"agent_{_agent_counter}"
    _agent_counter += 1
    x, y = generate_agent_position(index)

    return Character(
        id=agent_id,
        name=name,
        role=role,
        emoji=emoji,
        x=x,
        y=y,
        personality=personality,
        system_prompt=build_system_prompt(name, role, personality),
    )
