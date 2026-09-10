from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from core.contracts import RiskTier


class CapabilityEventType(str, Enum):
    CAPABILITY_REQUESTED = "CAPABILITY_REQUESTED"
    CAPABILITY_FOUND = "CAPABILITY_FOUND"
    CAPABILITY_MISSING = "CAPABILITY_MISSING"
    CAPABILITY_BUILD_STARTED = "CAPABILITY_BUILD_STARTED"
    CAPABILITY_BUILD_COMPLETED = "CAPABILITY_BUILD_COMPLETED"
    CAPABILITY_TEST_STARTED = "CAPABILITY_TEST_STARTED"
    CAPABILITY_TEST_PASSED = "CAPABILITY_TEST_PASSED"
    CAPABILITY_TEST_FAILED = "CAPABILITY_TEST_FAILED"
    CAPABILITY_REGISTERED = "CAPABILITY_REGISTERED"
    CAPABILITY_EXECUTED = "CAPABILITY_EXECUTED"
    CAPABILITY_EXECUTION_FAILED = "CAPABILITY_EXECUTION_FAILED"
    CAPABILITY_DISABLED = "CAPABILITY_DISABLED"
    CAPABILITY_ENABLED = "CAPABILITY_ENABLED"
    CAPABILITY_HEALTH_CHECKED = "CAPABILITY_HEALTH_CHECKED"


@dataclass(frozen=True)
class CapabilityEvent:
    event_type: CapabilityEventType
    capability_id: str
    message: str
    timestamp_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    name: str
    description: str
    purpose: str
    version: str
    risk_tier: RiskTier
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityRecord:
    spec: CapabilitySpec
    module_path: str
    class_name: str
    test_status: str
    created_at_utc: str
    updated_at_utc: str
    usage_count: int = 0
    last_used_at_utc: str | None = None


@dataclass(frozen=True)
class CapabilityPlan:
    capability_id: str
    name: str
    description: str
    purpose: str
    operation: str
    risk_tier: RiskTier
    intents: tuple[str, ...]
    dependencies: tuple[str, ...]
    extracted_params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityBuildResult:
    success: bool
    spec: CapabilitySpec | None
    code: str
    test_code: str
    class_name: str
    error: str | None = None


@dataclass(frozen=True)
class CapabilityTestResult:
    passed: bool
    output: str
    error: str | None = None
