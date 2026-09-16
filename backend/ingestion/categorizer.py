"""
backend/ingestion/categorizer.py

Deterministic rule-based transaction categorizer with transparent rule provenance.
"""
from __future__ import annotations
import re
from typing import Dict, List, Tuple


CATEGORY_RULES: List[Tuple[str, List[str]]] = [
    (
        "salary",
        [
            r"\bsalary\b", r"\bpayroll\b", r"\bdirect\s+dep\b", r"\bdirect\s+deposit\b",
            r"\bstipend\b", r"\bwages\b", r"\bbonus\b", r"\bemployer\b"
        ],
    ),
    (
        "rent",
        [
            r"\brent\b", r"\blease\b", r"\blandlord\b", r"\bapartment\b",
            r"\bhousing\b", r"\bproperty\s+mgmt\b"
        ],
    ),
    (
        "groceries",
        [
            r"\bgrocery\b", r"\bgroceries\b", r"\bsupermarket\b", r"\bwalmart\b",
            r"\bkroger\b", r"\bwhole\s*foods\b", r"\btrader\s*joe\b", r"\btesco\b",
            r"\bsafeway\b", r"\baldi\b", r"\bcostco\b", r"\bpublix\b", r"\bfresh\s*market\b"
        ],
    ),
    (
        "utilities",
        [
            r"\belectric\b", r"\bwater\b", r"\bgas\s*bill\b", r"\binternet\b",
            r"\bbroadband\b", r"\bmobile\b", r"\butility\b", r"\butilities\b",
            r"\bverizon\b", r"\bat&t\b", r"\bcomcast\b", r"\bxfinity\b", r"\bpower\b"
        ],
    ),
    (
        "transport",
        [
            r"\buber\b", r"\blyft\b", r"\bfuel\b", r"\bgas\s*station\b",
            r"\bmetro\b", r"\bsubway\b", r"\btransit\b", r"\btrain\b",
            r"\bparking\b", r"\bshell\b", r"\bchevron\b", r"\bbp\b",
            r"\bexxon\b", r"\btoll\b"
        ],
    ),
    (
        "dining",
        [
            r"\brestaurant\b", r"\bcafe\b", r"\bcoffee\b", r"\bstarbucks\b",
            r"\bmcdonald\b", r"\bburger\b", r"\buber\s*eats\b", r"\bdoordash\b",
            r"\bgrubhub\b", r"\bpizza\b", r"\bbar\b", r"\bpub\b", r"\bbakery\b",
            r"\bdiner\b", r"\bchipotle\b", r"\bsubway\s+(?:restaurant|sandwiches|food)\b"
        ],
    ),
    (
        "shopping",
        [
            r"\bamazon\b", r"\btarget\b", r"\bebay\b", r"\bclothing\b",
            r"\bretail\b", r"\bzara\b", r"\bh&m\b", r"\bbest\s*buy\b",
            r"\bapple\s*store\b", r"\bdepartment\s*store\b", r"\bmall\b"
        ],
    ),
    (
        "entertainment",
        [
            r"\bnetflix\b", r"\bspotify\b", r"\bcinema\b", r"\bmovie\b",
            r"\btheater\b", r"\bhulu\b", r"\bsteam\b", r"\bplaystation\b",
            r"\bdisney\b", r"\bhbo\b", r"\bprime\s*video\b"
        ],
    ),
    (
        "healthcare",
        [
            r"\bpharmacy\b", r"\bdoctor\b", r"\bhospital\b", r"\bclinic\b",
            r"\bdental\b", r"\bcvs\b", r"\bwalgreens\b", r"\bmedical\b",
            r"\bhealth\b", r"\bmedicine\b", r"\boptometry\b"
        ],
    ),
    (
        "debt",
        [
            r"\bloan\b", r"\bmortgage\b", r"\binterest\s*charge\b",
            r"\bcredit\s*card\s*payment\b", r"\bchase\s*card\b", r"\bamex\b",
            r"\bcapital\s*one\b", r"\bauto\s*loan\b"
        ],
    ),
    (
        "cash_withdrawal",
        [
            r"\batm\b", r"\bcash\s*withdrawal\b", r"\bcash\s*out\b", r"\bbank\s*teller\b"
        ],
    ),
    (
        "transfer",
        [
            r"\btransfer\b", r"\bzelle\b", r"\bvenmo\b", r"\bwire\b",
            r"\bach\b", r"\bp2p\b"
        ],
    ),
]


class RuleBasedCategorizer:
    """
    Deterministic rule-based transaction categorizer.
    Matches normalized description against regex pattern sets with logged match reason.
    """

    @classmethod
    def categorize(cls, normalized_description: str, explicit_category: str | None = None) -> Tuple[str, str]:
        """
        Categorizes transaction and returns (category, reason).
        """
        # If the statement explicitly gave a category, check if it maps to a standard category
        if explicit_category and explicit_category.strip():
            raw_clean = explicit_category.strip().lower()
            for cat, _ in CATEGORY_RULES:
                if cat in raw_clean:
                    return cat, f"source_statement_header:{explicit_category}"

        text = normalized_description.lower()

        # Check rules in priority order
        for cat, patterns in CATEGORY_RULES:
            for pat in patterns:
                m = re.search(pat, text)
                if m:
                    return cat, f"regex_match:{m.group(0)}"

        # Default fallback
        return "other", "unmatched_fallback"
