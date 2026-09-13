from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ServiceInfo:
    key: str
    name: str
    status: str
    description: str
    commands: tuple[str, ...] = ()


# Non-plugin services only. Executable tool capabilities are no longer duplicated
# here; the runtime core.SkillRegistry is the single source of truth for them.
BUILTIN_SERVICES = (
    ServiceInfo(
        key="memory",
        name="Personal Memory",
        status="active",
        description="Stores conversation history and selected personal facts in local SQLite memory.",
        commands=("remember facts", "recall stored facts"),
    ),
    ServiceInfo(
        key="language",
        name="Teacher-Student Language Layer",
        status="active",
        description="Understands English, Malayalam and Manglish; unknown Manglish can be taught by Gemini and reused locally.",
        commands=("/teacher-stats",),
    ),
)


SKILL_WORD = r"(?:skills?|skils?)"
SKILL_LIST_PATTERNS = (
    re.compile(r"^/skills$", re.IGNORECASE),
    re.compile(rf"^{SKILL_WORD}\s+list(?:\s+cheyyu|\s+cheythe|\s+cheyyamo)?$", re.IGNORECASE),
    re.compile(rf"^ninte\s+{SKILL_WORD}\s+list(?:\s+cheyyu|\s+cheythe|\s+cheyya)?$", re.IGNORECASE),
    re.compile(rf"^nexa(?:yude)?\s+{SKILL_WORD}\s+list(?:\s+cheyyu|\s+cheythe|\s+cheyya)?$", re.IGNORECASE),
    re.compile(rf"^enthoke\s+{SKILL_WORD}\s+undu\??$", re.IGNORECASE),
    re.compile(rf"^enthokke\s+{SKILL_WORD}\s+undu\??$", re.IGNORECASE),
)


def is_skill_list_request(text: str) -> bool:
    normalized = " ".join(text.strip().split())
    return any(pattern.fullmatch(normalized) for pattern in SKILL_LIST_PATTERNS)


def render_skill_list(registry: Any | None = None) -> str:
    lines = ["NEXA installed/active capabilities:"]

    if registry is None:
        lines.append("Kernel plugins: runtime registry not supplied.")
    else:
        lines.append("Kernel plugins:")
        for metadata in registry.list_metadata():
            lines.append(f"- {metadata.name} v{metadata.version} - {metadata.description}")
            for operation in metadata.operations:
                lines.append(f"  - {operation.name} [{operation.risk.value}]")

    lines.append("Built-in services:")
    for service in BUILTIN_SERVICES:
        lines.append(f"- {service.name} [{service.status}] - {service.description}")
        if service.commands:
            lines.append("  Commands: " + "; ".join(service.commands))

    lines.append("Executable plugins are reported only from the runtime registry; planned capabilities are not shown as installed.")
    return "\n".join(lines)


def handle_skill_command(text: str, registry: Any | None = None) -> str | None:
    if is_skill_list_request(text):
        return render_skill_list(registry)
    return None
