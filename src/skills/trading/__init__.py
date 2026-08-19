"""Trading-first NEXA skill package."""

from .backtest import BacktestEngine, BacktestReport, BacktestTrade, EquityPoint
from .indicators import atr, ema, highest, lowest, sma, true_range
from .journal import TradingJournal
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
from .portfolio import FillEffect, PaperPortfolio, Position
from .regime import MarketRegime, RegimeConfig, RegimeDetector, RegimeReading
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
    "Candle",
    "DataQualityReport",
    "EquityPoint",
    "EvaluationDecision",
    "EvaluationThresholds",
    "FillEffect",
    "FixedRiskSizer",
    "MarketRegime",
    "MarketSeries",
    "MeanReversionConfig",
    "MeanReversionStrategy",
    "MomentumConfig",
    "OrderStatus",
    "PaperBroker",
    "PaperCycleResult",
    "PaperOrder",
    "PaperPortfolio",
    "PerformanceMetrics",
    "Position",
    "RegimeConfig",
    "RegimeDetector",
    "RegimeReading",
    "RiskDecision",
    "RiskEngine",
    "RiskSnapshot",
    "StrategyDecision",
    "StrategyEvaluator",
    "TradeSide",
    "TradeSignal",
    "TradingJournal",
    "TradingMandate",
    "TradingMode",
    "TradingSkill",
    "WalkForwardSplitter",
    "WalkForwardWindow",
    "atr",
    "calculate_metrics",
    "ema",
    "highest",
    "lowest",
    "sma",
    "true_range",
    "validate_market_series",
]
