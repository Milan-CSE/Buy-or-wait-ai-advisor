"""
backend/ingestion/parsers/base.py

Base statement parser interface.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from backend.ingestion.models import DialectInfo, ParsedRow


class BaseStatementParser(ABC):
    @abstractmethod
    def parse(
        self,
        content: bytes,
        dialect: Optional[DialectInfo] = None,
    ) -> Tuple[DialectInfo, List[ParsedRow], List[str]]:
        """
        Parses raw file bytes into a list of extracted ParsedRow objects.
        Returns: (detected_dialect, parsed_rows, parse_errors)
        """
        pass
