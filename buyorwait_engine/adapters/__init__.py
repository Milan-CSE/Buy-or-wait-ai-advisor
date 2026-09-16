"""
buyorwait_engine/adapters

Adapters for legacy data formats and migration compatibility.
"""
from buyorwait_engine.adapters.legacy import (
    adapt_profile,
    adapt_event,
    adapt_payment_option,
    adapt_request,
)

__all__ = [
    'adapt_profile',
    'adapt_event',
    'adapt_payment_option',
    'adapt_request',
]
