from __future__ import annotations
from typing import Any
import copy
import uuid
from datetime import datetime

from planner.contracts import TaskPlan

class SkillComposer:
    """Composes existing skills into reusable workflows.
    
    When the same multi-step pattern is used repeatedly, the composer
    can save it as a named workflow for faster future execution.
    """
    
    def __init__(self) -> None:
        self._workflows: dict[str, TaskPlan] = {}
    
    def save_workflow(self, name: str, plan: TaskPlan) -> None:
        """Save a completed plan as a reusable workflow."""
        self._workflows[name] = copy.deepcopy(plan)
    
    def get_workflow(self, name: str) -> TaskPlan | None:
        """Retrieve a saved workflow."""
        return copy.deepcopy(self._workflows.get(name))
    
    def list_workflows(self) -> list[str]:
        """List all saved workflow names."""
        return list(self._workflows.keys())
    
    def instantiate(self, name: str, params: dict[str, Any] | None = None) -> TaskPlan | None:
        """Create a new plan from a saved workflow, with optional parameter overrides."""
        workflow = self.get_workflow(name)
        if not workflow:
            return None
            
        workflow.plan_id = str(uuid.uuid4())
        workflow.created_at = datetime.utcnow().isoformat()
        
        return workflow
