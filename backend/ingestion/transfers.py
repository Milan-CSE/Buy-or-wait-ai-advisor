"""
backend/ingestion/transfers.py

Detection of internal transfers between user-owned accounts to prevent artificial inflation of income or expenses.
"""
from __future__ import annotations
import re
from typing import List, Optional


INTERNAL_TRANSFER_PATTERNS = [
    r"\btransfer\s+to\s+(?:checking|savings|account)\b",
    r"\btransfer\s+from\s+(?:checking|savings|account)\b",
    r"\binternal\s+transfer\b",
    r"\bself\s+transfer\b",
    r"\baccount\s+transfer\b",
    r"\bonline\s+transfer\s+to\b",
    r"\bonline\s+transfer\s+from\b",
    r"\bxfer\s+(?:to|from)\b",
    r"\bto\s+savings\b",
    r"\bto\s+checking\b",
    r"\bfrom\s+savings\b",
    r"\bfrom\s+checking\b",
]


class InternalTransferDetector:
    """
    Identifies internal account transfers from transaction descriptions
    and user account metadata.
    """

    @classmethod
    def is_internal_transfer(
        cls,
        normalized_description: str,
        user_account_names: Optional[List[str]] = None,
    ) -> bool:
        """
        Determines whether a transaction is an internal transfer between user accounts.
        """
        text = normalized_description.lower()

        # Check known account names
        if user_account_names:
            for acc in user_account_names:
                acc_clean = acc.lower().strip()
                if acc_clean and acc_clean in text:
                    if "transfer" in text or "xfer" in text:
                        return True

        # Check keyword regexes
        for pat in INTERNAL_TRANSFER_PATTERNS:
            if re.search(pat, text):
                return True

        return False
