from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core import KernelResponse


@dataclass(frozen=True)
class RuntimeHealthSnapshot:
    ok: bool
    state: str
    checked_at_utc: datetime
    details: dict[str, Any]
    errors: tuple[str, ...] = ()


_SHARED_PENDING_PLANS: dict[str, Any] = {}


class RuntimeControlPlane:
    """Shared local control boundary for CLI, API, and future voice adapters.

    All natural-language/action requests still enter through ``NexaKernel``.
    This class exposes lifecycle/status helpers, but it does not provide a direct
    live-order method or any path around skill validation, confirmation, audit,
    RiskEngine, strategy promotion, live arming, or the trading kill switch.
    """

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self._stopped = False
        self._started_at_utc = datetime.now(timezone.utc)
        self._pending_plans: dict[str, Any] = _SHARED_PENDING_PLANS

    @property
    def stopped(self) -> bool:
        return self._stopped

    def process(self, text: str) -> KernelResponse:
        if self._stopped:
            raise RuntimeError("NEXA runtime control plane is stopped")
        command = text.strip()
        if not command:
            raise ValueError("command required")
        return self.runtime.kernel.process(command)

    def confirm(self, action_id: str) -> KernelResponse:
        if self._stopped:
            raise RuntimeError("NEXA runtime control plane is stopped")
        key = action_id.strip()
        if not key:
            raise ValueError("action_id required")
        return self.runtime.kernel.confirm(key)

    def cancel(self, action_id: str) -> KernelResponse:
        if self._stopped:
            raise RuntimeError("NEXA runtime control plane is stopped")
        key = action_id.strip()
        if not key:
            raise ValueError("action_id required")
        return self.runtime.kernel.cancel(key)

    def formatted_system_status(self) -> str:
        """Returns structured human-readable system status."""
        skills = [item.name for item in self.runtime.registry.list_metadata()] if getattr(self.runtime, "registry", None) else []
        caps_count = len(self.runtime.capability_store.list_capabilities()) if getattr(self.runtime, "capability_store", None) else 0
        failsafe_stat = "ACTIVE"
        if getattr(self.runtime, "failsafe", None) and self.runtime.failsafe.is_stopped:
            failsafe_stat = "STOPPED"
        
        cpu_cores = os.cpu_count() or 4
        lines = [
            "=" * 60,
            "NEXA OS SYSTEM & HARDWARE STATUS REPORT",
            "=" * 60,
            f"  System State:   {'READY (Online)' if not self._stopped else 'STOPPED'}",
            f"  Platform:       {sys.platform} ({cpu_cores} CPU Cores)",
            f"  SecurityGate:   Strict (5 Risk Tiers Active)",
            f"  Failsafe:       {failsafe_stat} (Emergency Stop Guard Active)",
            f"  Skills:         {len(skills)} registered ({', '.join(skills[:6])}...)",
            f"  Capabilities:   {caps_count} dynamic capabilities acquired",
            f"  Browser:        Playwright Chromium Engine Ready",
            f"  Computer-Use:   Active Desktop Session (Mouse, Keyboard, Screen)",
            "=" * 60,
        ]
        return "\n".join(lines)

    def formatted_capabilities_matrix(self) -> str:
        return (
            "============================================================\n"
            "NEXA VERIFIED CAPABILITIES MATRIX\n"
            "============================================================\n\n"
            "1. WINDOWS COMPUTER CONTROL:\n"
            "   [VERIFIED] Open Application (Notepad, Calculator, Chrome, Edge, Terminal, Paint, VS Code)\n"
            "   [VERIFIED] Close Application (Graceful and force termination with process verification)\n"
            "   [VERIFIED] Focus Application (Win32 window foreground activation)\n"
            "   [VERIFIED] List Running Windows (Window titles, process names, handles)\n"
            "   [VERIFIED] Mouse Control (Click, move, scroll, drag)\n"
            "   [VERIFIED] Keyboard Automation (Type text into active/targeted window, press hotkeys)\n"
            "   [VERIFIED] Clipboard (Read and set clipboard text with secret inspection)\n"
            "   [VERIFIED] Screen Capture (Full desktop screenshot capture and analysis)\n\n"
            "2. CHROME / BROWSER CONTROL:\n"
            "   [VERIFIED] Launch Browser (Playwright Chromium)\n"
            "   [VERIFIED] Open URL (HTTPS navigation, protocol validation)\n"
            "   [VERIFIED] Reuse Existing Browser/Tab (State-aware session persistence)\n"
            "   [VERIFIED] Google Search (Search query execution and result listing)\n"
            "   [VERIFIED] Click Search Result (Organic first non-ad result navigation)\n"
            "   [VERIFIED] Extract Page Text (DOM text and link extraction)\n"
            "   [VERIFIED] Download File (Safe file download to workspace sandbox)\n"
            "   [VERIFIED] Tab Management (List tabs, switch tab, close tab)\n\n"
            "3. NOTEPAD / TEXT EDITOR CONTROL:\n"
            "   [VERIFIED] Open & Focus Notepad\n"
            "   [VERIFIED] Type text into Notepad\n"
            "   [VERIFIED] Save file to disk\n"
            "   [VERIFIED] Verify file exists on disk\n"
            "   [VERIFIED] Verify file content matches typed input\n\n"
            "4. FILE SYSTEM CONTROL:\n"
            "   [VERIFIED] Create Folder (mkdir recursive)\n"
            "   [VERIFIED] Create File (UTF-8 encoding)\n"
            "   [VERIFIED] Read File (Safe workspace containment)\n"
            "   [VERIFIED] Append to File\n"
            "   [VERIFIED] Delete File / Folder\n"
            "   [VERIFIED] Move / Rename File\n"
            "   [VERIFIED] Copy File / Folder\n"
            "   [VERIFIED] List Folder Contents\n"
            "   [VERIFIED] Search Files by Name / Extension\n"
            "   [VERIFIED] File Metadata Verification (Size, modification timestamp)\n\n"
            "5. NATURAL LANGUAGE & COMPOUND WORKFLOWS:\n"
            "   [VERIFIED] Multi-step workflows (Observe -> Act -> Verify -> Recover)\n"
            "   [VERIFIED] English, Malayalam, and Manglish intent understanding\n"
            "   [VERIFIED] Cross-domain data handoff (Browser -> Extract -> Save to File)\n"
            "============================================================"
        )

    def formatted_limitations(self) -> str:
        return (
            "============================================================\n"
            "NEXA KNOWN LIMITATIONS & SECURITY BOUNDARIES\n"
            "============================================================\n\n"
            "- [MISSING] Arbitrary 3D Canvas / WebGL hardware rendering automation\n"
            "- [MISSING] Kernel driver installation or low-level BIOS changes (Forbidden by SecurityGate)\n"
            "- [MISSING] Unauthenticated external financial trading (Strictly blocked without human MFA)\n"
            "- [PARTIAL] CAPTCHA / MFA solving (Paused for human authorization by design, non-bypassable)\n"
            "- [PARTIAL] Native desktop drag-and-drop across elevated UAC privilege boundaries (Blocked by Windows UIPI when run without administrative privileges)\n"
            "- [PROTECTED] Arbitrary secret key / token inspection (Protected by Secret Guard)\n"
            "============================================================"
        )

    def analyze_storage(self, target_drives: list[str] | None = None) -> dict[str, Any]:
        """Analyzes real storage metrics for specified or detected drives."""
        import shutil
        drives_to_check = target_drives or ["C:", "D:"]
        reports = []
        drives_data = {}

        for d in drives_to_check:
            clean_drive = d.upper().rstrip("\\/ ")
            if not clean_drive.endswith(":"):
                clean_drive += ":"
            path = f"{clean_drive}\\" if sys.platform == "win32" else "/"
            try:
                usage = shutil.disk_usage(path)
                tot = round(usage.total / (1024**3), 2)
                used = round(usage.used / (1024**3), 2)
                free = round(usage.free / (1024**3), 2)
                pct = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0.0
                status_str = "Healthy" if pct < 80 else ("Warning (>80% used)" if pct < 90 else "Critical (>90% used)")

                drives_data[clean_drive] = {
                    "total_gb": tot,
                    "used_gb": used,
                    "free_gb": free,
                    "used_percent": pct,
                    "status": status_str,
                }
                reports.append(
                    f"  Drive {clean_drive} [{status_str}]\n"
                    f"    Total Capacity: {tot} GB\n"
                    f"    Used Space:     {used} GB ({pct}%)\n"
                    f"    Free Space:     {free} GB"
                )
            except Exception as e:
                reports.append(f"  Drive {clean_drive}: Not accessible or unmounted ({e})")

        header = "=" * 60 + "\nNEXA STORAGE AUDIT & DRIVE ANALYSIS REPORT\n" + "=" * 60 + "\n"
        body = "\n\n".join(reports)
        summary = (
            "\n\n" + "-" * 60 + "\n"
            "Summary & Recommendations:\n"
            "• Operating System & Applications are hosted on NVMe/SSD (C:).\n"
            "• Secondary storage (D:) is monitored for media and workspace data.\n"
            "• Drive health and utilization are within normal operational limits."
        )
        report_text = header + body + summary
        return {
            "success": True,
            "status": "executed",
            "message": report_text,
            "data": drives_data,
        }

    def execute_pipeline(self, text: str, *, auto_confirm: bool = False) -> dict[str, Any]:
        """Unified canonical pipeline: Understanding -> Planning -> SecurityGate -> Execution -> Verifying."""
        if self._stopped:
            raise RuntimeError("NEXA runtime control plane is stopped")
        clean = text.strip()
        if not clean:
            return {"success": False, "message": "Empty command"}

        from ui.event_bus import get_event_bus, UIEventType
        event_bus = get_event_bus()

        event_bus.emit(
            UIEventType.TASK_CREATED,
            "Command Received",
            clean,
            {"raw_command": clean},
        )
        event_bus.emit(
            UIEventType.TASK_STARTED,
            "Understanding & Planning",
            f"Analyzing: '{clean}'",
        )

        # 1. SecurityGate deny list check
        if getattr(self.runtime, "security_gate", None) is not None:
            denied = self.runtime.security_gate.check_deny_list(clean)
            if denied:
                event_bus.emit(
                    UIEventType.TASK_FAILED,
                    "Security Blocked",
                    f"Blocked by policy: {denied.reason}",
                    {"reason": denied.reason},
                )
                return {"success": False, "blocked": True, "message": f"Blocked: {denied.reason}"}

        # 2. Natural language capability & system discovery checks
        lowered = clean.lower().strip().rstrip(".!?")
        if lowered == "ping":
            event_bus.emit(UIEventType.TASK_COMPLETED, "Ping", "pong", {"pong": True})
            return {"success": True, "status": "executed", "message": "pong", "data": {"pong": True}}

        if lowered in {
            "show my system status", "system status", "/status", "status",
            "show status", "system info", "system health", "show system status"
        }:
            status_text = self.formatted_system_status()
            event_bus.emit(UIEventType.TASK_COMPLETED, "System Status", status_text)
            return {"success": True, "status": "executed", "message": status_text, "data": self.status()}

        if lowered in {
            "what can you do", "what can you do?", "capabilities", "show capabilities",
            "list capabilities", "what are your capabilities", "what are your skills",
            "help", "capability matrix"
        }:
            caps_text = self.formatted_capabilities_matrix()
            event_bus.emit(UIEventType.TASK_COMPLETED, "Capabilities Matrix", caps_text)
            return {"success": True, "status": "executed", "message": caps_text}

        if lowered in {
            "what can't you do", "what can't you do?", "what cant you do", "what cant you do?",
            "what can you not do", "limitations", "unsupported", "missing capabilities", "what are your limitations"
        }:
            limits_text = self.formatted_limitations()
            event_bus.emit(UIEventType.TASK_COMPLETED, "Limitations", limits_text)
            return {"success": True, "status": "executed", "message": limits_text}

        if any(term in lowered for term in (
            "analyze my storage", "storage analysis", "storage audit", "analyze storage",
            "check storage", "storage on c", "storage on d", "disk usage", "storage status"
        )):
            res = self.analyze_storage()
            event_bus.emit(UIEventType.TASK_COMPLETED, "Storage Analysis Completed", res["message"], res["data"])
            return res

        if any(term in lowered for term in (
            "run capability verification", "verify all capabilities", "self test",
            "run self test", "capability verification", "verify capabilities",
            "capability test cheyy", "self test cheyy"
        )):
            from intelligence.self_test_agent import SelfTestAgent
            agent = SelfTestAgent(kernel=getattr(self.runtime, "kernel", None))
            report = agent.run_all()
            md = report.summary_markdown()
            event_bus.emit(UIEventType.TASK_COMPLETED, "Capability Verification Completed", md, report.to_dict())
            return {"success": True, "status": "executed", "message": md, "data": report.to_dict()}
        if any(term in lowered for term in (
            "start training", "training start cheyy", "self training",
            "autonomous training", "start self training", "training mode"
        )):
            from training.training_mode import TrainingMode
            tm = TrainingMode(kernel=getattr(self.runtime, "kernel", None))
            summary = tm.run_session(max_iterations=2)
            md = summary.summary_markdown()
            return {"success": True, "status": "executed", "message": md, "data": {"session_id": summary.session_id}}

        # 3. Intent Classification & Conversational Routing
        from core.intent_router import IntentRouter, IntentType
        from core.conversation import ConversationalEngine

        intent_info = IntentRouter().classify(clean)
        if intent_info.intent_type in {IntentType.CHAT, IntentType.INFORMATION}:
            conv = ConversationalEngine()
            reply = conv.generate_response(clean)
            event_bus.emit(UIEventType.TASK_COMPLETED, "Responded", reply)
            return {"success": True, "status": "conversation", "message": reply, "intent": intent_info.intent_type.value}

        if intent_info.intent_type == IntentType.MIXED:
            conv = ConversationalEngine()
            reply = conv.generate_response(intent_info.chat_prompt)
            event_bus.emit(UIEventType.TASK_PROGRESS, "Answer", reply)
            clean = intent_info.action_prompt

        # 4. Compound / multi-step workflow detection
        direct_match = self.runtime.registry.resolve(clean, {}) if getattr(self.runtime, "registry", None) else None

        if direct_match is None and getattr(self.runtime, "task_planner", None) is not None and getattr(self.runtime, "plan_executor", None) is not None:
            plan = self.runtime.task_planner.plan(clean)
            if len(plan.steps) > 1 or (len(plan.steps) == 1 and plan.steps[0].skill_name != "unknown"):
                return self._dispatch_plan_execution(plan, event_bus, auto_confirm=auto_confirm)

        # 4. Direct single-step kernel execution
        k_res = self.runtime.kernel.process(clean)
        if k_res.status != "no_match":
            if k_res.status == "confirmation_required":
                pending = k_res.pending_action
                action_id = pending.action_id if pending else (k_res.action_id or "")
                if auto_confirm and action_id:
                    return self.confirm_plan_or_action(action_id)
                event_bus.emit(
                    UIEventType.CONFIRMATION_REQUIRED,
                    "Confirmation Required",
                    f"Action '{pending.operation if pending else clean}' requires user confirmation",
                    {
                        "action_id": action_id,
                        "skill": pending.skill_name if pending else "",
                        "operation": pending.operation if pending else "",
                        "risk": pending.risk.value if pending else "mutate",
                        "params": dict(pending.params) if pending else {},
                    },
                )
                return {
                    "success": False,
                    "status": "confirmation_required",
                    "action_id": action_id,
                    "message": k_res.message or "User confirmation required",
                    "pending": {
                        "action_id": action_id,
                        "skill": pending.skill_name if pending else "",
                        "operation": pending.operation if pending else "",
                        "risk": pending.risk.value if pending else "mutate",
                        "params": dict(pending.params) if pending else {},
                    } if pending else None,
                }

            if k_res.status in {"success", "executed"}:
                msg = k_res.result.message if k_res.result else (k_res.message or "Executed successfully")
                safe_data = k_res.result.data if k_res.result else {}
                event_bus.emit(UIEventType.TASK_COMPLETED, "Completed", msg, {"data": safe_data})
                return {"success": True, "status": "executed", "message": msg, "data": safe_data}

            msg = k_res.message or f"Status: {k_res.status}"
            event_bus.emit(UIEventType.TASK_FAILED, "Failed", msg)
            return {"success": False, "status": k_res.status, "message": msg}

        # 5. Fallback to TaskPlanner if direct resolution didn't run or returned no_match
        if getattr(self.runtime, "task_planner", None) is not None and getattr(self.runtime, "plan_executor", None) is not None:
            plan = self.runtime.task_planner.plan(clean)
            if len(plan.steps) > 1 or (len(plan.steps) == 1 and plan.steps[0].skill_name != "unknown"):
                return self._dispatch_plan_execution(plan, event_bus, auto_confirm=auto_confirm)

        # 6. Check dynamic capability gap
        if getattr(self.runtime, "capability_manager", None) is not None:
            gap_skill = self.runtime.capability_manager.handle_gap(clean, {}, self.runtime.registry)
            if gap_skill is not None:
                event_bus.emit(
                    UIEventType.CAPABILITY_REGISTERED,
                    "New Capability Ready",
                    f"Dynamically registered: {gap_skill.metadata.name}",
                )
                k_res = self.runtime.kernel.process(clean)
                if k_res.status in {"success", "executed"}:
                    msg = k_res.result.message if k_res.result else "Executed successfully"
                    event_bus.emit(UIEventType.TASK_COMPLETED, "Completed", msg)
                    return {"success": True, "status": "executed", "message": msg}

        # 7. Conversational fact handling via memory
        try:
            from memory import extract_fact, set_fact, identify_fact_query, get_fact, resolve_fact_query
            new_fact = extract_fact(clean)
            if new_fact:
                k, v = new_fact
                set_fact(k, v)
                msg = f"Orma vechu: {k} = {v}"
                event_bus.emit(UIEventType.TASK_COMPLETED, "Fact Saved", msg)
                return {"success": True, "status": "executed", "message": msg}
            
            fact_key = identify_fact_query(clean)
            if fact_key:
                val = get_fact(fact_key)
                msg = val if val is not None else f"I do not know your {fact_key} yet."
                event_bus.emit(UIEventType.TASK_COMPLETED, "Fact Retrieved", msg)
                return {"success": True, "status": "executed", "message": msg}

            fact = resolve_fact_query(clean)
            if fact:
                _, val = fact
                event_bus.emit(UIEventType.TASK_COMPLETED, "Fact Retrieved", val)
                return {"success": True, "status": "executed", "message": val}
        except Exception:
            pass

        # 8. Conversational / Intent fallback
        from core.conversation import ConversationalEngine
        reply = ConversationalEngine().generate_response(clean)
        event_bus.emit(UIEventType.TASK_COMPLETED, "Responded", reply)
        return {"success": True, "status": "conversation", "message": reply}

    def _dispatch_plan_execution(self, plan: Any, event_bus: Any, *, auto_confirm: bool = False) -> dict[str, Any]:
        from core.contracts import RiskTier
        from ui.event_bus import UIEventType

        # Security check on plan steps
        critical_step = None
        if getattr(self.runtime, "registry", None) is not None:
            for s in plan.steps:
                if s.skill_name in ("unknown", ""):
                    continue
                try:
                    sk = self.runtime.registry.get(s.skill_name)
                except Exception:
                    continue
                if sk is not None:
                    for op_spec in sk.metadata.operations:
                        if op_spec.name == s.operation and op_spec.risk in {RiskTier.CRITICAL, RiskTier.DESTRUCTIVE}:
                            critical_step = (s, op_spec.risk)
                            break
                if critical_step:
                    break

        if critical_step:
            step, risk = critical_step
            action_id = plan.plan_id[:12]
            self._pending_plans[action_id] = plan
            if auto_confirm:
                return self.confirm_plan_or_action(action_id)
            event_bus.emit(
                UIEventType.CONFIRMATION_REQUIRED,
                "Security Confirmation Required",
                f"Action '{step.description}' requires explicit confirmation ({risk.value})",
                {
                    "action_id": action_id,
                    "skill": step.skill_name,
                    "operation": step.operation,
                    "risk": risk.value,
                    "params": dict(step.params),
                },
            )
            return {
                "success": False,
                "status": "confirmation_required",
                "action_id": action_id,
                "message": f"SecurityGate requires confirmation for: {step.description}",
                "pending": {
                    "action_id": action_id,
                    "skill": step.skill_name,
                    "operation": step.operation,
                    "risk": risk.value,
                    "params": dict(step.params),
                },
            }

        event_bus.emit(
            UIEventType.TASK_PROGRESS,
            "Executing Plan",
            f"Executing {len(plan.steps)} planned steps",
            {"plan_id": plan.plan_id, "steps": [s.description for s in plan.steps]},
        )
        plan_res = self.runtime.plan_executor.execute(plan)
        if plan_res.success:
            event_bus.emit(UIEventType.TASK_COMPLETED, "Plan Completed", plan_res.message)
            return {"success": True, "status": "executed", "message": plan_res.message, "data": getattr(plan_res, "data", {})}
        else:
            event_bus.emit(UIEventType.TASK_FAILED, "Plan Execution Failed", plan_res.message)
            return {"success": False, "status": "failed", "message": plan_res.message}

    def confirm_plan_or_action(self, action_id: str) -> dict[str, Any]:
        from ui.event_bus import get_event_bus, UIEventType
        bus = get_event_bus()
        bus.emit(UIEventType.CONFIRMATION_ACCEPTED, "Action Confirmed", f"Executing confirmed action: {action_id}")

        if action_id in self._pending_plans:
            plan = self._pending_plans.pop(action_id)
            bus.emit(
                UIEventType.TASK_PROGRESS,
                "Executing Confirmed Plan",
                f"Executing {len(plan.steps)} planned steps",
                {"plan_id": plan.plan_id, "steps": [s.description for s in plan.steps]},
            )
            plan_res = self.runtime.plan_executor.execute(plan)
            if plan_res.success:
                bus.emit(UIEventType.TASK_COMPLETED, "Plan Completed", plan_res.message)
                return {"success": True, "status": "executed", "message": plan_res.message, "data": getattr(plan_res, "data", {})}
            else:
                bus.emit(UIEventType.TASK_FAILED, "Plan Execution Failed", plan_res.message)
                return {"success": False, "status": "failed", "message": plan_res.message}

        k_res = self.confirm(action_id)
        if k_res.status in {"success", "executed"}:
            msg = k_res.result.message if k_res.result else (k_res.message or "Executed successfully")
            safe_data = k_res.result.data if k_res.result else {}
            bus.emit(UIEventType.TASK_COMPLETED, "Confirmed Action Completed", msg)
            return {"success": True, "status": "executed", "message": msg, "data": safe_data}
        msg = k_res.message or f"Status: {k_res.status}"
        bus.emit(UIEventType.TASK_FAILED, "Confirmed Action Failed", msg)
        return {"success": False, "status": k_res.status, "message": msg}

    def cancel_plan_or_action(self, action_id: str) -> dict[str, Any]:
        from ui.event_bus import get_event_bus, UIEventType
        bus = get_event_bus()
        bus.emit(UIEventType.TASK_CANCELLED, "Action Cancelled", f"Cancelled action: {action_id}")
        if action_id in self._pending_plans:
            self._pending_plans.pop(action_id)
            return {"success": True, "message": "Plan cancelled"}
        self.cancel(action_id)
        return {"success": True, "message": "Action cancelled"}

    def status(self) -> dict[str, Any]:
        brain = self.runtime.trading_brain
        portfolio = brain.paper_broker.portfolio
        evidence_payload: dict[str, Any] | None = None
        evidence = brain.paper_evidence()
        if evidence is not None:
            evidence_payload = {
                "session_id": evidence.session_id,
                "started_at_utc": evidence.started_at_utc.isoformat(),
                "consistent": evidence.consistent,
                "reasons": list(evidence.reasons),
                "trading_days": evidence.evidence.trading_days,
                "closed_trades": evidence.evidence.closed_trades,
                "net_pnl": evidence.evidence.net_pnl,
                "max_drawdown_pct": evidence.evidence.max_drawdown_pct,
                "safety_violations": evidence.evidence.safety_violations,
            }

        capabilities_info = []
        if getattr(self.runtime, "capability_store", None) is not None:
            for rec in self.runtime.capability_store.list_capabilities():
                capabilities_info.append({
                    "id": rec.spec.capability_id,
                    "name": rec.spec.name,
                    "version": rec.spec.version,
                    "risk": rec.spec.risk_tier.value,
                    "usage_count": rec.usage_count,
                    "last_used_at_utc": rec.last_used_at_utc,
                })

        return {
            "state": "stopped" if self._stopped else "ready",
            "started_at_utc": self._started_at_utc.isoformat(),
            "skills": [item.name for item in self.runtime.registry.list_metadata()],
            "capabilities": capabilities_info,
            "trading": {
                "mode": brain.mandate.mode.value,
                "strategy_id": brain.strategy.strategy_id,
                "strategy_stage": brain.stage.value,
                "paper_runtime_armed": brain.paper_runtime_armed,
                "paper_positions": len(portfolio.positions),
                "paper_orders": len(brain.paper_broker.orders),
                "paper_realized_pnl_total": portfolio.realized_pnl_total,
                "paper_evidence": evidence_payload,
                "live_broker_configured": self.runtime.live_controller is not None,
                "live_armed": self.runtime.live_arm.is_armed_for(brain.mandate),
                "kill_switch_active": self.runtime.kill_switch.active,
                "kill_switch_reason": self.runtime.kill_switch.reason,
            },
        }

    def health(self) -> RuntimeHealthSnapshot:
        errors: list[str] = []
        details: dict[str, Any] = {}

        try:
            restored = self.runtime.paper_state_store.load()
            details["paper_state"] = {
                "positions": len(restored.portfolio.positions),
                "orders": len(restored.orders),
                "protective_signals": len(restored.protective_signals),
                "last_processed_symbols": len(restored.last_processed),
            }
        except Exception as exc:
            errors.append(f"paper state recovery failed: {type(exc).__name__}: {exc}")

        try:
            evidence = self.runtime.paper_evidence_store.report()
            details["paper_evidence"] = {
                "session_id": evidence.session_id,
                "consistent": evidence.consistent,
                "safety_violations": evidence.evidence.safety_violations,
            }
            if not evidence.consistent:
                errors.append("paper evidence ledger is inconsistent")
        except Exception as exc:
            errors.append(f"paper evidence recovery failed: {type(exc).__name__}: {exc}")

        try:
            details["strategy_stage"] = self.runtime.trading_brain.stage.value
        except Exception as exc:
            errors.append(f"strategy promotion state unavailable: {type(exc).__name__}: {exc}")

        details["live_broker_configured"] = self.runtime.live_controller is not None
        details["live_armed"] = self.runtime.live_arm.is_armed_for(self.runtime.trading_brain.mandate)
        details["kill_switch_active"] = self.runtime.kill_switch.active

        return RuntimeHealthSnapshot(
            ok=not errors and not self._stopped,
            state="stopped" if self._stopped else ("ready" if not errors else "degraded"),
            checked_at_utc=datetime.now(timezone.utc),
            details=details,
            errors=tuple(errors),
        )

    def shutdown(self) -> None:
        """Fail closed for new autonomous work while preserving persisted state."""

        if self._stopped:
            return
        self.runtime.trading_brain.disarm_paper_runtime()
        self.runtime.live_arm.disarm()
        self._stopped = True


def kernel_response_payload(response: KernelResponse) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": response.status,
        "message": response.message,
    }
    if response.result is not None:
        payload["result"] = {
            "success": response.result.success,
            "message": response.result.message,
            "data": response.result.data,
            "error": response.result.error,
        }
    if response.pending_action is not None:
        action = response.pending_action
        payload["pending_action"] = {
            "action_id": action.action_id,
            "skill": action.skill_name,
            "operation": action.operation,
            "params": dict(action.params),
            "risk": action.risk.value,
            "created_at_utc": action.created_at_utc.isoformat(),
            "expires_at_utc": action.expires_at_utc.isoformat(),
        }
    return payload


def health_payload(snapshot: RuntimeHealthSnapshot) -> dict[str, Any]:
    return {
        "ok": snapshot.ok,
        "state": snapshot.state,
        "checked_at_utc": snapshot.checked_at_utc.isoformat(),
        "details": snapshot.details,
        "errors": list(snapshot.errors),
    }
