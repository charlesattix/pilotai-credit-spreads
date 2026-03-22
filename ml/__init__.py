"""
Machine Learning Pipeline for Credit Spread Trading

Canonical implementations live in compass/ — this package re-exports
for backward compatibility with existing scripts.
"""

from compass.features import FeatureEngine
from compass.iv_surface import IVAnalyzer
from compass.sizing import PositionSizer
from compass.signal_model import SignalModel

__all__ = [
    'IVAnalyzer',
    'FeatureEngine',
    'SignalModel',
    'PositionSizer',
]
