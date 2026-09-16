"""
backend/ingestion/parsers/csv_parser.py

Production-grade CSV financial statement parser.
"""
from __future__ import annotations
import csv
import io
from typing import List, Optional, Tuple

from backend.ingestion.dialect import DialectDetector
from backend.ingestion.models import DialectInfo, ParsedRow
from backend.ingestion.parsers.base import BaseStatementParser


class CSVStatementParser(BaseStatementParser):
    SUPPORTED_ENCODINGS = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]

    def _decode_content(self, content: bytes) -> Tuple[str, str]:
        """Tries decoding byte content using supported encodings."""
        for enc in self.SUPPORTED_ENCODINGS:
            try:
                return content.decode(enc), enc
            except UnicodeDecodeError:
                continue
        # Fallback with replacement
        return content.decode("utf-8", errors="replace"), "utf-8-replace"

    def parse(
        self,
        content: bytes,
        dialect: Optional[DialectInfo] = None,
    ) -> Tuple[DialectInfo, List[ParsedRow], List[str]]:
        text, detected_enc = self._decode_content(content)
        parse_errors: List[str] = []

        if dialect is None:
            try:
                dialect = DialectDetector.detect_dialect(text, encoding=detected_enc)
            except Exception as e:
                parse_errors.append(f"Dialect detection failed: {str(e)}")
                return (
                    DialectInfo(
                        delimiter=",",
                        has_header=True,
                        date_column="Date",
                        desc_column="Description",
                        amount_column="Amount",
                        debit_column=None,
                        credit_column=None,
                        currency_column=None,
                        category_column=None,
                        balance_column=None,
                        date_format="%Y-%m-%d",
                        sign_convention="standard",
                        encoding=detected_enc,
                    ),
                    [],
                    parse_errors,
                )

        reader = csv.reader(
            io.StringIO(text),
            delimiter=dialect.delimiter,
            skipinitialspace=True,
        )

        headers: List[str] = []
        parsed_rows: List[ParsedRow] = []

        for line_num, row in enumerate(reader, start=1):
            if not row or not any(c.strip() for c in row):
                continue

            if not headers:
                headers = [h.strip() for h in row]
                continue

            if len(row) != len(headers):
                # Try to salvage or record error
                if len(row) < len(headers):
                    # Pad with empty strings
                    row = row + [""] * (len(headers) - len(row))
                else:
                    parse_errors.append(
                        f"Line {line_num}: Row has {len(row)} columns, expected {len(headers)}. Ignored excess columns."
                    )
                    row = row[:len(headers)]

            raw_dict = {headers[i]: row[i].strip() for i in range(len(headers))}

            date_val = raw_dict.get(dialect.date_column)
            desc_val = raw_dict.get(dialect.desc_column)
            amount_val = raw_dict.get(dialect.amount_column) if dialect.amount_column else None
            debit_val = raw_dict.get(dialect.debit_column) if dialect.debit_column else None
            credit_val = raw_dict.get(dialect.credit_column) if dialect.credit_column else None
            curr_val = raw_dict.get(dialect.currency_column) if dialect.currency_column else None
            cat_val = raw_dict.get(dialect.category_column) if dialect.category_column else None
            bal_val = raw_dict.get(dialect.balance_column) if dialect.balance_column else None

            parsed_rows.append(
                ParsedRow(
                    line_number=line_num,
                    raw_fields=raw_dict,
                    date_str=date_val,
                    description_str=desc_val,
                    amount_str=amount_val,
                    debit_str=debit_val,
                    credit_str=credit_val,
                    currency_str=curr_val,
                    category_str=cat_val,
                    balance_str=bal_val,
                )
            )

        return dialect, parsed_rows, parse_errors
