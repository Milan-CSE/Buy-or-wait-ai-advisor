"""
backend/services/data_quality.py

Assesses whether a user's financial profile, accounts, and transaction history
provide sufficient verified evidence for an accurate financial decision without guessing.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Sequence

from backend.database.models.account import FinancialAccount
from backend.database.models.profile import FinancialProfile
from backend.database.models.transaction import Transaction
from buyorwait_engine.currency.fx import FXEngine, FXRateMissingError


@dataclass(frozen=True)
class DataQualityResult:
    """Outcome of a data quality assessment."""
    is_sufficient: bool
    code: str = "OK"  # "OK" | "DATA_INSUFFICIENT"
    reason: str = ""
    affected_data: str = ""
    user_action_required: str = ""

    def to_dict(self) -> dict:
        return {
            "is_sufficient": self.is_sufficient,
            "code": self.code,
            "reason": self.reason,
            "affected_data": self.affected_data,
            "user_action_required": self.user_action_required,
        }


class DataQualityEvaluator:
    """
    Evaluates real-world completeness and freshness of a user's financial state.
    Never converts uncertainty into false precision.
    """

    def __init__(
        self,
        min_historical_transactions: int = 3,
        max_staleness_days: int = 90,
        fx_engine: Optional[FXEngine] = None,
    ):
        self.min_historical_transactions = min_historical_transactions
        self.max_staleness_days = max_staleness_days
        self.fx = fx_engine

    def evaluate(
        self,
        profile: Optional[FinancialProfile],
        accounts: Sequence[FinancialAccount],
        transactions: Sequence[Transaction],
        as_of_date: date,
        purchase_currency: Optional[str] = None,
    ) -> DataQualityResult:
        """
        Runs comprehensive data quality checks on profile, accounts, and transactions.
        """
        # 1. Profile existence
        if profile is None:
            return DataQualityResult(
                is_sufficient=False,
                code="DATA_INSUFFICIENT",
                reason="User financial profile does not exist.",
                affected_data="profile",
                user_action_required="Create a financial profile setting home currency and minimum reserve.",
            )

        if profile.minimum_balance_to_keep < Decimal("0.0000"):
            return DataQualityResult(
                is_sufficient=False,
                code="DATA_INSUFFICIENT",
                reason="Profile minimum balance to keep cannot be negative.",
                affected_data="profile.minimum_balance_to_keep",
                user_action_required="Update financial profile with a valid non-negative minimum balance.",
            )

        # 2. Active liquid accounts & balances
        active_accounts = [a for a in accounts if a.status == "active"]
        liquid_accounts = [
            a for a in active_accounts
            if a.account_type in ("checking", "savings", "cash")
        ]

        if not liquid_accounts and (profile.current_available_balance is None or profile.current_available_balance <= Decimal("0.0000")):
            return DataQualityResult(
                is_sufficient=False,
                code="DATA_INSUFFICIENT",
                reason="No active liquid bank or cash accounts found.",
                affected_data="accounts",
                user_action_required="Link at least one active checking, savings, or cash account.",
            )

        for acc in liquid_accounts:
            if acc.current_balance is None:
                return DataQualityResult(
                    is_sufficient=False,
                    code="DATA_INSUFFICIENT",
                    reason=f"Account '{acc.institution_name} ({acc.account_mask})' has a missing balance.",
                    affected_data=f"accounts.{acc.id}.current_balance",
                    user_action_required="Update the account balance to reflect the current position.",
                )

        # 3. Currency support and convertibility
        home_currency = profile.home_currency
        if self.fx is not None:
            # Check account currencies
            for acc in liquid_accounts:
                if acc.currency != home_currency:
                    try:
                        self.fx.to_home(Decimal("1.00"), acc.currency, home_currency, as_of_date)
                    except FXRateMissingError:
                        return DataQualityResult(
                            is_sufficient=False,
                            code="DATA_INSUFFICIENT",
                            reason=(
                                f"Account '{acc.institution_name}' uses currency '{acc.currency}', "
                                f"which cannot be converted to home currency '{home_currency}' on {as_of_date}."
                            ),
                            affected_data="accounts.currency",
                            user_action_required=f"Provide exchange rate for {acc.currency}->{home_currency} or convert account.",
                        )

            # Check purchase currency if provided
            if purchase_currency and purchase_currency != home_currency:
                try:
                    self.fx.to_home(Decimal("1.00"), purchase_currency, home_currency, as_of_date)
                except FXRateMissingError:
                    return DataQualityResult(
                        is_sufficient=False,
                        code="DATA_INSUFFICIENT",
                        reason=(
                            f"Purchase proposal currency '{purchase_currency}' cannot be converted "
                            f"to home currency '{home_currency}' on {as_of_date}."
                        ),
                        affected_data="purchase_proposal.currency",
                        user_action_required=f"Provide exchange rate for {purchase_currency}->{home_currency} on {as_of_date}.",
                    )

        # 4. Verified transaction history completeness
        verified_historical_txs = [
            tx for tx in transactions
            if tx.confidence_state == "verified"
            and tx.transaction_date <= as_of_date
            and tx.lifecycle_status in ("settled", "pending", "scheduled")
        ]

        if len(verified_historical_txs) < self.min_historical_transactions:
            return DataQualityResult(
                is_sufficient=False,
                code="DATA_INSUFFICIENT",
                reason=(
                    f"Insufficient verified transaction history ({len(verified_historical_txs)} verified "
                    f"transactions found, minimum required: {self.min_historical_transactions}). "
                    "Cannot reliably forecast recurring expenses or living burn without guessing."
                ),
                affected_data="transactions",
                user_action_required="Import at least 30 to 90 days of verified bank statement history.",
            )

        # 5. Balance staleness check
        most_recent_tx_date = max(tx.transaction_date for tx in verified_historical_txs)
        staleness_threshold = as_of_date - timedelta(days=self.max_staleness_days)

        if most_recent_tx_date < staleness_threshold:
            days_old = (as_of_date - most_recent_tx_date).days
            return DataQualityResult(
                is_sufficient=False,
                code="DATA_INSUFFICIENT",
                reason=(
                    f"Financial data is stale. The latest verified transaction is from "
                    f"{most_recent_tx_date.isoformat()}, which is {days_old} days before evaluation "
                    f"date {as_of_date.isoformat()} (maximum allowable staleness: {self.max_staleness_days} days)."
                ),
                affected_data="transactions.staleness",
                user_action_required="Upload an updated financial statement reflecting recent account activity.",
            )

        return DataQualityResult(
            is_sufficient=True,
            code="OK",
            reason="User financial state is complete and verified.",
            affected_data="",
            user_action_required="",
        )
