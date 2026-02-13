"""
Machine Learning Pipeline for Credit Spread Trading

This module provides sophisticated ML-based trade selection, regime detection,
and position sizing for credit spread strategies.
"""

from .regime_detector import RegimeDetector
from .iv_analyzer import IVAnalyzer
from .feature_engine import FeatureEngine
from .signal_model import SignalModel
from .position_sizer import PositionSizer
from .sentiment_scanner import SentimentScanner
from .ml_pipeline import MLPipeline

__all__ = [
    'RegimeDetector',
    'IVAnalyzer',
    'FeatureEngine',
    'SignalModel',
    'PositionSizer',
    'SentimentScanner',
    'MLPipeline',
]
