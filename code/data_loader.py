"""
data_loader.py
Strict schema loading for all Buy-or-Wait? dataset files.
Uses Decimal for monetary amounts, datetime.date for dates.
Builds indexed lookups for efficient per-user/per-request access.
"""
from __future__ import annotations
import csv
import os
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, List, Tuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DATASET_DIR = os.path.join(os.path.dirname(__file__), '..', 'dataset')


def _path(filename: str) -> str:
    return os.path.join(DATASET_DIR, filename)


def _dec(value: str) -> Optional[Decimal]:
    """Parse a decimal value; return None if blank or not parseable."""
    if value is None or str(value).strip() in ('', 'nan', 'NaN', 'None'):
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation:
        return None


def _date(value: str) -> Optional[date]:
    """Parse YYYY-MM-DD date; return None if blank."""
    if value is None or str(value).strip() in ('', 'nan', 'NaN', 'None'):
        return None
    return date.fromisoformat(str(value).strip())


def _str(value: str) -> str:
    v = str(value).strip() if value is not None else ''
    return '' if v in ('nan', 'NaN', 'None') else v


def _bool(value: str) -> bool:
    return str(value).strip().lower() in ('true', '1', 'yes')


def _pipe_list(value: str) -> List[str]:
    v = _str(value)
    if not v:
        return []
    return [x.strip() for x in v.split('|') if x.strip()]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FinancialProfile:
    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: List[str]                    # pipe-delimited list
    expense_categories_to_protect: List[str]
    expense_categories_user_is_willing_to_reduce: List[str]
    expense_categories_user_is_willing_to_stop: List[str]
    payment_methods_user_will_consider: List[str]
    max_installment_months: Optional[Decimal]          # None = installments not considered


@dataclass
class FinancialEvent:
    event_id: str
    user_id: str
    event_type: str          # expense | subscription | income | debt_payment | investment_*| refund
    description: str
    category: str
    direction: str           # debit | credit | non_cash
    amount: Optional[Decimal]  # None = resolved from image
    currency: str
    event_date: Optional[date]
    settlement_date: Optional[date]
    status: str              # settled | pending | scheduled | cancelled | failed | unrealized
    linked_event_id: Optional[str]
    flexibility: str         # fixed | reducible | stoppable | reducible_or_stoppable
    minimum_allowed_amount: Optional[Decimal]


@dataclass
class ExchangeRate:
    rate_date: date
    from_currency: str
    to_currency: str
    rate: Decimal


@dataclass
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


@dataclass
class SampleRequest:
    # Input fields
    request: Request
    # Ground-truth output fields
    amount_safe_to_pay: Optional[Decimal]
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str          # raw string "none" or "YYYY-MM-DD:amt|..."
    earliest_date_for_full_payment: Optional[date]
    spending_changes_needed: str
    decision_explanation: str


@dataclass
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str        # full_payment | installments
    payment_amount: Decimal    # per-payment amount
    number_of_payments: int
    first_payment_date: Optional[date]
    payment_frequency_days: Optional[int]   # None for full_payment
    financing_fee: Decimal
    total_payable_amount: Decimal


@dataclass
class Message:
    message_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]
    sent_at: str
    source_type: str           # employer | service_provider | financial_service | bank | merchant
    message_text: str


@dataclass
class ImageRecord:
    image_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]


# ---------------------------------------------------------------------------
# Dataset container
# ---------------------------------------------------------------------------

