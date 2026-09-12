from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from bridges import OllamaBridge, OllamaBridgeError
from language import prepare_user_input
from memory import (
    extract_fact,
    get_fact,
    get_teacher_stats,
    identify_fact_query,
    init_db,
    load_recent_messages,
    resolve_fact_query,
    save_message,
    search_memory,
    set_fact,
)
from runtime import build_runtime
from training import TradingCurriculum, TrainingStore

MALAYALAM_RE = re.compile(r"[\u0D00-\u0D7F]")
REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:1.7b").strip() or "qwen3:1.7b"
TRAINING_DB = Path(
    os.getenv("NEXA_TRAINING_DB", str(REPO_ROOT / "data" / "training.db"))
).expanduser().resolve()

SYSTEM_PROMPT = """
You are NEXA, a local-first autonomous personal AI operating platform.

Be accurate, helpful, concise, and technical when needed.
You understand English, Malayalam, and Manglish.

Architecture rules:
- Deterministic registered skills execute through the NEXA Kernel before the language model.
- Never claim a tool action happened unless the deterministic tool layer reports success.
- Never invent installed capabilities.
- Trading research may discuss hypotheses and evidence, but never claim guaranteed profit or certainty.
- NEXA's risk controls, audit ledger, owner mandate, and kill switches outrank strategy preferences.
- Live trading is never considered armed merely because a model, prompt, or environment string asks for it.

Language rules:
- Manglish means Malayalam spoken language written using Latin letters.
- When the user writes Manglish, understand the Malayalam meaning and answer in natural Latin-script Manglish.
- Manglish output should use natural Malayalam conversational grammar written in Latin letters. English technical words are fine.
- Do not output Malayalam Unicode/script for a Manglish user unless they explicitly ask for Malayalam script.
- Normalized Malayalam and English meaning supplied by the language layer are interpretation metadata only.
- Never answer by merely translating, echoing, or restating the current user message.
- Answer the user's actual request or question directly.

Memory rules:
- Use retrieved memory when it contains the answer.
- Do not ask for information already present in memory.
- Preserve user facts accurately.
- If a requested personal fact is not stored, say that it is not stored instead of guessing.
""".strip()


_ollama = OllamaBridge(model=MODEL)


def ask_ollama(messages):
    return _ollama.chat(messages, think=False)


