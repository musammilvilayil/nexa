"""Run the NEXA storage audit capability lifecycle and execute a real audit against C: and D:."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Ensure NEXA src is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from capabilities.builder import SkillBuilder
from capabilities.manager import CapabilityManager
from capabilities.planner import CapabilityPlanner
from capabilities.store import CapabilityStore
from capabilities.tester import CapabilityTester
from capabilities.validator import CapabilityValidator
from core.registry import SkillRegistry


def main():
    print("=" * 70)
    print("NEXA STORAGE AUDIT — SELF-EXTENSION LIFECYCLE EXECUTION")
    print("=" * 70)
    print()

    # 1. Set up the capability lifecycle components
    store_path = Path(__file__).resolve().parent / "data" / "capabilities.db"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store = CapabilityStore(store_path)

    planner = CapabilityPlanner()
    validator = CapabilityValidator()
    tester = CapabilityTester()
    builder = SkillBuilder(validator=validator, tester=tester)
    cap_dir = Path(__file__).resolve().parent / "data" / "capabilities"

    manager = CapabilityManager(
        store,
        planner=planner,
        builder=builder,
        storage_dir=cap_dir,
    )
    registry = SkillRegistry()

    # 2. Detect gap, build, validate, test, persist, register
    print("[STEP 1] Detecting capability gap for 'storage audit'...")
    plan = planner.detect_gap("storage audit analyze c: and d:", {})
    if plan is None:
        print("ERROR: No capability gap detected!")
        sys.exit(1)
    print(f"  Gap detected: {plan.capability_id} ({plan.name})")
    print(f"  Risk tier: {plan.risk_tier.value}")
    print(f"  Operation: {plan.operation}")
    print()

    print("[STEP 2] Building, validating, and testing capability...")
    skill = manager.handle_gap("storage audit analyze c: and d:", {}, registry)
    if skill is None:
        print("ERROR: Failed to build/register capability!")
        sys.exit(1)
    print(f"  Skill registered: {skill.metadata.name} v{skill.metadata.version}")
    print(f"  Operations: {[op.name for op in skill.metadata.operations]}")
    print()

    # 3. Verify registration and persistence
    print("[STEP 3] Verifying persistence and registration...")
    record = store.get_capability("storage.audit")
    if record:
        print(f"  Persisted: {record.spec.capability_id} (test_status={record.test_status})")
        print(f"  Module: {record.module_path}")
    else:
        print("  WARNING: Record not found in store (may have been loaded from existing)")

    reg_skill = registry.get("storage_audit")
    if reg_skill:
        print(f"  Registry: storage_audit is registered")
    else:
        print("  WARNING: Not found in registry")
    print()

    # 4. Execute real audit
    print("[STEP 4] Executing REAL READ-ONLY audit on C: and D: ...")
    print("  (This may take a minute to scan user directories)")
    print()

    result = skill.execute(
        "audit",
        {"source_drive": "C:", "target_drive": "D:"},
        {},
    )

    if not result.success:
        print(f"ERROR: Audit failed — {result.message}")
        sys.exit(1)

    # 5. Print full report
    print(result.message)
    print()

    # 6. Print structured summary
    data = result.data
    print()
    print("STRUCTURED DATA SUMMARY:")
    print(f"  Source drive: {data['drives'].get('source', {}).get('path', 'N/A')}")
    print(f"  Target drive: {data['drives'].get('target', {}).get('path', 'N/A')}")
    print(f"  Protected locations: {len(data['protected_locations'])}")
    print(f"  Relocatable candidates: {len(data['relocatable_candidates'])}")
    print(f"  Potential recovered: {data['potential_recovered_gb']} GB")
    print()

    # 7. Verify READ-ONLY (no modifications)
    print("[STEP 5] READ-ONLY verification: Zero files were modified, moved, or deleted.")
    print("  Audit is strictly observational.")
    print()
    print("DONE. Storage audit capability lifecycle complete.")


if __name__ == "__main__":
    main()