@dataclass
class Dataset:
    profiles: Dict[str, FinancialProfile]              # user_id -> profile
    events: Dict[str, FinancialEvent]                  # event_id -> event
    events_by_user: Dict[str, List[FinancialEvent]]    # user_id -> [events]
    exchange_rates: List[ExchangeRate]
    fx_index: Dict[Tuple[date, str, str], Decimal]     # (date, from, to) -> rate
    requests: Dict[str, Request]                       # request_id -> request
    requests_by_user: Dict[str, Request]               # user_id -> request (1:1)
    sample_requests: Dict[str, SampleRequest]          # request_id -> sample
    payment_options: Dict[str, List[PaymentOption]]    # request_id -> [options]
    messages_by_user: Dict[str, List[Message]]         # user_id -> [messages]
    messages_by_request: Dict[str, List[Message]]      # request_id -> [messages]
    messages_by_event: Dict[str, List[Message]]        # event_id -> [messages]
    images: Dict[str, ImageRecord]                     # image_id -> record
    images_by_event: Dict[str, ImageRecord]            # event_id -> image record
    images_by_request: Dict[str, List[ImageRecord]]    # request_id -> [images]


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _read_csv(filename: str) -> List[Dict[str, str]]:
    filepath = _path(filename)
    rows = []
    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def load_dataset() -> Dataset:
    # --- profiles ---
    profiles: Dict[str, FinancialProfile] = {}
    for row in _read_csv('financial_profiles.csv'):
        p = FinancialProfile(
            user_id=_str(row['user_id']),
            home_currency=_str(row['home_currency']),
            current_available_balance=_dec(row['current_available_balance']) or Decimal('0'),
            minimum_balance_to_keep=_dec(row['minimum_balance_to_keep']) or Decimal('0'),
            financial_priorities=_pipe_list(row['financial_priorities']),
            expense_categories_to_protect=_pipe_list(row['expense_categories_to_protect']),
            expense_categories_user_is_willing_to_reduce=_pipe_list(row['expense_categories_user_is_willing_to_reduce']),
            expense_categories_user_is_willing_to_stop=_pipe_list(row['expense_categories_user_is_willing_to_stop']),
            payment_methods_user_will_consider=_pipe_list(row['payment_methods_user_will_consider']),
            max_installment_months=_dec(row['max_installment_months']),
        )
        profiles[p.user_id] = p

    # --- events ---
    events: Dict[str, FinancialEvent] = {}
    events_by_user: Dict[str, List[FinancialEvent]] = {}
    for row in _read_csv('financial_events.csv'):
        e = FinancialEvent(
            event_id=_str(row['event_id']),
            user_id=_str(row['user_id']),
            event_type=_str(row['event_type']),
            description=_str(row['description']),
            category=_str(row['category']),
            direction=_str(row['direction']),
            amount=_dec(row['amount']),
            currency=_str(row['currency']),
            event_date=_date(row['event_date']),
            settlement_date=_date(row['settlement_date']),
            status=_str(row['status']),
            linked_event_id=_str(row['linked_event_id']) or None,
            flexibility=_str(row['flexibility']),
            minimum_allowed_amount=_dec(row['minimum_allowed_amount']),
        )
        events[e.event_id] = e
        events_by_user.setdefault(e.user_id, []).append(e)

    # --- exchange rates ---
    exchange_rates: List[ExchangeRate] = []
    fx_index: Dict[Tuple[date, str, str], Decimal] = {}
    for row in _read_csv('exchange_rates.csv'):
        r = ExchangeRate(
            rate_date=_date(row['rate_date']),
            from_currency=_str(row['from_currency']),
            to_currency=_str(row['to_currency']),
            rate=_dec(row['rate']),
        )
        exchange_rates.append(r)
        fx_index[(r.rate_date, r.from_currency, r.to_currency)] = r.rate

    # --- requests ---
    requests: Dict[str, Request] = {}
    requests_by_user: Dict[str, Request] = {}
    for row in _read_csv('requests.csv'):
        r = Request(
            request_id=_str(row['request_id']),
            user_id=_str(row['user_id']),
            request_date=_date(row['request_date']),
            request_type=_str(row['request_type']),
            requested_amount=_dec(row['requested_amount']) or Decimal('0'),
            desired_completion_date=_date(row['desired_completion_date']),
            allows_partial_payment=_bool(row['allows_partial_payment']),
            request_text=_str(row['request_text']),
        )
        requests[r.request_id] = r
        requests_by_user[r.user_id] = r

    # --- sample requests ---
    sample_requests: Dict[str, SampleRequest] = {}
    for row in _read_csv('sample_requests.csv'):
        req = Request(
            request_id=_str(row['request_id']),
            user_id=_str(row['user_id']),
            request_date=_date(row['request_date']),
            request_type=_str(row['request_type']),
            requested_amount=_dec(row['requested_amount']) or Decimal('0'),
            desired_completion_date=_date(row['desired_completion_date']),
            allows_partial_payment=_bool(row['allows_partial_payment']),
            request_text=_str(row['request_text']),
        )
        sr = SampleRequest(
            request=req,
            amount_safe_to_pay=_dec(row['amount_safe_to_pay']),
            affordability_status=_str(row['affordability_status']),
            recommended_payment_method=_str(row['recommended_payment_method']),
            payment_plan=_str(row['payment_plan']),
            earliest_date_for_full_payment=_date(row['earliest_date_for_full_payment']),
            spending_changes_needed=_str(row['spending_changes_needed']),
            decision_explanation=_str(row['decision_explanation']),
        )
        sample_requests[req.request_id] = sr
        # Also index profiles for sample users if not already
        if req.user_id not in requests_by_user:
            requests_by_user[req.user_id] = req

    # --- payment options ---
    payment_options: Dict[str, List[PaymentOption]] = {}
    for row in _read_csv('request_payment_options.csv'):
        num_pay = int(_dec(row['number_of_payments']) or 1)
        freq_days_dec = _dec(row['payment_frequency_days'])
        freq_days = int(freq_days_dec) if freq_days_dec is not None else None
        po = PaymentOption(
            payment_option_id=_str(row['payment_option_id']),
            request_id=_str(row['request_id']),
            payment_method=_str(row['payment_method']),
            payment_amount=_dec(row['payment_amount']) or Decimal('0'),
            number_of_payments=num_pay,
            first_payment_date=_date(row['first_payment_date']),
            payment_frequency_days=freq_days,
            financing_fee=_dec(row['financing_fee']) or Decimal('0'),
            total_payable_amount=_dec(row['total_payable_amount']) or Decimal('0'),
        )
        payment_options.setdefault(po.request_id, []).append(po)

    # --- messages ---
    messages_by_user: Dict[str, List[Message]] = {}
    messages_by_request: Dict[str, List[Message]] = {}
    messages_by_event: Dict[str, List[Message]] = {}
    for row in _read_csv('messages.csv'):
        m = Message(
            message_id=_str(row['message_id']),
            user_id=_str(row['user_id']),
            request_id=_str(row['request_id']) or None,
            related_event_id=_str(row['related_event_id']) or None,
            sent_at=_str(row['sent_at']),
            source_type=_str(row['source_type']),
            message_text=_str(row['message_text']),
        )
        messages_by_user.setdefault(m.user_id, []).append(m)
        if m.request_id:
            messages_by_request.setdefault(m.request_id, []).append(m)
        if m.related_event_id:
            messages_by_event.setdefault(m.related_event_id, []).append(m)

    # --- images ---
    images: Dict[str, ImageRecord] = {}
    images_by_event: Dict[str, ImageRecord] = {}
    images_by_request: Dict[str, List[ImageRecord]] = {}
    for row in _read_csv('images.csv'):
        img = ImageRecord(
            image_id=_str(row['image_id']),
            user_id=_str(row['user_id']),
            request_id=_str(row['request_id']) or None,
            related_event_id=_str(row['related_event_id']) or None,
        )
        images[img.image_id] = img
        if img.related_event_id:
            images_by_event[img.related_event_id] = img
        if img.request_id:
            images_by_request.setdefault(img.request_id, []).append(img)

    return Dataset(
        profiles=profiles,
        events=events,
        events_by_user=events_by_user,
        exchange_rates=exchange_rates,
        fx_index=fx_index,
        requests=requests,
        requests_by_user=requests_by_user,
        sample_requests=sample_requests,
        payment_options=payment_options,
        messages_by_user=messages_by_user,
        messages_by_request=messages_by_request,
        messages_by_event=messages_by_event,
        images=images,
        images_by_event=images_by_event,
        images_by_request=images_by_request,
    )
