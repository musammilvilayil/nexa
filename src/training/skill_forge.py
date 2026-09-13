from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from bridges import GeminiBridge
from sandbox import SandboxResult, SandboxRunner, StaticValidator


@dataclass(frozen=True)
class SkillCandidate:
    name: str
    description: str
    risk_tier: str
    skill_py: str
    test_skill_py: str
    intents_json: str
    teacher_notes: str

    def files(self) -> dict[str, str]:
        return {
            "skill.py": self.skill_py,
            "test_skill.py": self.test_skill_py,
            "intents.json": self.intents_json,
        }


@dataclass(frozen=True)
class ForgeResult:
    passed: bool
    candidate: SkillCandidate | None
    sandbox: SandboxResult | None
    teacher_calls: int
    reason: str


class SkillForge:
    """Bounded teacher-generated plugin candidate forge.

    A successful result is only a promotion candidate. This class never edits the
    live registry, kernel, security policy, or source tree automatically.
    """

    CANDIDATE_SCHEMA = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "skill_py": {"type": "string"},
            "test_skill_py": {"type": "string"},
            "intents": {"type": "array", "items": {"type": "string"}},
            "teacher_notes": {"type": "string"},
        },
        "required": ["name", "description", "skill_py", "test_skill_py", "intents", "teacher_notes"],
    }

    SYSTEM = """You are NEXA's senior Skill Forge teacher. Generate a small Python plugin that follows the
NEXA Skill contract from core. Generated code is untrusted until static validation and unit tests pass.
Never import os, subprocess, socket, requests, urllib, ctypes, winreg, shutil, multiprocessing, or bridges.
Never use eval, exec, compile, __import__, open, dunder introspection, or shell commands. Capabilities that
need external resources must receive a narrow reviewed dependency object through __init__; do not bypass
that dependency. Do not modify core security, audit, permission gates, or registry. Return only structured JSON."""

    ALLOWED_RISKS = {"read", "mutate", "remote", "destructive"}

    def __init__(
        self,
        bridge: GeminiBridge | None = None,
        *,
        sandbox: SandboxRunner | None = None,
        validator: StaticValidator | None = None,
        max_repairs: int = 2,
        max_source_chars: int = 40_000,
    ) -> None:
        if max_repairs < 0 or max_repairs > 5:
            raise ValueError("max_repairs must be between 0 and 5")
        if max_source_chars <= 0:
            raise ValueError("max_source_chars must be positive")
        self.bridge = bridge or GeminiBridge()
        self.validator = validator or StaticValidator()
        self.sandbox = sandbox or SandboxRunner(validator=self.validator)
        self.max_repairs = int(max_repairs)
        self.max_source_chars = int(max_source_chars)

    def forge(
        self,
        capability_request: str,
        *,
        risk_tier: str,
        context: str | None = None,
    ) -> ForgeResult:
        request = capability_request.strip()
        risk = risk_tier.strip().lower()
        if not request:
            raise ValueError("capability_request cannot be empty")
        if risk not in self.ALLOWED_RISKS:
            raise ValueError(f"invalid risk tier: {risk}")

        teacher_calls = 0
        candidate = self._generate(request, risk, context=context)
        teacher_calls += 1

        for repair_round in range(self.max_repairs + 1):
            validation_reason = self._preflight(candidate)
            if validation_reason is not None:
                if repair_round >= self.max_repairs:
                    return ForgeResult(False, candidate, None, teacher_calls, validation_reason)
                candidate = self._repair(
                    candidate,
                    request=request,
                    failure=validation_reason,
                    risk_tier=risk,
                )
                teacher_calls += 1
                continue

            sandbox_result = self.sandbox.run(candidate.files())
            if sandbox_result.passed:
                return ForgeResult(
                    True,
                    candidate,
                    sandbox_result,
                    teacher_calls,
                    "candidate passed static validation and isolated unit tests; manual/policy promotion still required",
                )

            if repair_round >= self.max_repairs:
                return ForgeResult(False, candidate, sandbox_result, teacher_calls, sandbox_result.reason)

            failure = self._sandbox_failure(sandbox_result)
            candidate = self._repair(
                candidate,
                request=request,
                failure=failure,
                risk_tier=risk,
            )
            teacher_calls += 1

        return ForgeResult(False, candidate, None, teacher_calls, "repair loop exhausted")

    def _generate(
        self,
        request: str,
        risk_tier: str,
        *,
        context: str | None,
    ) -> SkillCandidate:
        prompt = f"""Generate one NEXA skill candidate.

Capability requested: {request}
Required risk tier: {risk_tier}
Optional architecture context: {(context or 'none')[:4000]}

Contract requirements:
- Import SkillMetadata, OperationSpec, RiskTier, SkillMatch, ExecutionResult from core.
- Implement metadata, match(text, context), validate(operation, params, context), execute(operation, params, context).
- Matching and validation must be deterministic and fail closed.
- Do not create a live trading or money-transfer executor.
- Tests must use Python unittest and mock injected dependencies; no real network/process/filesystem side effects.
- intents must include concise English and Manglish trigger examples where appropriate.
- Keep implementation narrow and under {self.max_source_chars} characters per Python file.
""".strip()
        payload = self.bridge.generate_json(
            prompt,
            self.CANDIDATE_SCHEMA,
            system_instruction=self.SYSTEM,
        )
        return self._candidate(payload, risk_tier)

    def _repair(
        self,
        candidate: SkillCandidate,
        *,
        request: str,
        failure: str,
        risk_tier: str,
    ) -> SkillCandidate:
        prompt = f"""Repair this NEXA skill candidate without broadening its permissions.

Original capability: {request}
Required risk tier: {risk_tier}
Failure from deterministic validator/test runner:
{failure[:6000]}

Current skill.py:
```python
{candidate.skill_py[:self.max_source_chars]}
```

Current test_skill.py:
```python
{candidate.test_skill_py[:self.max_source_chars]}
```

Current intents JSON:
{candidate.intents_json[:4000]}

Return a complete replacement candidate. Preserve the same narrow capability. Never disable or work around
validation/tests, never import forbidden modules, and never change core/security/audit code.
""".strip()
        payload = self.bridge.generate_json(
            prompt,
            self.CANDIDATE_SCHEMA,
            system_instruction=self.SYSTEM,
        )
        return self._candidate(payload, risk_tier)

    def _candidate(self, payload: dict[str, Any], risk_tier: str) -> SkillCandidate:
        intents = payload.get("intents")
        if not isinstance(intents, list) or not intents:
            raise ValueError("teacher candidate requires intents")
        intent_values = [str(item).strip() for item in intents if str(item).strip()]
        if not intent_values:
            raise ValueError("teacher candidate intents are empty")
        return SkillCandidate(
            name=str(payload["name"]).strip(),
            description=str(payload["description"]).strip(),
            risk_tier=risk_tier,
            skill_py=str(payload["skill_py"]),
            test_skill_py=str(payload["test_skill_py"]),
            intents_json=json.dumps(intent_values, ensure_ascii=False, indent=2),
            teacher_notes=str(payload["teacher_notes"]).strip(),
        )

    def _preflight(self, candidate: SkillCandidate) -> str | None:
        if not candidate.name or not candidate.description:
            return "candidate metadata is empty"
        if len(candidate.skill_py) > self.max_source_chars or len(candidate.test_skill_py) > self.max_source_chars:
            return "candidate Python source exceeds size limit"
        try:
            intents = json.loads(candidate.intents_json)
        except json.JSONDecodeError as exc:
            return f"intents JSON invalid: {exc}"
        if not isinstance(intents, list) or not intents or any(not isinstance(item, str) for item in intents):
            return "intents JSON must be a non-empty string array"

        findings: list[str] = []
        for filename, source in (("skill.py", candidate.skill_py), ("test_skill.py", candidate.test_skill_py)):
            report = self.validator.validate(source)
            for finding in report.findings:
                findings.append(f"{filename}:{finding.line}:{finding.code}:{finding.message}")
        return "\n".join(findings) if findings else None

    @staticmethod
    def _sandbox_failure(result: SandboxResult) -> str:
        pieces = [result.reason]
        if result.process is not None:
            if result.process.stdout:
                pieces.append("stdout:\n" + result.process.stdout[-4000:])
            if result.process.stderr:
                pieces.append("stderr:\n" + result.process.stderr[-4000:])
        for filename, report in result.validation:
            for finding in report.findings:
                pieces.append(f"{filename}:{finding.line}:{finding.code}:{finding.message}")
        return "\n".join(pieces)
