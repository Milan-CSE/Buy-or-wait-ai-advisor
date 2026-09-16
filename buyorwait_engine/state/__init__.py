"""
buyorwait_engine/state

State construction and lifecycle event resolution.
"""
from buyorwait_engine.state.builder import (
    build_financial_state_from_inputs,
    resolve_events,
)

__all__ = [
    'build_financial_state_from_inputs',
    'resolve_events',
]
