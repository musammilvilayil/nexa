"""Trading-first NEXA skill package."""

from .backtest import BacktestEngine, BacktestReport, BacktestTrade, EquityPoint
from .brain import TradingBrain, TradingBrainResearchResult
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
from .validation import (
    EvaluationDecision,
    EvaluationThresholds,
    StrategyEvaluator,
    WalkForwardSplitter,
    WalkForwardWindow,
)

__all__ = [
    "AdaptiveMomentumStrategy",
    "AdaptiveStrategyRouter",
    "AutonomousPaperTrader",
    "BacktestEngine",
    "BacktestReport",
    "BacktestTrade",
    "BrokerAdapter",
    "BrokerHealth",
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
    "OrderStatus",
    "PaperBroker",
    "PaperCycleResult",
    "PaperEvidence",
    "PaperOrder",
    "PaperPortfolio",
    "PaperRuntimeState",
    "PaperStateStore",
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
    "WalkForwardSplitter",
    "WalkForwardWindow",
    "atr",
    "calculate_metrics",
    "ema",
    "highest",
    "lowest",
    "mandate_fingerprint",
    "sma",
    "true_range",
    "validate_market_series",
]
