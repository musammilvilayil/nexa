from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from core.context import CURRENT_DEVICE_CONTEXT
from planner.contracts import TaskPlan, PlanStep


class TaskPlanner:
    """Decomposes complex user requests into multi-step skill execution plans.
    
    Supports:
    1. Contextual reference resolution (ith, ath, ee file, last file)
    2. Multi-step splitting across English and Manglish conjunctions (and, then, pinne, athukazhinju)
    3. Pattern matching and capability resolution
    4. Generalization across English, Malayalam, and Manglish
    """

    COMPOUND_SPLIT_RE = re.compile(
        r"\s+(?:and\s+then|and|then|pinne|athukazhinju|ennitt)\s+|\s*,\s*(?=(?:open|search|type|click|run|create|delete|close|list)\b)",
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
        if ("linkedin" in req_lower or "google" in req_lower) and ("jobs" in req_lower or "search" in req_lower) and ("list" in req_lower or "extract" in req_lower or "nokk" in req_lower):
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
            for idx, part in enumerate(parts, 1):
                found = self._find_skill_for_step(part, context)
                skill_name = found[0] if found else "unknown"
                op = found[1] if found else f"op{idx}"
                params = found[2] if found else {}
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
        if self._registry is not None:
            match = self._registry.resolve(step_description, context or {})
            if match is not None:
                return (match.skill_name, match.operation, dict(match.params))
        return None
