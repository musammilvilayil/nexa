from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core import ContextBus, NexaKernel, SQLiteAuditLedger, SkillRegistry
from core.security import SecurityGate
from core.failsafe import FailsafeMonitor, FailsafeConfig
from capabilities import CapabilityManager, CapabilityStore
from providers.registry import ProviderRegistry
from skills.file_skill import FileSkill
from skills.git_plugin import GitPlugin
from skills.github_skill import GitHubSkill
from skills.computer_skill import ComputerSkill
from skills.browser_skill import BrowserSkill
from skills.terminal_skill import TerminalSkill
from skills.app_skill import AppSkill
from skills.trading import (
    AdaptiveStrategyRouter,
    BrokerAdapter,
    BrokerFactoryRegistry,
    BrokerSelection,
    LiveArmController,
    LiveExecutionController,
    PaperBroker,
    PaperEvidenceStore,
    PaperStateStore,
    StrategyPromotionStore,
    TradingBrain,
    TradingControlSkill,
    TradingKillSwitch,
    TradingMandate,
    TradingMode,
    TradingSkill,
    build_selected_trusted_broker,
)
from skills.workspace_skill import WorkspaceSkill
from workspace import WorkspaceManager


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class NexaRuntime:
    kernel: NexaKernel
    registry: SkillRegistry
    context_bus: ContextBus
    workspace_manager: WorkspaceManager
    trading_skill: TradingSkill
    trading_control_skill: TradingControlSkill
    github_skill: GitHubSkill
    trading_brain: TradingBrain
    promotion_store: StrategyPromotionStore
    paper_state_store: PaperStateStore
    paper_evidence_store: PaperEvidenceStore
    live_arm: LiveArmController
    kill_switch: TradingKillSwitch
    live_controller: LiveExecutionController | None
    capability_manager: CapabilityManager | None = None
    capability_store: CapabilityStore | None = None
    security_gate: SecurityGate | None = None
    failsafe: FailsafeMonitor | None = None
    provider_registry: ProviderRegistry | None = None
    computer_skill: ComputerSkill | None = None
    browser_skill: BrowserSkill | None = None
    terminal_skill: TerminalSkill | None = None
    app_skill: AppSkill | None = None
    task_planner: Any | None = None
    plan_executor: Any | None = None


def _workspace_roots() -> tuple[Path, ...]:
    raw = os.getenv("NEXA_WORKSPACE_ROOTS", "").strip()
    if not raw:
        return (PROJECT_ROOT,)
    parts = [item.strip() for item in raw.split(os.pathsep) if item.strip()]
    if not parts:
        return (PROJECT_ROOT,)
    return tuple(Path(item).expanduser().resolve() for item in parts)


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be boolean")


def build_trading_mandate() -> TradingMandate:
    """Build the owner trading envelope from explicit environment config.

    Defaults are deliberately research-only. A live mode in configuration does
    not itself arm execution; LiveArmController remains a separate owner action.
    """

    mode_raw = os.getenv("NEXA_TRADING_MODE", TradingMode.RESEARCH.value).strip().lower()
    mode = TradingMode(mode_raw)
    raw_symbols = os.getenv("NEXA_TRADING_SYMBOLS", "NIFTY50")
    symbols = tuple(item.strip().upper() for item in raw_symbols.split(",") if item.strip())
    raw_strategies = os.getenv("NEXA_TRADING_STRATEGIES", "adaptive_router_v1")
    strategies = tuple(item.strip() for item in raw_strategies.split(",") if item.strip())

    confidence = float(os.getenv("NEXA_MIN_SIGNAL_CONFIDENCE", "0.60"))
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("NEXA_MIN_SIGNAL_CONFIDENCE must be between 0 and 1")

    return TradingMandate(
        mode=mode,
        allowed_symbols=symbols,
        allowed_strategies=strategies,
        max_notional_per_trade=_float_env("NEXA_MAX_NOTIONAL_PER_TRADE", 10_000.0),
        max_total_exposure=_float_env("NEXA_MAX_TOTAL_EXPOSURE", 25_000.0),
        max_risk_per_trade=_float_env("NEXA_MAX_RISK_PER_TRADE", 250.0),
        max_daily_loss=_float_env("NEXA_MAX_DAILY_LOSS", 500.0),
        max_open_positions=_int_env("NEXA_MAX_OPEN_POSITIONS", 3),
        min_signal_confidence=confidence,
        allow_short=_bool_env("NEXA_ALLOW_SHORT", False),
        require_stop_loss=_bool_env("NEXA_REQUIRE_STOP_LOSS", True),
    )


