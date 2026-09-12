from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from core.context import CURRENT_DEVICE_CONTEXT
from core.entity_resolver import EntityResolver
from planner.contracts import TaskPlan, PlanStep


class TaskPlanner:
    """Decomposes complex user requests into multi-step skill execution plans.
    
    Supports:
    1. Contextual reference resolution (ith, ath, ee file, last file)
    2. Multi-step splitting across English and Manglish conjunctions (and, then, pinne, athukazhinju)
    3. Pattern matching, entity resolution, and capability resolution
    4. Cross-step context propagation (active app, active directory, extracted data)
    5. Generalization across English, Malayalam, and Manglish
    """

    COMPOUND_SPLIT_RE = re.compile(
        r"\s+(?:and\s+then|then|pinne|athukazhinju|ennitt)\s+|\s+(?:and)\s+(?!(?:verify|confirm)\b)|\s*,\s*(?=(?:open|search|type|click|run|create|delete|close|list|save|read|write|move|copy|find|extract|[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)\b)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        registry: Any | None = None,
        capability_manager: Any | None = None,
    ) -> None:
        self._registry = registry
        self._capability_manager = capability_manager

    def plan(self, request: str, context: dict[str, Any] | None = None) -> TaskPlan:
        """Create an execution plan for a user request."""
        # 1. Resolve deictic contextual references (e.g. 'ith close cheyy', 'ee file delete cheyy')
        resolved_request = CURRENT_DEVICE_CONTEXT.resolve_reference(request)

        # 2. Detect compound multi-step workflows
        steps = self._detect_multi_step(resolved_request, context)
        if not steps:
            found = self._find_skill_for_step(resolved_request, context)
            if found:
                skill_name, op, params = found
                steps = [
                    PlanStep(
                        step_id=1,
                        description=resolved_request,
                        skill_name=skill_name,
                        operation=op,
                        params=params,
                    )
                ]
            else:
                steps = [
                    PlanStep(
                        step_id=1,
                        description=resolved_request,
                        skill_name="unknown",
                        operation="unknown",
                    )
                ]

        return TaskPlan(
            plan_id=str(uuid.uuid4()),
            description=request,
            steps=steps,
            original_request=request,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _detect_multi_step(
        self,
        request: str,
        context: dict[str, Any] | None = None,
    ) -> list[PlanStep] | None:
        """Detect if request requires multiple steps using pattern matching and skill resolution."""
        # Check special complex Manglish patterns (e.g. open browser, search, extract)
        req_lower = request.lower()
        if ("linkedin" in req_lower or "google" in req_lower) and ("jobs" in req_lower or "nokk" in req_lower or "cheythu" in req_lower) and "save" not in req_lower and ("list" in req_lower or "extract" in req_lower or "nokk" in req_lower):
            # Generalized decomposition for web search & extraction queries
            return [
                PlanStep(
                    step_id=1,
                    description="open browser",
                    skill_name="browser",
                    operation="launch",
                    params={},
                ),
                PlanStep(
                    step_id=2,
                    description=f"search {request}",
                    skill_name="browser",
                    operation="search",
                    params={"query": request},
                    depends_on=(1,),
                ),
                PlanStep(
                    step_id=3,
                    description="extract content",
                    skill_name="browser",
                    operation="extract",
                    params={},
                    depends_on=(2,),
                ),
            ]

        # General multi-step conjunction split
        parts = [p.strip() for p in self.COMPOUND_SPLIT_RE.split(request) if p.strip()]
        if len(parts) >= 2:
            steps = []
            active_app: str | None = None
            active_dir: str | None = None
            last_text: str | None = None

            for idx, raw_part in enumerate(parts, 1):
                part = raw_part.strip()
                # Normalize part phrasing
                m_file_with = re.match(r"^(?:create\s+(?:file\s+)?)?([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)\s+with\s+(.*)$", part, re.IGNORECASE)
                if m_file_with:
                    part = f"create file {m_file_with.group(1)} with {m_file_with.group(2).strip('\'\"')}"
                elif re.match(r"^save\s+(?:it\s+)?to\s+(.+)$", part, re.IGNORECASE):
                    m_save = re.match(r"^save\s+(?:it\s+)?to\s+(.+)$", part, re.IGNORECASE)
                    part = f"save as {m_save.group(1).strip()}"
                elif re.match(r"^extract\s+(?:the\s+)?(?:answer|summary|content|data|text)$", part, re.IGNORECASE):
                    part = "extract"
                elif re.match(r"^type\s+['\"](.*)['\"]$", part, re.IGNORECASE):
                    m_type = re.match(r"^type\s+['\"](.*)['\"]$", part, re.IGNORECASE)
                    part = f'type "{m_type.group(1)}"'
                elif part.lower() == "list the folder" and active_dir:
                    part = f"list folder {active_dir}"

                if part in ("extract", "extract content", "extract the answer", "extract data") and any(s.skill_name == "browser" for s in steps):
                    found = ("browser", "extract", {})
                else:
                    found = self._find_skill_for_step(part, context)
                skill_name = found[0] if found else "unknown"
                op = found[1] if found else f"op{idx}"
                params = dict(found[2]) if found else {}

                # Context propagation across steps
                if skill_name == "app_control" and op == "launch" and params.get("app_name"):
                    active_app = params["app_name"]
                elif skill_name == "computer" and op == "type_text":
                    if active_app and not params.get("app"):
                        params["app"] = active_app
                    if params.get("text"):
                        last_text = params["text"]
                elif skill_name == "files" and op == "mkdir":
                    active_dir = params.get("path")
                elif skill_name == "files" and op == "write":
                    p_path = params.get("path", "")
                    if active_dir and p_path and not os.path.isabs(p_path) and not p_path.startswith(active_dir):
                        params["path"] = f"{active_dir}/{p_path}"
                    if not params.get("content") and last_text:
                        params["content"] = last_text
                elif skill_name == "files" and op == "list":
                    if active_dir and (params.get("path") == "." or not params.get("path")):
                        params["path"] = active_dir

                steps.append(
                    PlanStep(
                        step_id=idx,
                        description=part,
                        skill_name=skill_name,
                        operation=op,
                        params=params,
                        depends_on=(idx - 1,) if idx > 1 else (),
                    )
                )
            return steps

        return None

    def _find_skill_for_step(
        self,
        step_description: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, str, dict[str, Any]] | None:
        """Find a skill and operation that can handle a step description."""
        normalized = EntityResolver.strip_politeness(step_description).strip().rstrip(".!?")
        if self._registry is not None:
            match = self._registry.resolve(normalized, context or {})
            if match is not None:
                return (match.skill_name, match.operation, dict(match.params))
            # Try raw step description
            match = self._registry.resolve(step_description, context or {})
            if match is not None:
                return (match.skill_name, match.operation, dict(match.params))
        return None
