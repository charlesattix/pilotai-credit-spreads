"""
Execution package — live order submission and position management.

Components:
  ExecutionEngine   — submits approved opportunities to Alpaca as live orders
  PositionMonitor   — background daemon managing profit targets, stop losses, DTE exits
"""

from execution.execution_engine import ExecutionEngine
from execution.position_monitor import PositionMonitor

__all__ = ["ExecutionEngine", "PositionMonitor"]