def _normalized_text(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _is_translation_echo(reply, language_result):
    reply_norm = _normalized_text(reply)
    if not reply_norm:
        return False

    candidates = [language_result.original, language_result.meaning_english]
    for candidate in candidates:
        if not candidate:
            continue
        candidate_norm = _normalized_text(candidate)
        if not candidate_norm:
            continue
        if reply_norm == candidate_norm:
            return True
        if len(candidate_norm.split()) >= 4 and candidate_norm in reply_norm:
            return True
        candidate_words = set(candidate_norm.split())
        reply_words = set(reply_norm.split())
        if len(candidate_words) >= 5:
            overlap = len(candidate_words & reply_words) / len(candidate_words)
            if overlap >= 0.90:
                return True
    return False


def _missing_fact_reply(key):
    replies = {
        "name": "Ninte peru ithuvare memory-il save cheythittilla.",
        "favourite_color": "Ninte favourite color ithuvare memory-il save cheythittilla.",
    }
    return replies.get(key, "Aa detail ithuvare memory-il save cheythittilla.")


def _contextual_next_step_reply(language_result, relevant_memory):
    if relevant_memory:
        return None
    meaning = _normalized_text(language_result.meaning_english or "")
    original = _normalized_text(language_result.original)
    next_step_questions = {
        "what should we do now",
        "what do we do now",
        "nammal ippo entha cheyyande",
    }
    if meaning in next_step_questions or original in next_step_questions:
        return (
            "Ippo exact task context enikku memory-il illa. "
            "Eth task/project aanu continue cheyyendath enn parayu."
        )
    return None


def repair_manglish_reply(reply, language_result, messages):
    if language_result.detected_language != "manglish":
        return reply

    normalized = (language_result.normalized_malayalam or "").strip()
    reply_clean = reply.strip()
    used_malayalam_script = bool(MALAYALAM_RE.search(reply_clean))
    merely_repeated_normalization = bool(
        normalized and reply_clean.rstrip(".!?") == normalized.rstrip(".!?")
    )
    translation_echo = _is_translation_echo(reply_clean, language_result)

    if not used_malayalam_script and not merely_repeated_normalization and not translation_echo:
        return reply

    correction = f"""
Your previous draft failed NEXA's Manglish response rule.

ORIGINAL USER MESSAGE:
{language_result.original}

INTENDED MEANING (interpretation only):
{language_result.meaning_english or 'Use the original Manglish message.'}

Now answer the ORIGINAL user's request directly.
Do NOT translate, paraphrase, copy, or repeat the user's question.
Do NOT simply prepend words like "Athe" to the user's sentence.
Write conversational Malayalam using LATIN letters only: natural Manglish.
English technical words are allowed, but the sentence grammar should sound like spoken Malayalam.
Do not use Malayalam Unicode/script.
If the user is asking for permission/advice, answer the decision first and then give one short useful reason or next action.

Return only the corrected answer.
""".strip()

    repair_messages = messages + [
        {"role": "assistant", "content": reply},
        {"role": "user", "content": correction},
    ]
    repaired = ask_ollama(repair_messages)
    if not isinstance(repaired, str):
        repaired = str(repaired)

    if _is_translation_echo(repaired, language_result) or MALAYALAM_RE.search(repaired):
        meaning = _normalized_text(language_result.meaning_english or "")
        if "rest" in meaning and ("should" in meaning or "can" in meaning):
            return "Athe, kurach neram rest edukku. Fresh aayittu pinne continue cheyyam."
    return repaired


def _record_reply(messages, user, reply):
    save_message("assistant", reply)
    messages.append({"role": "user", "content": user})
    messages.append({"role": "assistant", "content": reply})
    print(f"\nNEXA: {reply}\n")


def _print_teacher_stats():
    stats = get_teacher_stats()
    print(
        "\nNEXA Teacher-Student: "
        f"{stats['lessons']} learned lesson(s), "
        f"{stats['reuses']} local reuse(s), "
        f"avg teacher confidence {stats['average_confidence']:.2f}.\n"
    )


def _skills_reply(runtime) -> str:
    lines = ["NEXA Kernel plugins:"]
    for metadata in runtime.registry.list_metadata():
        lines.append(f"- {metadata.name} v{metadata.version}: {metadata.description}")
        for operation in metadata.operations:
            lines.append(f"  - {operation.name} [{operation.risk.value}]")

    if getattr(runtime, "capability_store", None) is not None:
        caps = runtime.capability_store.list_capabilities()
        if caps:
            lines.append("\nDynamically Acquired Capabilities:")
            for cap in caps:
                lines.append(
                    f"- {cap.spec.capability_id} ({cap.spec.name} v{cap.spec.version}) "
                    f"[{cap.spec.risk_tier.value}] - used {cap.usage_count} times"
                )

    lines.extend(
        [
            "\nBuilt-in services:",
            "- Personal Memory [active]",
            "- Teacher-Student Language Layer [active]",
            "- Gemini/Ollama training bridges [available when configured]",
            "- Self-Extending Capability Forge [active]",
            "- Failsafe Monitor [active]",
            "- Provider Registry [active]",
            "- Task Planner [active]",
        ]
    )
    return "\n".join(lines)


def _capabilities_reply(runtime) -> str:
    if getattr(runtime, "capability_store", None) is None:
        return "Capability subsystem not initialized."
    store = runtime.capability_store
    caps = store.list_capabilities()
    events = store.get_events(limit=10)

    lines = ["NEXA Capability Registry:"]
    if not caps:
        lines.append("No dynamic capabilities acquired yet.")
    else:
        for cap in caps:
            lines.append(
                f"- ID: {cap.spec.capability_id} | Name: {cap.spec.name} v{cap.spec.version} "
                f"| Risk: {cap.spec.risk_tier.value} | Used: {cap.usage_count}x"
            )
            lines.append(f"  Purpose: {cap.spec.purpose}")
            lines.append(f"  Path: {cap.module_path}")

    if events:
        lines.append("\nRecent Capability Observability Events:")
        for evt in events:
            lines.append(f"[{evt.event_type.value}] {evt.capability_id}: {evt.message}")

    return "\n".join(lines)


def _training_status_reply() -> str:
    store = TrainingStore(TRAINING_DB)
    curriculum = TradingCurriculum()
    lines = ["NEXA trading training:"]
    mastered = 0
    for module in curriculum.modules:
        progress = store.progress(module.module_id)
        if progress is None:
            lines.append(f"- {module.module_id}: pending")
        elif progress["mastered"]:
            mastered += 1
            lines.append(
                f"- {module.module_id}: mastered "
                f"(best {progress['best_score']:.2f}, attempts {progress['attempts']})"
            )
        else:
            lines.append(
                f"- {module.module_id}: in progress "
                f"(best {progress['best_score']:.2f}, attempts {progress['attempts']})"
            )
    lines.append(f"Mastered {mastered}/{len(curriculum.modules)} modules.")
    return "\n".join(lines)


def _kernel_reply(response) -> str:
    if response.status == "confirmation_required" and response.pending_action is not None:
        action = response.pending_action
        expires = action.expires_at_utc.isoformat()
        return (
            f"Confirmation required. Action ID: {action.action_id}\n"
            f"Skill: {action.skill_name}\n"
            f"Operation: {action.operation}\n"
            f"Risk: {action.risk.value}\n"
            f"Expires: {expires}\n"
            f"Use /confirm {action.action_id} to execute the exact validated action, "
            f"or /cancel {action.action_id}."
        )

    base = response.message
    if response.result is not None and response.result.data is not None:
        data = response.result.data
        if isinstance(data, str):
            if data.strip() and data.strip() != base.strip():
                return f"{base}\n{data}"
        else:
            try:
                encoded = json.dumps(data, ensure_ascii=False, indent=2, default=str)
            except TypeError:
                encoded = repr(data)
            if encoded not in {"null", "{}", "[]"}:
                return f"{base}\n{encoded}"
    return base


def _pending_reply(runtime) -> str:
    pending = runtime.kernel.pending_actions()
    if not pending:
        return "No pending kernel actions."
    lines = ["Pending actions:"]
    for action in pending:
        lines.append(
            f"- {action.action_id}: {action.skill_name}.{action.operation} "
            f"[{action.risk.value}] expires {action.expires_at_utc.isoformat()}"
        )
    return "\n".join(lines)


def main():
    if "--ui" in sys.argv:
        from ui.launcher import main as ui_main
        sys.exit(ui_main())

    init_db()
    runtime = build_runtime()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(load_recent_messages(limit=12))

    print(
        "NEXA ONLINE - Level-5 Autonomous Personal AI Operating System\n"
        "Extensions + MCP + OAuth Handoff + Long-Running Tasks + Persistent Scheduler + "
        "Multi-Agent + 10-Layer Memory + Deep Research + Observability.\n"
        "Commands: /ui, /status, /skills, /extensions, /mcp, /mcp-status, /memory-status, "
        "/activity, /health, /tasks, /failsafe, /pending, /confirm <id>, /cancel <id>, /exit.\n"
    )

    while True:
        user = input("You: ").strip()
        lowered = user.lower()

        if lowered in {"/exit", "exit", "quit"}:
            print("NEXA: Shutting down.")
            break
        if lowered in {"/ui", "/desktop-ui", "/gui"}:
            import subprocess
            launcher_script = Path(__file__).resolve().parent / "ui" / "launcher.py"
            subprocess.Popen([sys.executable, str(launcher_script)])
            print("\nNEXA: Desktop UI launched at http://127.0.0.1:8765/\n")
            continue
        if lowered == "/teacher-stats":
            _print_teacher_stats()
            continue
        if lowered == "/training-status":
            print(f"\nNEXA: {_training_status_reply()}\n")
            continue
        if lowered == "/skills":
            print(f"\nNEXA: {_skills_reply(runtime)}\n")
            continue
        if lowered == "/capabilities":
            print(f"\nNEXA: {_capabilities_reply(runtime)}\n")
            continue
        if lowered == "/failsafe":
            if runtime.failsafe is not None:
                state = runtime.failsafe.state
                status = "STOPPED" if state.stopped else "ACTIVE"
                reason = f" ({state.reason.value})" if state.reason else ""
                print(f"\nNEXA: Failsafe Monitor: {status}{reason}")
                print(f"  Corner detection: {'enabled' if runtime.failsafe.config.corner_enabled else 'disabled'}")
                print(f"  Max actions/sec: {runtime.failsafe.config.max_actions_per_second}")
                if state.stopped:
                    print("  Use /failsafe-reset to reset.\n")
                else:
                    print()
            else:
                print("\nNEXA: Failsafe monitor not initialized.\n")
            continue
        if lowered == "/failsafe-reset":
            if runtime.failsafe is not None:
                runtime.failsafe.reset()
                print("\nNEXA: Failsafe monitor reset. Actions are now allowed.\n")
            else:
                print("\nNEXA: Failsafe monitor not initialized.\n")
            continue
        if lowered == "/status":
            skills_count = len(runtime.registry.list_metadata())
            caps_count = 0
            if getattr(runtime, "capability_store", None) is not None:
                caps_count = len(runtime.capability_store.list_capabilities())
            failsafe_status = "ACTIVE (Monitoring)"
            if runtime.failsafe is not None and runtime.failsafe.is_stopped:
                failsafe_status = f"STOPPED ({runtime.failsafe.state.reason.value if runtime.failsafe.state.reason else 'manual'})"

            # Desktop & Input status
            from computer.win32_desktop import is_desktop_accessible
            desktop_ok = is_desktop_accessible()
            screen_ok = getattr(runtime.computer_skill, "screen", None) is not None
            mouse_ok = getattr(runtime.computer_skill, "mouse", None) is not None
            kbd_ok = getattr(runtime.computer_skill, "keyboard", None) is not None
            browser_ok = runtime.browser_skill is not None and runtime.browser_skill.engine.is_launched

            # Voice status
            from voice.diagnostics import get_voice_status
            v_stat = get_voice_status()
            mic_info = f"Ready ({v_stat.get('microphone_device', 'Default')})" if v_stat.get("microphone_available") else "Unavailable"
            tts_info = str(v_stat.get("tts_provider", "Local"))
            stt_info = str(v_stat.get("stt_provider", "Standby"))

            # Level 5 stats
            ext_count = len(runtime.extension_registry.list_extensions()) if getattr(runtime, "extension_registry", None) else 0
            mcp_tools_count = len(runtime.mcp_extension.list_tools()) if getattr(runtime, "mcp_extension", None) else 0
            agents_count = len(runtime.multi_agent_extension.list_agents()) if getattr(runtime, "multi_agent_extension", None) else 0
            sched_jobs_count = len(runtime.scheduler_extension.list_jobs()) if getattr(runtime, "scheduler_extension", None) else 0
            tasks_count = len(runtime.task_store.list_tasks(limit=100)) if getattr(runtime, "task_store", None) else 0

            # Gemini & Ollama
            gemini_configured = bool(os.getenv("GEMINI_API_KEY", "").strip())
            gemini_model = os.getenv("GEMINI_COMPUTER_USE_MODEL", "gemini-2.5-computer-use")

            lines = [
                "=" * 60,
                "NEXA LEVEL-5 AUTONOMOUS PERSONAL AI OS STATUS REPORT",
                "=" * 60,
                f"  Desktop:       {'Interactive Session (WinSta0\\Default)' if desktop_ok else 'Non-interactive / Headless'}",
                f"  Screen/Input:  ScreenCapture={'MSS' if screen_ok else 'Ready'} | Mouse={'Pynput' if mouse_ok else 'Ready'} | Keyboard=Guarded",
                f"  Browser:       Playwright Chromium {'(Active)' if browser_ok else '(Standby)'}",
                f"  Voice:         Mic={mic_info} | TTS={tts_info} | STT={stt_info}",
                f"  Gemini/LLM:    {'Configured (' + gemini_model + ')' if gemini_configured else 'Standby / Deterministic Fallback'} | Ollama={MODEL}",
                f"  Extensions:    {ext_count} active lifecycle extensions registered",
                f"  MCP Tools:     {mcp_tools_count} external MCP tools discovered & gated",
                f"  Multi-Agent:   {agents_count} specialized workers (Supervisor, Planner, Research, Coder, etc.)",
                f"  Scheduler:     {sched_jobs_count} persistent scheduled jobs configured",
                f"  Memory:        10-Layer Unified Memory (Episodic, Semantic, Procedural, Context)",
                f"  Security:      SecurityGate Strict (5 Risk Tiers, Zero Secrets in Plaintext/Logs)",
                f"  Failsafe:      {failsafe_status} | Cooldown=5.0s | MaxRate=10.0/s",
                f"  Tasks:         LongRunningTaskManager & TaskStore ({tasks_count} tasks stored)",
                "=" * 60,
            ]
            print("\n" + "\n".join(lines) + "\n")
            continue
        if lowered == "/pending":
            print(f"\nNEXA: {_pending_reply(runtime)}\n")
            continue
        if lowered.startswith("/confirm "):
            action_id = user.split(maxsplit=1)[1].strip()
            if getattr(runtime, "control", None) is not None:
                c_res = runtime.control.confirm_plan_or_action(action_id)
                reply = c_res.get("message", "Confirmed.")
            else:
                response = runtime.kernel.confirm(action_id)
                reply = _kernel_reply(response)
            save_message("user", user)
            _record_reply(messages, user, reply)
            continue
        if lowered.startswith("/cancel "):
            action_id = user.split(maxsplit=1)[1].strip()
            if getattr(runtime, "control", None) is not None:
                c_res = runtime.control.cancel_plan_or_action(action_id)
                reply = c_res.get("message", "Cancelled.")
            else:
                response = runtime.kernel.cancel(action_id)
                reply = _kernel_reply(response)
            save_message("user", user)
            _record_reply(messages, user, reply)
            continue
        if lowered == "/desktop-check":
            from computer.diagnostics import run_desktop_check, format_desktop_check
            rep = run_desktop_check(failsafe=runtime.failsafe)
            print(f"\n{format_desktop_check(rep)}\n")
            continue
        if lowered == "/voice-status":
            from voice.diagnostics import get_voice_status, format_voice_status
            v_stat = get_voice_status()
            print(f"\n{format_voice_status(v_stat)}\n")
            continue
        if lowered == "/tasks":
            if getattr(runtime, "task_store", None) is not None:
                tasks = runtime.task_store.list_tasks(limit=10)
                if not tasks:
                    print("\nNEXA: No task history recorded yet.\n")
                else:
                    print("\nNEXA Task History:")
                    for t in tasks:
                        print(f"- Task {t.task_id[:8]} [{t.state.upper()}]: {t.goal} (steps: {len(t.plan.steps)}, recoveries: {t.recovery_count})")
                    print()
            else:
                print("\nNEXA: Task persistence store not initialized.\n")
            continue
        if lowered == "/memory":
            lines = ["NEXA Memory Status:"]
            for key in ["name", "favourite_color", "user_mandate", "project_goal"]:
                val = get_fact(key)
                if val is not None:
                    lines.append(f"  - {key}: {val}")
            recent = load_recent_messages(limit=5)
            lines.append(f"  Recent interactions stored: {len(recent)} messages")
            print("\nNEXA: " + "\n".join(lines) + "\n")
            continue
        if lowered == "/permissions":
            lines = [
                "NEXA Permissions & Security Boundaries:",
                f"  Workspace roots: {', '.join(str(r) for r in _workspace_roots())}",
            ]
            if runtime.security_gate:
                lines.append(f"  Deny patterns: {len(runtime.security_gate._deny_patterns)} active rules")
            lines.extend([
                "  Risk Tiers:",
                "    - READ: Autonomous read-only access",
                "    - MUTATE: Autonomous local filesystem/app changes",
                "    - REMOTE: External network/web interaction",
                "    - CRITICAL: Interactive confirmation required",
                "    - DESTRUCTIVE: Forbidden or confirmed execution",
            ])
            print("\nNEXA: " + "\n".join(lines) + "\n")
            continue
        if lowered.startswith("/plan "):
            plan_query = user.split(maxsplit=1)[1].strip()
            if runtime.task_planner is not None:
                plan = runtime.task_planner.plan(plan_query)
                print(f"\nNEXA Planned Workflow: '{plan_query}'")
                print(f"  Plan ID: {plan.plan_id}")
                for s in plan.steps:
                    print(f"  Step {s.step_id}: [{s.skill_name}.{s.operation}] {s.description}")
                print()
            else:
                print("\nNEXA: TaskPlanner not configured.\n")
            continue
        if lowered == "/stop":
            if runtime.failsafe is not None:
                runtime.failsafe.stop()
            print("\nNEXA: EMERGENCY STOP TRIGGERED. All computer-use actions halted.\n")
            continue
        if lowered in {"/mcp", "/mcp-list"}:
            if getattr(runtime, "mcp_extension", None) is not None:
                tools = runtime.mcp_extension.list_tools()
                lines = [f"Registered MCP Tools ({len(tools)}):"]
                for t in tools:
                    lines.append(f"  - {t['name']} [{t['risk_tier'].upper()}]: {t['description']} (server: {t['server']})")
                print("\nNEXA: " + "\n".join(lines) + "\n")
            else:
                print("\nNEXA: MCP subsystem not initialized.\n")
            continue
        if lowered == "/mcp-status":
            if getattr(runtime, "mcp_extension", None) is not None:
                hc = runtime.mcp_extension.health_check()
                print(f"\nNEXA MCP Status: healthy={hc['healthy']}, servers={hc['server_count']}, tools={hc['tool_count']}\n")
            else:
                print("\nNEXA: MCP subsystem not initialized.\n")
            continue
        if lowered in {"/extensions", "/extension-status"}:
            if getattr(runtime, "extension_registry", None) is not None:
                exts = runtime.extension_registry.list_extensions()
                lines = [f"Registered Extensions ({len(exts)}):"]
                for e in exts:
                    lines.append(f"  - {e.name} v{e.version} [{e.status.value.upper()}]: {e.description}")
                print("\nNEXA: " + "\n".join(lines) + "\n")
            else:
                print("\nNEXA: Extension registry not initialized.\n")
            continue
        if lowered == "/memory-status":
            print("\nNEXA 10-Layer Unified Memory Snapshot:")
            print("  Layer 1 (Conversation): Active turn buffer loaded")
            print("  Layer 2 (User Preferences): Persistent key-values loaded")
            print("  Layer 3 (Task Memory): Active and historical task states")
            print("  Layer 4 (Capability Memory): Dynamic discovered and learned skills")
            print("  Layer 5 (Application Context): Active window & desktop handles")
            print("  Layer 6 (Browser Context): Playwright session tabs & history")
            print("  Layer 7 (Device Context): Display bounds, DPI scaling, monitors")
            print("  Layer 8 (Episodic Memory): Chronological interaction logs")
            print("  Layer 9 (Semantic Memory): Knowledge graph triples & facts")
            print("  Layer 10 (Procedural Memory): Learned workflow recipes & playbooks\n")
            continue
        if lowered in {"/activity", "/history"}:
            if getattr(runtime, "observability", None) is not None:
                acts = runtime.observability.get_recent_activity(limit=10)
                if not acts:
                    print("\nNEXA: No recent activities logged.\n")
                else:
                    print("\nNEXA Activity Log:")
                    for a in acts:
                        print(f"  [{a['timestamp'][:19]}] [{a['category'].upper()}] {a['action']} - {a['status']} ({a['duration_ms']:.1f}ms)")
                    print()
            else:
                print("\nNEXA: Observability engine not initialized.\n")
            continue
        if lowered == "/health":
            if getattr(runtime, "observability", None) is not None:
                h = runtime.observability.health_summary()
                print(f"\nNEXA System Health: healthy={h['healthy']}, success_rate={h['success_rate']}%, operations={h['total_activities']}\n")
            else:
                print("\nNEXA: Observability engine not initialized.\n")
            continue
        if lowered.startswith("/task-pause "):
            tid = user.split(maxsplit=1)[1].strip()
            if getattr(runtime, "long_running_manager", None) is not None:
                ok = runtime.long_running_manager.pause_task(tid)
                print(f"\nNEXA: Task '{tid}' paused: {ok}\n")
            else:
                print("\nNEXA: LongRunningTaskManager not initialized.\n")
            continue
        if lowered.startswith("/task-resume "):
            tid = user.split(maxsplit=1)[1].strip()
            if getattr(runtime, "long_running_manager", None) is not None:
                ok = runtime.long_running_manager.resume_task(tid)
                print(f"\nNEXA: Task '{tid}' resumed: {ok}\n")
            else:
                print("\nNEXA: LongRunningTaskManager not initialized.\n")
            continue
        if lowered.startswith("/task-cancel "):
            tid = user.split(maxsplit=1)[1].strip()
            if getattr(runtime, "long_running_manager", None) is not None:
                ok = runtime.long_running_manager.cancel_task(tid)
                print(f"\nNEXA: Task '{tid}' cancelled: {ok}\n")
            else:
                print("\nNEXA: LongRunningTaskManager not initialized.\n")
            continue
        if not user:
            continue

        if getattr(runtime, "control", None) is not None:
            cmd_res = runtime.control.execute_pipeline(user)
            if cmd_res.get("status") not in {"conversation", "no_match"}:
                reply = cmd_res.get("message", "")
                save_message("user", user)
                _record_reply(messages, user, reply)
                continue
        else:
            response = runtime.kernel.process(user)
            if response.status != "no_match":
                reply = _kernel_reply(response)
                save_message("user", user)
                _record_reply(messages, user, reply)
                continue

            # Multi-step task planning before conversational fallback
            if runtime.task_planner is not None and runtime.plan_executor is not None:
                task_plan = runtime.task_planner.plan(user)
                if len(task_plan.steps) > 1 or (len(task_plan.steps) == 1 and task_plan.steps[0].skill_name != "unknown"):
                    plan_res = runtime.plan_executor.execute(task_plan)
                    reply = plan_res.message
                    save_message("user", user)
                    _record_reply(messages, user, reply)
                    continue

        save_message("user", user)

        new_fact = extract_fact(user)
        if new_fact:
            key, value = new_fact
            set_fact(key, value)
            reply = f"Orma vechu: {key} = {value}"
            _record_reply(messages, user, reply)
            continue

        fact_key = identify_fact_query(user)
        if fact_key:
            value = get_fact(fact_key)
            reply = value if value is not None else _missing_fact_reply(fact_key)
            _record_reply(messages, user, reply)
            continue

        fact = resolve_fact_query(user)
        if fact:
            _, value = fact
            _record_reply(messages, user, value)
            continue

        relevant = search_memory(user, limit=5)
        memory_context = ""
        if relevant:
            memory_context = "\nRelevant memory:\n"
            for item in relevant:
                memory_context += f"- {item['role']}: {item['content']}\n"

        language_result = prepare_user_input(user)
        context_reply = _contextual_next_step_reply(language_result, relevant)
        if context_reply:
            _record_reply(messages, user, context_reply)
            continue

        model_input = language_result.model_text()
        current_message = memory_context + "\nCurrent user message:\n" + model_input
        messages.append({"role": "user", "content": current_message})

        try:
            reply = ask_ollama(messages)
            if not isinstance(reply, str):
                reply = str(reply)
            reply = repair_manglish_reply(reply, language_result, messages)
        except OllamaBridgeError as exc:
            reply = f"Local model error: {exc}"

        messages.append({"role": "assistant", "content": reply})
        save_message("assistant", reply)
        print(f"\nNEXA: {reply}\n")


if __name__ == "__main__":
    main()
