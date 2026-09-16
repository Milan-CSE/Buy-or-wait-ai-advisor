"""
backend/ingestion/dialect.py

Robust CSV dialect detection, delimiter sniffing, and flexible column mapping.
"""
from __future__ import annotations
import csv
import io
import re
from typing import Dict, List, Optional, Tuple

from backend.ingestion.models import DialectInfo


# Common synonyms for statement columns (lowercased, stripped)
DATE_SYNONYMS = {
    "date", "transaction date", "txn date", "posted date", "posting date",
    "value date", "date settled", "booking date", "trans date", "activity date"
}

DESC_SYNONYMS = {
    "description", "narration", "narrative", "details", "payee",
    "merchant", "memo", "transaction details", "particulars", "name",
    "counterparty", "transaction description", "reference"
}

AMOUNT_SYNONYMS = {
    "amount", "transaction amount", "total", "value", "net amount",
    "trans amount", "amount (usd)", "amount (inr)", "amount (gbp)", "amount (eur)"
}

DEBIT_SYNONYMS = {
    "debit", "debits", "withdrawal", "withdrawals", "paid out",
    "debit amount", "dr", "expense", "spent", "outgoing", "payments",
    "debit (dr)", "withdrawal (dr)", "amount debited"
}

CREDIT_SYNONYMS = {
    "credit", "credits", "deposit", "deposits", "paid in",
    "credit amount", "cr", "income", "received", "incoming", "lodgements",
    "credit (cr)", "deposit (cr)", "amount credited"
}

CURRENCY_SYNONYMS = {
    "currency", "curr", "ccy", "iso currency"
}

CATEGORY_SYNONYMS = {
    "category", "classification", "type", "transaction type", "tag"
}

BALANCE_SYNONYMS = {
    "balance", "running balance", "available balance", "closing balance", "ledger balance"
}


class DialectDetector:
    """
    Analyzes sample text from financial statements to determine delimiters,
    column headers, date formats, and sign conventions.
    """

    @staticmethod
    def detect_delimiter(text_sample: str) -> str:
        """Determines the most likely CSV delimiter."""
        candidates = [",", ";", "\t", "|"]
        first_lines = text_sample.splitlines()[:5]
        if not first_lines:
            return ","

        # Count frequencies per candidate
        scores = {c: 0 for c in candidates}
        for line in first_lines:
            for c in candidates:
                scores[c] += line.count(c)

        best_delim = max(scores, key=scores.get)
        return best_delim if scores[best_delim] > 0 else ","

    @classmethod
    def match_column(cls, header: str, synonyms: set[str]) -> bool:
        """Fuzzy matches a single column header against a synonym set."""
        clean = re.sub(r"[^a-zA-Z0-9\s]", " ", header).lower().strip()
        clean = re.sub(r"\s+", " ", clean)
        if clean in synonyms:
            return True
        for syn in synonyms:
            if syn in clean:
                return True
        return False

    @classmethod
    def detect_columns(cls, headers: List[str]) -> Tuple[
        Optional[str], Optional[str], Optional[str], Optional[str],
        Optional[str], Optional[str], Optional[str], Optional[str]
    ]:
        """
        Maps raw headers to normalized roles:
        Returns: (date_col, desc_col, amount_col, debit_col, credit_col, currency_col, category_col, balance_col)
        """
        date_col = None
        desc_col = None
        amount_col = None
        debit_col = None
        credit_col = None
        currency_col = None
        category_col = None
        balance_col = None

        for h in headers:
            h_strip = h.strip()
            if not date_col and cls.match_column(h_strip, DATE_SYNONYMS):
                date_col = h_strip
            elif not desc_col and cls.match_column(h_strip, DESC_SYNONYMS):
                desc_col = h_strip
            elif not debit_col and cls.match_column(h_strip, DEBIT_SYNONYMS):
                debit_col = h_strip
            elif not credit_col and cls.match_column(h_strip, CREDIT_SYNONYMS):
                credit_col = h_strip
            elif not amount_col and cls.match_column(h_strip, AMOUNT_SYNONYMS):
                amount_col = h_strip
            elif not currency_col and cls.match_column(h_strip, CURRENCY_SYNONYMS):
                currency_col = h_strip
            elif not category_col and cls.match_column(h_strip, CATEGORY_SYNONYMS):
                category_col = h_strip
            elif not balance_col and cls.match_column(h_strip, BALANCE_SYNONYMS):
                balance_col = h_strip

        return date_col, desc_col, amount_col, debit_col, credit_col, currency_col, category_col, balance_col

    @staticmethod
    def detect_date_format(sample_dates: List[str]) -> str:
        """
        Detects date format based on sample string patterns.
        """
        for s in sample_dates:
            s = s.strip()
            # YYYY-MM-DD
            if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
                return "%Y-%m-%d"
            # YYYY/MM/DD
            if re.match(r"^\d{4}/\d{2}/\d{2}$", s):
                return "%Y/%m/%d"
            # DD-Mon-YYYY (e.g. 15-Sep-2026)
            if re.match(r"^\d{1,2}-[a-zA-Z]{3}-\d{4}$", s):
                return "%d-%b-%Y"
            # DD/MM/YYYY vs MM/DD/YYYY
            m = re.match(r"^(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})$", s)
            if m:
                first, second, _ = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if first > 12 >= second:
                    return "%d/%m/%Y"
                elif second > 12 >= first:
                    return "%m/%d/%Y"

        # Default fallback to standard ISO or DD/MM/YYYY
        return "%Y-%m-%d"

    @classmethod
    def detect_dialect(cls, text_content: str, encoding: str = "utf-8") -> DialectInfo:
        """
        Full dialect detection pipeline for a text string.
        """
        delimiter = cls.detect_delimiter(text_content)
        reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)

        headers = []
        sample_rows = []
        for i, row in enumerate(reader):
            # Skip blank lines
            if not row or not any(cell.strip() for cell in row):
                continue
            if not headers:
                headers = [col.strip() for col in row]
            else:
                sample_rows.append(row)
                if len(sample_rows) >= 10:
                    break

        (
            date_col, desc_col, amount_col,
            debit_col, credit_col, currency_col,
            category_col, balance_col
        ) = cls.detect_columns(headers)

        if not date_col:
            raise ValueError(f"Could not identify Date column in headers: {headers}")
        if not desc_col:
            # Fallback to second column or description-like
            desc_col = headers[1] if len(headers) > 1 else headers[0]
        if not amount_col and not (debit_col or credit_col):
            raise ValueError(f"Could not identify Amount or Debit/Credit columns in headers: {headers}")

        # Sample dates for format sniffing
        sample_dates = []
        try:
            date_idx = headers.index(date_col)
            for r in sample_rows:
                if len(r) > date_idx and r[date_idx].strip():
                    sample_dates.append(r[date_idx].strip())
        except ValueError:
            pass

        date_format = cls.detect_date_format(sample_dates)

        return DialectInfo(
            delimiter=delimiter,
            has_header=True,
            date_column=date_col,
            desc_column=desc_col,
            amount_column=amount_col,
            debit_column=debit_col,
            credit_column=credit_col,
            currency_column=currency_col,
            category_column=category_col,
            balance_column=balance_col,
            date_format=date_format,
            sign_convention="standard",
            encoding=encoding,
        )
