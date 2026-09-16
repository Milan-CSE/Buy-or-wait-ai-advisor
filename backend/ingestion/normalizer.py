"""
backend/ingestion/normalizer.py

Normalizes extracted statement fields into strict typed representations:
Decimal amounts, dates, directions, and cleaned descriptions.
"""
from __future__ import annotations
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
import re
from typing import Optional, Tuple

from backend.ingestion.models import (
    DialectInfo,
    ParsedRow,
    TransactionDirection,
    VerificationStatus,
)


CURRENCY_SYMBOLS = {"$", "€", "£", "₹", "¥"}


class TransactionNormalizer:
    """
    Transforms raw row fields into normalized dates, signed Decimal amounts,
    and standardized descriptions with confidence and ambiguity tracking.
    """

    @staticmethod
    def parse_clean_decimal(raw_val: str) -> Optional[Decimal]:
        """
        Parses monetary string into exact Decimal without using float.
        Handles commas, currency symbols, and parentheses accounting format (e.g. '(100.50)').
        """
        if not raw_val or not raw_val.strip():
            return None

        val = raw_val.strip()

        # Remove currency symbols
        for sym in CURRENCY_SYMBOLS:
            val = val.replace(sym, "")

        # Remove spaces
        val = val.replace(" ", "")

        # Check for parentheses accounting format e.g. "(1,234.56)" -> "-1234.56"
        is_negative = False
        if val.startswith("(") and val.endswith(")"):
            is_negative = True
            val = val[1:-1]
        elif val.startswith("-"):
            is_negative = True
            val = val[1:]
        elif val.startswith("+"):
            val = val[1:]

        # Remove commas
        val = val.replace(",", "")

        if not val:
            return None

        try:
            d = Decimal(val)
            if is_negative:
                d = -d
            # Quantize to 4 decimal places for consistency with Numeric(18, 4)
            return d.quantize(Decimal("0.0001"))
        except InvalidOperation:
            return None

    @classmethod
    def resolve_amount_and_direction(
        cls,
        row: ParsedRow,
        dialect: DialectInfo,
    ) -> Tuple[Optional[Decimal], str, VerificationStatus, Optional[str]]:
        """
        Calculates signed Decimal amount and direction ('debit', 'credit', 'non_cash').
        Returns: (amount, direction, status, ambiguity_or_rejection_reason)
        """
        has_debit_col = bool(dialect.debit_column and row.debit_str)
        has_credit_col = bool(dialect.credit_column and row.credit_str)

        # 1. Dual column format (Debit & Credit)
        if dialect.debit_column or dialect.credit_column:
            debit_amt = cls.parse_clean_decimal(row.debit_str) if row.debit_str else None
            credit_amt = cls.parse_clean_decimal(row.credit_str) if row.credit_str else None

            # Ignore zero values in credit/debit
            if debit_amt is not None and debit_amt == Decimal("0"):
                debit_amt = None
            if credit_amt is not None and credit_amt == Decimal("0"):
                credit_amt = None

            if debit_amt is not None and credit_amt is not None:
                return None, "debit", VerificationStatus.AMBIGUOUS, "Row has both Debit and Credit amounts populated"

            if debit_amt is not None:
                signed = -abs(debit_amt)
                return signed, TransactionDirection.DEBIT.value, VerificationStatus.VERIFIED, None

            if credit_amt is not None:
                signed = abs(credit_amt)
                return signed, TransactionDirection.CREDIT.value, VerificationStatus.VERIFIED, None

            return None, "debit", VerificationStatus.REJECTED, "Both Debit and Credit fields are empty"

        # 2. Single amount column format
        if dialect.amount_column and row.amount_str:
            amt = cls.parse_clean_decimal(row.amount_str)
            if amt is None:
                return None, "debit", VerificationStatus.REJECTED, f"Malformed amount value: '{row.amount_str}'"

            # Check for DR / CR indicators in raw fields or description
            full_text = " ".join(str(v) for v in row.raw_fields.values()).upper()
            has_dr = bool(re.search(r"\b(DR|DEBIT)\b", full_text))
            has_cr = bool(re.search(r"\b(CR|CREDIT)\b", full_text))

            if dialect.sign_convention == "inverted":
                # Inverted convention (credit card statement where purchase is positive)
                amt = -amt

            if has_dr and not has_cr:
                amt = -abs(amt)
            elif has_cr and not has_dr:
                amt = abs(amt)

            direction = TransactionDirection.DEBIT.value if amt < Decimal("0") else TransactionDirection.CREDIT.value
            return amt, direction, VerificationStatus.VERIFIED, None

        return None, "debit", VerificationStatus.REJECTED, "No amount column present in row"

    @classmethod
    def parse_date(
        cls,
        date_str: Optional[str],
        date_format: str,
    ) -> Tuple[Optional[date], Optional[str]]:
        """
        Parses date string with fallback formats.
        Returns: (parsed_date, error_message)
        """
        if not date_str or not date_str.strip():
            return None, "Empty date field"

        s = date_str.strip()
        formats_to_try = [
            date_format,
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%d-%m-%Y",
            "%d-%b-%Y",
            "%Y/%m/%d",
            "%d.%m.%Y",
        ]

        # Deduplicate while preserving order
        unique_formats = []
        for fmt in formats_to_try:
            if fmt not in unique_formats:
                unique_formats.append(fmt)

        for fmt in unique_formats:
            try:
                dt = datetime.strptime(s, fmt)
                return dt.date(), None
            except ValueError:
                continue

        return None, f"Unable to parse date string '{date_str}' with candidate formats"

    @staticmethod
    def normalize_description(raw_desc: Optional[str]) -> str:
        """
        Cleans and standardizes transaction description:
        - Collapses multiline whitespace and extra tabs
        - Strips noisy terminal reference tags (e.g. '#REF12345')
        """
        if not raw_desc:
            return "Unspecified Transaction"

        # Collapse whitespace and newlines
        clean = re.sub(r"\s+", " ", raw_desc).strip()

        # Remove trailing transaction ref numbers like 'REF# 123456789' or 'ID: 987654'
        clean = re.sub(r"\s+(?:REF|TRX|TXN|ID)[\s#:]+[a-zA-Z0-9_-]+$", "", clean, flags=re.IGNORECASE)

        return clean.strip() or "Unspecified Transaction"
