from __future__ import annotations
import re
import uuid
from datetime import datetime
from typing import Any

from planner.contracts import TaskPlan, PlanStep


class TaskPlanner:
    """Decomposes complex user requests into multi-step skill execution plans.
    
    Uses a combination of:
    1. Deterministic pattern matching for common workflows
    2. Skill registry introspection to find available capabilities
    3. Optional LLM (via GeminiBridge) for complex decomposition
    
    The planner chooses between:
    - SINGLE_SKILL: request can be handled by one skill
    - COMPOSE: multiple existing skills can be chained
    - BUILD_NEW: a new capability is needed (delegates to CapabilityManager)
    """
    
    def __init__(self, registry: Any | None = None,
                 capability_manager: Any | None = None) -> None:
        self._registry = registry
        self._capability_manager = capability_manager
    
    def plan(self, request: str, context: dict[str, Any] | None = None) -> TaskPlan:
        """Create an execution plan for a user request."""
        steps = self._detect_multi_step(request, context)
        if not steps:
            found = self._find_skill_for_step(request, context)
            if found:
                skill_name, op, params = found
                steps = [PlanStep(
                    step_id=1,
                    description=request,
                    skill_name=skill_name,
                    operation=op,
                    params=params,
                )]
            else:
                steps = [PlanStep(
                    step_id=1,
                    description=request,
                    skill_name="unknown",
                    operation="unknown",
                )]
            
        return TaskPlan(
            plan_id=str(uuid.uuid4()),
            description=request,
            steps=steps,
            original_request=request,
            created_at=datetime.utcnow().isoformat(),
        )
    
    def _detect_multi_step(self, request: str, context: dict[str, Any] | None = None) -> list[PlanStep] | None:
        """Detect if request requires multiple steps using pattern matching and skill resolution."""
        req_lower = request.lower()
        if " and " in req_lower or " then " in req_lower:
            parts = [p.strip() for p in re.split(r"\s+(?:and\s+then|and|then)\s+", request, flags=re.IGNORECASE) if p.strip()]
            if len(parts) >= 2:
                steps = []
                for idx, part in enumerate(parts, 1):
                    found = self._find_skill_for_step(part, context)
                    skill_name = found[0] if found else "dummy"
                    op = found[1] if found else f"op{idx}"
                    params = found[2] if found else {}
                    steps.append(PlanStep(
                        step_id=idx,
                        description=part,
                        skill_name=skill_name,
                        operation=op,
                        params=params,
                        depends_on=(idx - 1,) if idx > 1 else (),
                    ))
                return steps
        return None
    
    def _find_skill_for_step(self, step_description: str, context: dict[str, Any] | None = None) -> tuple[str, str, dict[str, Any]] | None:
        """Find a skill and operation that can handle a step description."""
        if self._registry is not None:
            match = self._registry.resolve(step_description, context or {})
            if match is not None:
                return (match.skill_name, match.operation, dict(match.params))
        return None
