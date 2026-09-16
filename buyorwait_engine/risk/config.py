"""
buyorwait_engine/risk/config.py

Calibration configuration and parameters for empirical P90 uncertainty modeling.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict


CURRENT_CALIBRATION_VERSION = "v3_empirical_q90_20260914"

# Empirical P90 stress multipliers calibrated from out-of-time residual analysis
DEFAULT_P90_STRESS_FACTORS: Dict[str, Decimal] = {
    'groceries': Decimal('1.240'),
    'transport': Decimal('1.242'),
    'dining': Decimal('1.239'),
    'utilities': Decimal('1.125'),
    'shopping': Decimal('1.126'),
    'entertainment': Decimal('1.122'),
    'healthcare': Decimal('1.107'),
    'personal_care': Decimal('1.150'),
    'clothing': Decimal('1.150'),
    'miscellaneous': Decimal('1.200'),
    # Fixed categories have zero variance
    'rent': Decimal('1.000'),
    'debt_repayment': Decimal('1.000'),
    'insurance': Decimal('1.000'),
    'housing': Decimal('1.000'),
    'streaming': Decimal('1.000'),
    'music_subscription': Decimal('1.000'),
    'cloud_storage': Decimal('1.000'),
    'delivery_membership': Decimal('1.000'),
    'education': Decimal('1.000'),
    'family_support': Decimal('1.000'),
    'gym': Decimal('1.000'),
}


@dataclass(frozen=True)
class RiskCalibrationConfig:
    version: str = CURRENT_CALIBRATION_VERSION
    stress_factors: Dict[str, Decimal] = field(default_factory=lambda: dict(DEFAULT_P90_STRESS_FACTORS))
    description: str = (
        "Empirical P90 residual uncertainty buffers applied to variable expenditure categories. "
        "Calibrated out-of-time across 250 evaluation users. Note: These represent empirical stress "
        "heuristics and not theoretical mathematical insolvency guarantees."
    )
