from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SkillInfo:
    key: str
    name: str
    status: str
    description: str
    commands: tuple[str, ...] = ()


INSTALLED_SKILLS = (
    SkillInfo(
        key="memory",
        name="Personal Memory",
        status="active",
        description="Stores conversation history and selected personal facts in local SQLite memory.",
        commands=("remember facts", "recall stored facts"),
    ),
    SkillInfo(
        key="language",
        name="Teacher-Student Language Layer",
        status="active",
        description="Understands English, Malayalam and Manglish; unknown Manglish can be taught by Gemini and reused locally.",
        commands=("/teacher-stats",),
    ),
    SkillInfo(
        key="git",
        name="Git Operator v1",
        status="active",
        description="Deterministic allow-listed Git operations with branch and conflict safety; no arbitrary shell execution.",
        commands=(
            "git status nokku",
            "git pull cheyyu",
            "changes nokku",
            "ith stage cheyyu",
            'commit message "..." vechu commit cheyyu',
            "githubilek push cheyyu",
            "current branch",
            "recent commits",
            "conflicts nokku",
            "test-safe branch create cheyyu",
            "main branchilek switch cheyyu",
        ),
    ),
)


# Accept the correct spelling (`skill`/`skills`) and the common user typo
# (`skil`/`skils`) so the deterministic registry still catches the request.
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


def render_skill_list() -> str:
    lines = ["NEXA installed/active skills:"]
    for index, skill in enumerate(INSTALLED_SKILLS, start=1):
        lines.append(f"{index}. {skill.name} [{skill.status}] - {skill.description}")
        if skill.commands:
            lines.append("   Commands: " + "; ".join(skill.commands))

    lines.append(
        "Planned skills are not shown as installed. NEXA should never invent skills that are not registered here."
    )
    return "\n".join(lines)


def handle_skill_command(text: str) -> str | None:
    if is_skill_list_request(text):
        return render_skill_list()
    return None
