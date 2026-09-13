"""Trading-first NEXA skill package."""

from .backtest import BacktestEngine, BacktestReport, BacktestTrade, EquityPoint
from .brain import TradingBrain, TradingBrainResearchResult
from .broker_config import (
    BrokerFactoryRegistry,
    BrokerSelection,
    TrustedBrokerFactory,
    broker_selection_from_env,
    build_selected_trusted_broker,
)
from .control_skill import TradingControlSkill
from .data_provider import CSVMarketDataProvider, MarketDataProvider
from .indicators import atr, ema, highest, lowest, sma, true_range
from .journal import TradingJournal
from .live import (
    BrokerAdapter,
    BrokerHealth,
    LiveArmController,
    LiveExecutionController,
    LiveOrderRequest,
    LiveOrderResult,
    TradingKillSwitch,
    mandate_fingerprint,
)
from .market import Candle, DataQualityReport, MarketSeries, validate_market_series
from .metrics import PerformanceMetrics, calculate_metrics
from .models import (
    OrderStatus,
    PaperOrder,
    RiskDecision,
    RiskSnapshot,
    TradeSide,
    TradeSignal,
    TradingMandate,
    TradingMode,
)
from .paper import PaperBroker
from .paper_evidence import PaperEvidenceReport, PaperEvidenceStore
from .paper_service import PaperRuntimeService, PaperServiceCycle, PaperSymbolCycle
from .paper_state import PaperRuntimeState, PaperStateStore
from .portfolio import FillEffect, PaperPortfolio, Position
from .promotion import (
    PaperEvidence,
    PromotionDecision,
    PromotionPolicy,
    StrategyPromotionGate,
    StrategyPromotionStore,
    StrategyStage,
)
from .regime import MarketRegime, RegimeConfig, RegimeDetector, RegimeReading
from .research import ResearchWindowResult, StrategyResearchReport, TradingResearchPipeline
from .risk import RiskEngine
from .runtime import AutonomousPaperTrader, PaperCycleResult
from .sizing import FixedRiskSizer
from .skill import TradingSkill
from .strategy import (
    AdaptiveMomentumStrategy,
    AdaptiveStrategyRouter,
    MeanReversionConfig,
    MeanReversionStrategy,
    MomentumConfig,
    StrategyDecision,
)
from .strategy_v2 import AdaptiveMomentumStrategyV2, MomentumV2Config
from .strategy_v3 import AdaptiveMomentumStrategyV3, MomentumV3Config
from .trend_pullback import TrendPullbackConfig, TrendPullbackStrategy
from .validation import (
    EvaluationDecision,
    EvaluationThresholds,
    StrategyEvaluator,
    WalkForwardSplitter,
    WalkForwardWindow,
)

__all__ = [
    "AdaptiveMomentumStrategy",
    "AdaptiveMomentumStrategyV2",
    "AdaptiveMomentumStrategyV3",
    "AdaptiveStrategyRouter",
    "AutonomousPaperTrader",
    "BacktestEngine",
    "BacktestReport",
    "BacktestTrade",
    "BrokerAdapter",
    "BrokerFactoryRegistry",
    "BrokerHealth",
    "BrokerSelection",
    "CSVMarketDataProvider",
    "Candle",
    "DataQualityReport",
    "EquityPoint",
    "EvaluationDecision",
    "EvaluationThresholds",
    "FillEffect",
    "FixedRiskSizer",
    "LiveArmController",
    "LiveExecutionController",
    "LiveOrderRequest",
    "LiveOrderResult",
    "MarketDataProvider",
    "MarketRegime",
    "MarketSeries",
    "MeanReversionConfig",
    "MeanReversionStrategy",
    "MomentumConfig",
    "MomentumV2Config",
    "MomentumV3Config",
    "OrderStatus",
    "PaperBroker",
    "PaperCycleResult",
    "PaperEvidence",
    "PaperEvidenceReport",
    "PaperEvidenceStore",
    "PaperOrder",
    "PaperPortfolio",
    "PaperRuntimeService",
    "PaperRuntimeState",
    "PaperServiceCycle",
    "PaperStateStore",
    "PaperSymbolCycle",
    "PerformanceMetrics",
    "Position",
    "PromotionDecision",
    "PromotionPolicy",
    "RegimeConfig",
    "RegimeDetector",
    "RegimeReading",
    "ResearchWindowResult",
    "RiskDecision",
    "RiskEngine",
    "RiskSnapshot",
    "StrategyDecision",
    "StrategyEvaluator",
    "StrategyPromotionGate",
    "StrategyPromotionStore",
    "StrategyResearchReport",
    "StrategyStage",
    "TradeSide",
    "TradeSignal",
    "TradingBrain",
    "TradingBrainResearchResult",
    "TradingControlSkill",
    "TradingJournal",
    "TradingKillSwitch",
    "TradingMandate",
    "TradingMode",
    "TradingResearchPipeline",
    "TradingSkill",
    "TrendPullbackConfig",
    "TrendPullbackStrategy",
    "TrustedBrokerFactory",
    "WalkForwardSplitter",
    "WalkForwardWindow",
    "atr",
    "broker_selection_from_env",
    "build_selected_trusted_broker",
    "calculate_metrics",
    "ema",
    "highest",
    "lowest",
    "mandate_fingerprint",
    "sma",
    "true_range",
    "validate_market_series",
]
