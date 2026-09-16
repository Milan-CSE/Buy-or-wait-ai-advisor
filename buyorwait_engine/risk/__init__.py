"""
buyorwait_engine/risk

Empirical P90 stress testing, residual calibration, and risk classification.
"""
from buyorwait_engine.risk.config import (
    CURRENT_CALIBRATION_VERSION,
    DEFAULT_P90_STRESS_FACTORS,
    RiskCalibrationConfig,
)
from buyorwait_engine.risk.stress_buffers import build_stressed_state
from buyorwait_engine.risk.classifier import RiskProfile, classify_risk
from buyorwait_engine.risk.policy import apply_risk_policy

__all__ = [
    'CURRENT_CALIBRATION_VERSION',
    'DEFAULT_P90_STRESS_FACTORS',
    'RiskCalibrationConfig',
    'build_stressed_state',
    'RiskProfile',
    'classify_risk',
    'apply_risk_policy',
]
