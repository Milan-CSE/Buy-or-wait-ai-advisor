"""
backend/services/state_adapter.py

Bridges persistent storage models (FinancialProfile, FinancialAccount, Transaction)
into strictly typed, isolated domain inputs (FinancialProfileInput, CashflowEventInput).
Handles multi-account balance reconciliation, currency normalization, and internal transfer filtering.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from backend.database.mappers.transaction_mapper import TransactionMapper
from backend.database.models.account import FinancialAccount
from backend.database.models.profile import FinancialProfile
from backend.database.models.transaction import Transaction
from backend.ingestion.transfers import InternalTransferDetector
from buyorwait_engine.currency.fx import FXEngine
from buyorwait_engine.domain.models import CashflowEventInput, FinancialProfileInput


class FinancialStateAdapter:
    """
    Translates persistent DB entities into validated domain inputs for buyorwait_engine.
    """

    def __init__(self, fx_engine: Optional[FXEngine] = None):
        self.fx = fx_engine

    def reconcile_available_balance(
        self,
        profile: FinancialProfile,
        accounts: Sequence[FinancialAccount],
        as_of_date: date,
    ) -> Decimal:
        """
        Reconciles liquid cash across checking, savings, and cash accounts,
        converting each account balance to the profile's home currency.
        """
        active_accounts = [a for a in accounts if a.status == "active"]
        liquid_accounts = [
            a for a in active_accounts
            if a.account_type in ("checking", "savings", "cash")
        ]

        if not liquid_accounts:
            # Fall back to profile's recorded available balance
            return profile.current_available_balance

        total_home_balance = Decimal("0.0000")
        for acc in liquid_accounts:
            balance = acc.current_balance or Decimal("0.0000")
            if acc.currency == profile.home_currency or self.fx is None:
                total_home_balance += balance
            else:
                converted = self.fx.to_home(balance, acc.currency, profile.home_currency, as_of_date)
                total_home_balance += converted

        return total_home_balance

    def filter_and_map_transactions(
        self,
        transactions: Sequence[Transaction],
        accounts: Sequence[FinancialAccount],
    ) -> List[CashflowEventInput]:
        """
        Filters out unverified rows and internal transfers between user accounts,
        then maps remaining rows to domain CashflowEventInput DTOs.
        """
        # Collect known account names/masks for internal transfer detection
        user_account_keywords: List[str] = []
        for acc in accounts:
            if acc.institution_name:
                user_account_keywords.append(acc.institution_name)
            if acc.account_mask:
                user_account_keywords.append(acc.account_mask)
            user_account_keywords.append(acc.account_type)

        domain_events: List[CashflowEventInput] = []

        for tx in transactions:
            # 1. Ignore unverified or rejected transactions
            if tx.confidence_state != "verified":
                continue

            # 2. Exclude internal transfers to prevent double counting
            if tx.category in ("transfer", "internal_transfer"):
                continue
            if tx.cash_type == "non_cash":
                continue

            desc = tx.normalized_description or tx.original_description or ""
            if InternalTransferDetector.is_internal_transfer(desc, user_account_keywords):
                continue

            # 3. Map to domain DTO
            dto = TransactionMapper.to_domain_dto(tx)
            domain_events.append(dto)

        return domain_events

    def adapt(
        self,
        profile: FinancialProfile,
        accounts: Sequence[FinancialAccount],
        transactions: Sequence[Transaction],
        as_of_date: date,
    ) -> Tuple[FinancialProfileInput, List[CashflowEventInput]]:
        """
        Full adaptation step returning (FinancialProfileInput, List[CashflowEventInput]).
        """
        reconciled_balance = self.reconcile_available_balance(profile, accounts, as_of_date)

        profile_input = FinancialProfileInput(
            user_id=str(profile.user_id),
            home_currency=profile.home_currency,
            current_available_balance=reconciled_balance,
            minimum_balance_to_keep=profile.minimum_balance_to_keep,
            protected_categories=tuple(profile.protected_categories or []),
            reducible_categories=tuple(profile.reducible_categories or []),
            stoppable_categories=tuple(profile.stoppable_categories or []),
            payment_methods=tuple(profile.payment_methods or ["full_payment", "installments", "partial_payment"]),
            max_installment_months=profile.max_installment_months,
        )

        domain_events = self.filter_and_map_transactions(transactions, accounts)

        return profile_input, domain_events