def build_runtime(*, live_broker: BrokerAdapter | None = None) -> NexaRuntime:
    """Construct the production local runtime.

    No live broker is created from environment strings or model output. A broker
    adapter must be explicitly supplied by trusted owner-controlled application
    code. Even then, ordinary live entries remain blocked until the mandate is
    LIVE_AUTONOMOUS, the strategy is LIVE_ELIGIBLE, and LiveArmController is
    owner-confirmed for the exact mandate fingerprint.

    ContextBus stores only stable configuration facts here. Dynamic safety state
    such as current promotion stage, kill-switch state, and live arm state is
    queried from the owning trading components so a cached context flag cannot
    become a false source of truth.
    """

    context_bus = ContextBus()
    workspace_manager = WorkspaceManager(_workspace_roots())
    repos = workspace_manager.discover()

    for repo in repos:
        if repo.path == PROJECT_ROOT:
            workspace_manager.switch(str(repo.path))
            context_bus.set_active_workspace(repo.path)
            break

    registry = SkillRegistry()
    registry.register(WorkspaceSkill(workspace_manager, context_bus))
    registry.register(FileSkill())
    registry.register(GitPlugin())

    github_skill = GitHubSkill(workspace_manager, context_bus)
    registry.register(github_skill)

    mandate = build_trading_mandate()
    paper_path = Path(
        os.getenv(
            "NEXA_PAPER_DB",
            str(PROJECT_ROOT / "data" / "paper_trading.db"),
        )
    ).expanduser().resolve()
    paper_state_store = PaperStateStore(paper_path)
    paper_evidence_store = PaperEvidenceStore(
        paper_path,
        initial_equity=_float_env("NEXA_PAPER_INITIAL_EQUITY", 100_000.0),
    )
    paper_broker = PaperBroker(state_store=paper_state_store)
    trading_skill = TradingSkill(mandate, paper_broker)
    registry.register(trading_skill)

    promotion_path = Path(
        os.getenv(
            "NEXA_STRATEGY_DB",
            str(PROJECT_ROOT / "data" / "strategy_promotion.db"),
        )
    ).expanduser().resolve()
    promotion_store = StrategyPromotionStore(promotion_path)
    trading_brain = TradingBrain(
        mandate=mandate,
        strategy=AdaptiveStrategyRouter(),
        promotion_store=promotion_store,
        paper_broker=paper_broker,
        paper_evidence_store=paper_evidence_store,
    )

    live_arm = LiveArmController()
    kill_switch = TradingKillSwitch()
    live_controller = None
    if live_broker is not None:
        live_controller = LiveExecutionController(
            mandate=mandate,
            broker=live_broker,
            promotion_store=promotion_store,
            arm=live_arm,
            kill_switch=kill_switch,
            max_signal_age_seconds=_float_env("NEXA_MAX_SIGNAL_AGE_SECONDS", 60.0),
        )

    trading_control_skill = TradingControlSkill(
        mandate=mandate,
        promotion_store=promotion_store,
        live_arm=live_arm,
        kill_switch=kill_switch,
        live_controller=live_controller,
    )
    registry.register(trading_control_skill)

    capability_db_path = Path(
        os.getenv("NEXA_CAPABILITY_DB", str(PROJECT_ROOT / "data" / "capabilities.db"))
    ).expanduser().resolve()
    capability_store = CapabilityStore(capability_db_path)
    capability_storage_dir = Path(
        os.getenv("NEXA_CAPABILITIES_DIR", str(PROJECT_ROOT / "data" / "capabilities"))
    ).expanduser().resolve()
    capability_manager = CapabilityManager(
        store=capability_store,
        storage_dir=capability_storage_dir,
    )
    # Load all previously persisted capabilities into the registry
    capability_manager.load_all_into_registry(registry)

    # ── Security Gate (expanded with deny list and CRITICAL tier) ────
    blocked_processes_raw = os.getenv("NEXA_BLOCKED_PROCESSES", "").strip()
    blocked_processes = frozenset(
        p.strip() for p in blocked_processes_raw.split(",") if p.strip()
    ) if blocked_processes_raw else frozenset()

    security_gate = SecurityGate(
        critical_cooldown_seconds=_float_env("NEXA_CRITICAL_COOLDOWN_SECONDS", 5.0),
    )

    # ── Failsafe Monitor ─────────────────────────────────────────────
    failsafe_config = FailsafeConfig(
        corner_enabled=_bool_env("NEXA_FAILSAFE_CORNER", True),
        corner_threshold_px=_int_env("NEXA_FAILSAFE_CORNER_PX", 5),
        max_actions_per_second=_float_env("NEXA_FAILSAFE_MAX_ACTIONS", 10.0),
        action_timeout_seconds=_float_env("NEXA_FAILSAFE_TIMEOUT", 30.0),
        blocked_processes=blocked_processes,
        cooldown_after_trigger_seconds=_float_env("NEXA_FAILSAFE_COOLDOWN", 5.0),
    )
    failsafe = FailsafeMonitor(failsafe_config)

    # ── Provider Registry ─────────────────────────────────────────────
    provider_registry = ProviderRegistry()

    # ── Computer-Use Skills ───────────────────────────────────────────
    from computer.screen import ScreenCapture
    from computer.mouse import MouseController
    from computer.keyboard import KeyboardController
    from computer.clipboard import ClipboardManager
    from computer.window import WindowManager
    from computer.vision import ScreenAnalyzer

    screen = ScreenCapture(failsafe=failsafe)
    mouse = MouseController(failsafe=failsafe)
    keyboard = KeyboardController(failsafe=failsafe)
    clipboard = ClipboardManager()
    window_manager = WindowManager()
    screen_analyzer = ScreenAnalyzer()

    computer_skill = ComputerSkill(
        failsafe=failsafe,
        screen=screen,
        mouse=mouse,
        keyboard=keyboard,
        clipboard=clipboard,
        window_manager=window_manager,
        screen_analyzer=screen_analyzer,
    )
    registry.register(computer_skill)

    browser_skill = BrowserSkill()
    registry.register(browser_skill)

    terminal_skill = TerminalSkill(
        timeout=_float_env("NEXA_TERMINAL_TIMEOUT", 60.0),
    )
    registry.register(terminal_skill)

    app_skill = AppSkill()
    registry.register(app_skill)

    # ── Kernel ────────────────────────────────────────────────────────
    audit_path = Path(
        os.getenv("NEXA_AUDIT_DB", str(PROJECT_ROOT / "data" / "actions.db"))
    ).expanduser().resolve()
    audit = SQLiteAuditLedger(audit_path)
    kernel = NexaKernel(
        registry=registry,
        context_bus=context_bus,
        security_gate=security_gate,
        audit_ledger=audit,
        capability_manager=capability_manager,
        pending_ttl_seconds=_float_env("NEXA_PENDING_TTL_SECONDS", 300.0),
    )

    context_bus.set_environment_flag("gemini_available", bool(os.getenv("GEMINI_API_KEY", "").strip()))
    context_bus.set_environment_flag("ollama_url", os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    context_bus.set_environment_flag("trading_mode", mandate.mode.value)
    context_bus.set_environment_flag("trading_strategy", trading_brain.strategy.strategy_id)
    context_bus.set_environment_flag("live_broker_configured", live_broker is not None)
    context_bus.set_environment_flag("paper_state_persistent", True)
    context_bus.set_environment_flag("paper_evidence_persistent", True)
    context_bus.set_environment_flag("capabilities_persistent", True)
    context_bus.set_environment_flag("failsafe_enabled", True)
    context_bus.set_environment_flag("computer_use_available", True)
    context_bus.set_environment_flag("browser_available", True)
    context_bus.set_environment_flag("terminal_available", True)

    from planner.task_planner import TaskPlanner
    from planner.executor import PlanExecutor

    task_planner = TaskPlanner(registry=registry, capability_manager=capability_manager)
    plan_executor = PlanExecutor(kernel_process=kernel.process)

    return NexaRuntime(
        kernel=kernel,
        registry=registry,
        context_bus=context_bus,
        workspace_manager=workspace_manager,
        trading_skill=trading_skill,
        trading_control_skill=trading_control_skill,
        github_skill=github_skill,
        trading_brain=trading_brain,
        promotion_store=promotion_store,
        paper_state_store=paper_state_store,
        paper_evidence_store=paper_evidence_store,
        live_arm=live_arm,
        kill_switch=kill_switch,
        live_controller=live_controller,
        capability_manager=capability_manager,
        capability_store=capability_store,
        security_gate=security_gate,
        failsafe=failsafe,
        provider_registry=provider_registry,
        computer_skill=computer_skill,
        browser_skill=browser_skill,
        terminal_skill=terminal_skill,
        app_skill=app_skill,
        task_planner=task_planner,
        plan_executor=plan_executor,
    )


def build_runtime_from_trusted_brokers(
    registry: BrokerFactoryRegistry,
    *,
    selection: BrokerSelection | None = None,
) -> NexaRuntime:
    """Explicit trusted application path for enabling a reviewed broker adapter.

    Unlike ``build_runtime()``, this function may consult the non-secret broker
    selector environment when ``selection`` is omitted. It still cannot import or
    instantiate an arbitrary adapter: the provider must already exist in the
    caller-supplied ``BrokerFactoryRegistry``. Live execution remains disarmed.
    """

    broker = build_selected_trusted_broker(registry, selection=selection)
    return build_runtime(live_broker=broker)
