"""
backend/auth/rate_limiter.py

In-memory sliding-window rate limiter and brute-force abuse protection.
Provides category-based quotas (auth, upload, purchases, general) and failed login tracking.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time
from typing import Dict, List, Optional, Tuple


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int
    retry_after: int = 0


class RateLimiter:
    """
    Thread-safe sliding-window rate limiter with per-window timestamp filtering.
    Tracks endpoint categories and failed login attempts.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # key -> list of float epoch timestamps
        self._windows: Dict[str, List[float]] = defaultdict(list)
        # (ip, email) -> list of failed timestamp floats
        self._failed_logins: Dict[Tuple[str, str], List[float]] = defaultdict(list)

    def check(
        self,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitResult:
        """
        Evaluates whether a request with identifier `key` is within `limit` per `window_seconds`.
        """
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            timestamps = self._windows[key]
            # Prune expired timestamps
            valid = [ts for ts in timestamps if ts > cutoff]
            self._windows[key] = valid

            if len(valid) >= limit:
                # Rate limit exceeded
                oldest = valid[0]
                retry_after = max(1, int(oldest + window_seconds - now))
                return RateLimitResult(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    reset_seconds=retry_after,
                    retry_after=retry_after,
                )

            valid.append(now)
            remaining = limit - len(valid)
            reset_seconds = max(1, int(window_seconds))
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=remaining,
                reset_seconds=reset_seconds,
            )

    def record_failed_login(self, ip: str, email: str) -> int:
        """
        Records a failed authentication attempt for (ip, email).
        Returns total failures in the current 5-minute window.
        """
        now = time.time()
        cutoff = now - 300.0  # 5 minutes
        key = (ip, email.strip().lower())

        with self._lock:
            failures = self._failed_logins[key]
            failures = [ts for ts in failures if ts > cutoff]
            failures.append(now)
            self._failed_logins[key] = failures
            return len(failures)

    def clear_failed_login(self, ip: str, email: str) -> None:
        """Clears failed attempts on successful login."""
        key = (ip, email.strip().lower())
        with self._lock:
            self._failed_logins.pop(key, None)

    def is_login_throttled(
        self,
        ip: str,
        email: str,
        max_failures: int = 5,
        cooldown_seconds: int = 60,
    ) -> Tuple[bool, int]:
        """
        Checks if the (ip, email) combination is temporarily throttled due to repeated failures.
        Returns (is_throttled, retry_after_seconds).
        """
        now = time.time()
        cutoff = now - 300.0
        key = (ip, email.strip().lower())

        with self._lock:
            failures = [ts for ts in self._failed_logins[key] if ts > cutoff]
            self._failed_logins[key] = failures
            if len(failures) >= max_failures:
                last_failure = failures[-1]
                elapsed = now - last_failure
                if elapsed < cooldown_seconds:
                    retry_after = max(1, int(cooldown_seconds - elapsed))
                    return True, retry_after

        return False, 0

    def reset_all(self) -> None:
        """Resets all rate limit windows (for testing)."""
        with self._lock:
            self._windows.clear()
            self._failed_logins.clear()


# Global singleton instance
_GLOBAL_RATE_LIMITER = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _GLOBAL_RATE_LIMITER
