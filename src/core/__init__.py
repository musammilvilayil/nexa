"""Standalone NEXA orchestration kernel.

The core package contains no Git-, GitHub-, file-, model-, or provider-specific
logic. External capabilities plug in through the generic Skill contract.
"""

from .contracts import (
    ExecutionResult,
    OperationSpec,
    PolicyDecision,
    PolicyOutcome,
    RiskTier,
    SkillMatch,
    SkillMetadata,
)
from .context import ContextBus, ContextSnapshot
from .dispatcher import Dispatcher
from .kernel import KernelResponse, NexaKernel, PendingAction
from .registry import SkillRegistry
from .security import SecurityGate

__all__ = [
    "ContextBus",
    "ContextSnapshot",
    "Dispatcher",
    "ExecutionResult",
    "KernelResponse",
    "NexaKernel",
    "OperationSpec",
    "PendingAction",
    "PolicyDecision",
    "PolicyOutcome",
    "RiskTier",
    "SecurityGate",
    "SkillMatch",
    "SkillMetadata",
    "SkillRegistry",
]
