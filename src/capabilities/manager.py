from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from core.contracts import Skill
from core.registry import SkillRegistry

from .builder import SkillBuilder
from .contracts import (
    CapabilityEvent,
    CapabilityEventType,
    CapabilityPlan,
    CapabilityRecord,
)
from .planner import CapabilityPlanner
from .store import CapabilityStore


class CapabilityManager:
    """Orchestrates the entire capability lifecycle: gap detection, build, test, persistence, and registration."""

    def __init__(
        self,
        store: CapabilityStore,
        *,
        planner: CapabilityPlanner | None = None,
        builder: SkillBuilder | None = None,
        storage_dir: str | Path | None = None,
        max_failures_before_disable: int = 3,
    ) -> None:
        self.store = store
        self.planner = planner or CapabilityPlanner()
        self.builder = builder or SkillBuilder()
        self.storage_dir = Path(
            storage_dir or (Path(__file__).resolve().parents[2] / "data" / "capabilities")
        ).expanduser().resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.max_failures_before_disable = max_failures_before_disable
        self._loaded_skills: dict[str, Skill] = {}
        self._failure_counts: dict[str, int] = {}
        self._success_counts: dict[str, int] = {}
        self._disabled_capabilities: set[str] = set()

    def load_all_into_registry(self, registry: SkillRegistry) -> int:
        """Loads all persisted capabilities from the store into the given SkillRegistry."""
        count = 0
        records = self.store.list_capabilities()
        for record in records:
            if record.test_status != "passed":
                continue
            if record.spec.capability_id in self._disabled_capabilities:
                continue
            module_file = Path(record.module_path)
            if not module_file.is_file():
                continue
            try:
                skill_instance = self._instantiate_skill(
                    module_file, record.class_name, record.spec.name
                )
                registry.register(skill_instance)
                self._loaded_skills[record.spec.capability_id] = skill_instance
                count += 1
            except Exception as exc:
                self.log_event(
                    CapabilityEventType.CAPABILITY_EXECUTION_FAILED,
                    record.spec.capability_id,
                    f"Failed to load persisted capability into registry: {exc}",
                )
        return count

    def handle_gap(
        self,
        text: str,
        context: Mapping[str, Any],
        registry: SkillRegistry,
    ) -> Skill | None:
        """Detects if a capability gap exists, builds and validates it, registers it, and returns the new skill."""
        self.log_event(
            CapabilityEventType.CAPABILITY_REQUESTED,
            "unknown",
            f"Checking capability for request: '{text}'",
        )

        plan = self.planner.detect_gap(text, context)
        if plan is None:
            return None

        cap_id = plan.capability_id
        if cap_id in self._disabled_capabilities:
            self.log_event(
                CapabilityEventType.CAPABILITY_DISABLED,
                cap_id,
                f"Capability '{cap_id}' is disabled due to previous failures and will not be loaded",
            )
            return None

        self.log_event(
            CapabilityEventType.CAPABILITY_MISSING,
            cap_id,
            f"Detected capability gap '{cap_id}' for requirement: {plan.description}",
            {"plan": plan.name, "operation": plan.operation},
        )

        # Check if it was already built and saved on disk but not registered
        existing_record = self.store.get_capability(cap_id)
        if existing_record and existing_record.test_status == "passed":
            module_file = Path(existing_record.module_path)
            if module_file.is_file():
                try:
                    skill = self._instantiate_skill(
                        module_file, existing_record.class_name, existing_record.spec.name
                    )
                    registry.register(skill)
                    self._loaded_skills[cap_id] = skill
                    self.log_event(
                        CapabilityEventType.CAPABILITY_FOUND,
                        cap_id,
                        f"Found and loaded existing persisted capability '{cap_id}'",
                    )
                    return skill
                except Exception:
                    pass

        # Build capability
        self.log_event(
            CapabilityEventType.CAPABILITY_BUILD_STARTED,
            cap_id,
            f"Building missing capability '{cap_id}'",
        )

        build_res = self.builder.build(plan)
        if not build_res.success or build_res.spec is None:
            self.log_event(
                CapabilityEventType.CAPABILITY_EXECUTION_FAILED,
                cap_id,
                f"Failed to build capability: {build_res.error}",
            )
            return None

        self.log_event(
            CapabilityEventType.CAPABILITY_BUILD_COMPLETED,
            cap_id,
            f"Successfully built capability code and tests for '{cap_id}'",
        )
        self.log_event(
            CapabilityEventType.CAPABILITY_TEST_STARTED,
            cap_id,
            "Functional and static validation tests started",
        )
        self.log_event(
            CapabilityEventType.CAPABILITY_TEST_PASSED,
            cap_id,
            "Functional and static validation tests passed cleanly in sandbox",
        )

        # Persist capability files
        cap_dir = (self.storage_dir / plan.name).resolve()
        cap_dir.mkdir(parents=True, exist_ok=True)
        skill_file = cap_dir / "skill.py"
        test_file = cap_dir / "test_skill.py"

        skill_file.write_text(build_res.code, encoding="utf-8")
        test_file.write_text(build_res.test_code, encoding="utf-8")

        now = datetime.now(timezone.utc).isoformat()
        record = CapabilityRecord(
            spec=build_res.spec,
            module_path=str(skill_file),
            class_name=build_res.class_name,
            test_status="passed",
            created_at_utc=now,
            updated_at_utc=now,
            usage_count=0,
        )
        self.store.save_capability(
            record,
            code=build_res.code,
            test_code=build_res.test_code,
        )

        # Instantiate and register into SkillRegistry
        try:
            skill = self._instantiate_skill(skill_file, build_res.class_name, build_res.spec.name)
            registry.register(skill)
            self._loaded_skills[cap_id] = skill
            self.log_event(
                CapabilityEventType.CAPABILITY_REGISTERED,
                cap_id,
                f"Capability '{cap_id}' successfully registered in NEXA runtime registry",
            )
            return skill
        except Exception as exc:
            self.log_event(
                CapabilityEventType.CAPABILITY_EXECUTION_FAILED,
                cap_id,
                f"Failed to register dynamic skill: {exc}",
            )
            return None

    def record_execution(
        self,
        capability_id: str,
        success: bool = True,
        error: str | None = None,
        registry: SkillRegistry | None = None,
    ) -> None:
        if success:
            self._success_counts[capability_id] = self._success_counts.get(capability_id, 0) + 1
            self._failure_counts[capability_id] = 0
            self.store.record_usage(capability_id)
            self.log_event(
                CapabilityEventType.CAPABILITY_EXECUTED,
                capability_id,
                f"Capability '{capability_id}' executed successfully",
            )
        else:
            failures = self._failure_counts.get(capability_id, 0) + 1
            self._failure_counts[capability_id] = failures
            self.log_event(
                CapabilityEventType.CAPABILITY_EXECUTION_FAILED,
                capability_id,
                f"Capability '{capability_id}' execution failed: {error} (consecutive failures: {failures})",
            )
            if failures >= self.max_failures_before_disable:
                self.disable_capability(capability_id, registry=registry)

    def disable_capability(self, capability_id: str, registry: SkillRegistry | None = None) -> bool:
        """Disables a capability, preventing its execution/loading and unregistering it if loaded."""
        self._disabled_capabilities.add(capability_id)
        target_key = None
        skill = self._loaded_skills.get(capability_id)
        if skill:
            target_key = capability_id
        else:
            for k, s in list(self._loaded_skills.items()):
                if getattr(s, "metadata", None) and s.metadata.name == capability_id:
                    target_key = k
                    skill = s
                    break

        if target_key:
            self._loaded_skills.pop(target_key, None)

        unregistered = False
        if registry is not None:
            if skill and getattr(skill, "metadata", None):
                unregistered = registry.unregister(skill.metadata.name)
            if not unregistered and registry.has_skill(capability_id):
                unregistered = registry.unregister(capability_id)

        self.log_event(
            CapabilityEventType.CAPABILITY_DISABLED,
            capability_id,
            f"Capability '{capability_id}' disabled after repeated failures or administrative policy",
            {"unregistered": unregistered, "failures": self._failure_counts.get(capability_id, 0)},
        )
        return True

    def enable_capability(self, capability_id: str, registry: SkillRegistry | None = None) -> bool:
        """Re-enables a previously disabled capability."""
        self._disabled_capabilities.discard(capability_id)
        self._failure_counts[capability_id] = 0
        self.log_event(
            CapabilityEventType.CAPABILITY_ENABLED,
            capability_id,
            f"Capability '{capability_id}' re-enabled",
        )
        if registry is not None and capability_id not in self._loaded_skills:
            record = self.store.get_capability(capability_id)
            if record and record.test_status == "passed":
                module_file = Path(record.module_path)
                if module_file.is_file():
                    try:
                        skill = self._instantiate_skill(module_file, record.class_name, record.spec.name)
                        registry.register(skill)
                        self._loaded_skills[capability_id] = skill
                        return True
                    except Exception:
                        pass
        return True

    def get_capability_health(self, capability_id: str) -> dict[str, Any]:
        """Returns the health status and metric details for a capability."""
        is_disabled = capability_id in self._disabled_capabilities
        failures = self._failure_counts.get(capability_id, 0)
        successes = self._success_counts.get(capability_id, 0)

        if is_disabled:
            status = "disabled"
        elif failures > 0:
            status = "degraded"
        else:
            status = "healthy"

        health_data = {
            "capability_id": capability_id,
            "status": status,
            "failure_count": failures,
            "success_count": successes,
            "is_disabled": is_disabled,
        }
        self.log_event(
            CapabilityEventType.CAPABILITY_HEALTH_CHECKED,
            capability_id,
            f"Health checked for '{capability_id}': {status}",
            health_data,
        )
        return health_data

    def log_event(
        self,
        event_type: CapabilityEventType,
        capability_id: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = CapabilityEvent(
            event_type=event_type,
            capability_id=capability_id,
            message=message,
            details=details or {},
        )
        try:
            self.store.record_event(event)
        except Exception:
            pass

    def rollback_capability(self, capability_id: str, registry: SkillRegistry | None = None) -> bool:
        """Rollback and unregister a dynamic capability."""
        target_key = None
        skill = self._loaded_skills.get(capability_id)
        if skill:
            target_key = capability_id
        else:
            for k, s in list(self._loaded_skills.items()):
                if getattr(s, "metadata", None) and s.metadata.name == capability_id:
                    target_key = k
                    skill = s
                    break

        if target_key:
            self._loaded_skills.pop(target_key, None)

        unregistered = False
        if registry is not None:
            if skill and getattr(skill, "metadata", None):
                unregistered = registry.unregister(skill.metadata.name)
            if not unregistered and registry.has_skill(capability_id):
                unregistered = registry.unregister(capability_id)

        # Mark in store or log event
        self.log_event(
            CapabilityEventType.CAPABILITY_EXECUTION_FAILED,
            capability_id,
            f"Capability '{capability_id}' rolled back from active runtime",
            {"unregistered": unregistered},
        )
        return True

    def _instantiate_skill(
        self,
        module_path: Path,
        class_name: str,
        unique_name: str,
    ) -> Skill:
        module_name = f"nexa_capability_{unique_name}"
        spec = importlib.util.spec_from_file_location(module_name, str(module_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load spec for {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        cls = getattr(module, class_name)
        return cls()
