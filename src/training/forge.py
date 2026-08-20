from __future__ import annotations

import json
from typing import Any, Mapping, Protocol

from bridges import GeminiBridge

from .models import CandidateRisk, SkillCandidate, TrainingNeed


class StructuredTeacher(Protocol):
    def generate_json(
        self,
        prompt: str,
        schema: Mapping[str, Any],
        *,
        system_instruction: str | None = None,
    ) -> dict[str, Any]:
        ...


_CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["name", "description", "risk", "skill_py", "test_py", "intents", "teacher_notes"],
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "risk": {
            "type": "string",
            "enum": [item.value for item in CandidateRisk],
        },
        "skill_py": {"type": "string"},
        "test_py": {"type": "string"},
        "intents": {"type": "array", "items": {"type": "string"}},
        "teacher_notes": {"type": "string"},
    },
}

_REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["skill_py", "test_py", "teacher_notes"],
    "properties": {
        "skill_py": {"type": "string"},
        "test_py": {"type": "string"},
        "teacher_notes": {"type": "string"},
    },
}


class TeacherSkillForge:
    """Gemini-backed curriculum/skill generator.

    The forge only returns candidate source text. It cannot write files, register
    plugins, execute code, change kernel policy, or access secrets. All generated
    Python must pass the sandbox before any promotion decision is possible.
    """

    def __init__(self, teacher: StructuredTeacher | None = None) -> None:
        self.teacher = teacher or GeminiBridge()

    def generate(self, need: TrainingNeed) -> SkillCandidate:
        context = json.dumps(dict(need.context), ensure_ascii=False, sort_keys=True)
        prompt = f"""
Create one small NEXA plugin candidate for this training need.

Domain: {need.domain.value}
Objective: {need.objective}
Context: {context}

Hard requirements:
- Conform to NEXA's public core Skill contract.
- Keep capability-specific logic outside the core kernel.
- Never use eval, exec, os.system, shell=True, dynamic code loading, raw shell
  strings, credential discovery, or security-policy modification.
- Never embed API keys, tokens, passwords, cookies, or private data.
- Every external process must be represented as an argument-list boundary and
  must not execute merely by importing the module.
- Include deterministic unit tests using unittest and mocks where external
  resources would otherwise be needed.
- Trading candidates must default to research/paper behavior. Do not create a
  live broker implementation or code that can place a real-money order.
- Return only the requested structured JSON.
""".strip()
        raw = self.teacher.generate_json(
            prompt,
            _CANDIDATE_SCHEMA,
            system_instruction=(
                "You are NEXA's senior teacher and code reviewer. Produce minimal, "
                "testable, safety-first plugin candidates; never bypass NEXA policy."
            ),
        )
        return self._candidate_from(raw)

    def repair(
        self,
        need: TrainingNeed,
        candidate: SkillCandidate,
        failure: str,
    ) -> SkillCandidate:
        prompt = f"""
Repair this NEXA plugin candidate after a sandbox/test failure.

Objective: {need.objective}
Risk classification: {candidate.risk.value}
Failure report:
{failure[:12000]}

Current skill.py:
{candidate.files['skill.py'][:24000]}

Current test file:
{self._test_source(candidate)[:24000]}

Preserve the same capability and risk classification. Do not weaken tests,
remove safety checks, add network/live-trading side effects, or modify NEXA core
security policy. Return corrected source only in the required JSON shape.
""".strip()
        raw = self.teacher.generate_json(
            prompt,
            _REPAIR_SCHEMA,
            system_instruction="Repair code conservatively. Safety constraints outrank task completion.",
        )
        test_name = self._test_name(candidate)
        files = dict(candidate.files)
        files["skill.py"] = str(raw["skill_py"])
        files[test_name] = str(raw["test_py"])
        return SkillCandidate(
            name=candidate.name,
            description=candidate.description,
            risk=candidate.risk,
            files=files,
            intents=candidate.intents,
            teacher_notes=str(raw.get("teacher_notes", "")).strip(),
        )

    @staticmethod
    def _candidate_from(raw: Mapping[str, Any]) -> SkillCandidate:
        name = str(raw["name"]).strip()
        safe_name = "".join(ch for ch in name if ch.isalnum() or ch in {"_", "-"})
        if not safe_name or safe_name != name:
            raise ValueError("teacher returned an unsafe candidate name")
        risk = CandidateRisk(str(raw["risk"]))
        test_name = f"test_{safe_name.replace('-', '_')}.py"
        intents = tuple(
            item.strip() for item in raw.get("intents", [])
            if isinstance(item, str) and item.strip()
        )
        files = {
            "skill.py": str(raw["skill_py"]),
            test_name: str(raw["test_py"]),
            "intents.json": json.dumps({"intents": intents}, ensure_ascii=False, indent=2),
        }
        return SkillCandidate(
            name=safe_name,
            description=str(raw["description"]).strip(),
            risk=risk,
            files=files,
            intents=intents,
            teacher_notes=str(raw.get("teacher_notes", "")).strip(),
        )

    @staticmethod
    def _test_name(candidate: SkillCandidate) -> str:
        return next(name for name in candidate.files if name.startswith("test_") and name.endswith(".py"))

    @classmethod
    def _test_source(cls, candidate: SkillCandidate) -> str:
        return candidate.files[cls._test_name(candidate)]
