from __future__ import annotations

import re
from dataclasses import dataclass

from agent_core import AgentCore


@dataclass(frozen=True)
class SkillInfo:
    key: str
    name: str
    status: str
    description: str
    commands: tuple[str, ...] = ()


INSTALLED_SKILLS = (
    SkillInfo("memory", "Personal Memory", "active", "Stores conversation history and selected personal facts in local SQLite memory.", ("remember facts", "recall stored facts")),
    SkillInfo("language", "Teacher-Student Language Layer", "active", "Understands English, Malayalam and Manglish; unknown Manglish can be taught by Gemini and reused locally.", ("/teacher-stats",)),
    SkillInfo("git", "Git Operator v1", "active", "Deterministic allow-listed Git operations with branch and conflict safety; no arbitrary shell execution.", ("git status nokku", "git pull cheyyu", "changes nokku", "ith stage cheyyu", 'commit message "..." vechu commit cheyyu', "githubilek push cheyyu", "current branch", "recent commits", "conflicts nokku", "test-safe branch create cheyyu", "main branchilek switch cheyyu")),
    SkillInfo("agent-core", "Agent Core v1", "active", "Structured understand-plan-tool-verify orchestration with an explicit tool allowlist and confirmation gate for mutations.", ("/agent tools", "/agent plan <goal>", "/agent run <goal>", "/agent confirm")),
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


def render_skill_list() -> str:
    lines = ["NEXA installed/active skills:"]
    for index, skill in enumerate(INSTALLED_SKILLS, start=1):
        lines.append(f"{index}. {skill.name} [{skill.status}] - {skill.description}")
        if skill.commands:
            lines.append("   Commands: " + "; ".join(skill.commands))
    lines.append("Planned skills are not shown as installed. NEXA should never invent skills that are not registered here.")
    return "\n".join(lines)


_AGENT = AgentCore()


def handle_agent_command(text: str) -> str | None:
    normalized = text.strip()
    lower = normalized.lower()
    if lower in {"/agent tools", "agent tools", "agent core tools"}:
        return _AGENT.describe()
    match = re.match(r"^/agent\s+plan\s+(.+)$", normalized, flags=re.IGNORECASE)
    if match:
        plan = _AGENT.plan(match.group(1))
        lines = [f"Agent plan for: {plan.task.goal}"]
        for index, step in enumerate(plan.steps, start=1):
            suffix = f" -> {step.tool}" if step.tool else ""
            gate = " [confirmation required]" if step.mutating else ""
            lines.append(f"{index}. {step.kind.value}: {step.description}{suffix}{gate}")
        return "\n".join(lines)
    return None


def handle_skill_command(text: str) -> str | None:
    agent_reply = handle_agent_command(text)
    if agent_reply is not None:
        return agent_reply
    if is_skill_list_request(text):
        return render_skill_list()
    return None
