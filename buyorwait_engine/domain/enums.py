"""
buyorwait_engine/domain/enums.py

Enumerations defining the financial lifecycle, affordability statuses,
decision methods, and risk classifications.
"""
from enum import Enum


class Verdict(str, Enum):
    BUY = "BUY"
    SAFER_PAYMENT = "SAFER_PAYMENT"
    WAIT = "WAIT"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"


class AffordabilityStatus(str, Enum):
    AFFORDABLE_NOW = "affordable_now"
    AFFORDABLE_WITH_PLAN = "affordable_with_plan"
    AFFORDABLE_LATER = "affordable_later"
    NOT_AFFORDABLE = "not_affordable"


class PaymentMethod(str, Enum):
    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"
    WAIT = "wait"
    NOT_RECOMMENDED = "not_recommended"


class RiskTier(str, Enum):
    LOW_RISK = "LOW_RISK"
    MODERATE_RISK = "MODERATE_RISK"
    HIGH_RISK = "HIGH_RISK"


class CashType(str, Enum):
    IMMEDIATE_DEBIT = "immediate_debit"
    FUTURE_DEBIT = "future_debit"
    SETTLED_INCOME = "settled_income"
    CONFIRMED_INCOME = "confirmed_income"
    NON_CASH = "non_cash"
    VOID = "void"


class Flexibility(str, Enum):
    FIXED = "fixed"
    REDUCIBLE = "reducible"
    STOPPABLE = "stoppable"
    REDUCIBLE_OR_STOPPABLE = "reducible_or_stoppable"


class Cadence(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    BI_WEEKLY = "bi_weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    IRREGULAR = "irregular"
