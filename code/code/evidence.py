"""
evidence.py
Image evidence manifest (structured, OCR-verified amounts for the 16 challenge images).
Message evidence interface (structured parsing, not raw text for decisions).

IMAGE MANIFEST
--------------
Verified by visual inspection of each image. Key fields:
- image_id: matches images.csv
- related_event_id: the event whose amount is missing
- verified_amount: the resolved amount in the event's currency
- currency: as shown in the image document
- document_type: pay_slip | receipt | invoice | bill | bank_statement | other
- confidence: HIGH | MEDIUM | LOW
- notes: brief validation rationale

MESSAGE EVIDENCE
----------------
Structured parsers extract typed evidence from message text.
Evidence types:
  SALARY_AMENDMENT: explicit next salary amount
  SALARY_DATE: confirmed first/next payment date
  RENT_AMENDMENT: new rent amount or percentage change
  PENDING_CREDIT_UNCONFIRMED: confirms a pending credit is not yet settled
  PENDING_REFUND_UNCONFIRMED: refund initiated but not received
  UNREALIZED_GAIN: portfolio gain is paper-only, no cash
  INTERNAL_TRANSFER: matching debit/credit is self-transfer
  WINDFALL_CLOSED: one-time prize fully settled, no recurring payment
  PENDING_INCOME_UNCONFIRMED: bonus/commission not yet approved
"""
from __future__ import annotations
from datetime import date
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

from data_loader import Dataset, ImageRecord, Message


# ---------------------------------------------------------------------------
# Image evidence manifest (hardcoded from OCR verification)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ImageFact:
    image_id: str
    related_event_id: str
    verified_amount: Decimal
    currency: str
    document_type: str
    confidence: str  # HIGH | MEDIUM | LOW
    notes: str


# Verified amounts extracted by visual inspection of all 16 PNGs
IMAGE_MANIFEST: Dict[str, ImageFact] = {f.image_id: f for f in [
    ImageFact(
        image_id='image_01',
        related_event_id='event_253',
        verified_amount=Decimal('4365000'),
        currency='IDR',
        document_type='pay_slip',
        confidence='HIGH',
        notes='PAY SLIP Aug-2019. Net Pay = IDR 4,365,000 explicitly stated.',
    ),
    ImageFact(
        image_id='image_02',
        related_event_id='event_1442',
        verified_amount=Decimal('100000'),
        currency='INR',
        document_type='receipt',
        confidence='HIGH',
        notes='Rent receipt. Amount Received = 1,00,000. Balance Due = 1,00,000. '
              'Event is scheduled debit (outstanding rent balance). Using Balance Due.',
    ),
    ImageFact(
        image_id='image_03',
        related_event_id='event_1545',
        verified_amount=Decimal('41272'),
        currency='INR',
        document_type='receipt',
        confidence='HIGH',
        notes='Bill of Supply 27/02/2026. Net Amount = INR 41,272.',
    ),
    ImageFact(
        image_id='image_04',
        related_event_id='event_1700',
        verified_amount=Decimal('2854'),
        currency='INR',
        document_type='receipt',
        confidence='HIGH',
        notes='Grocery delivery order. Item Bill = INR 2,854 (before delivery charges).',
    ),
    ImageFact(
        image_id='image_05',
        related_event_id='event_1786',
        verified_amount=Decimal('704.05'),
        currency='INR',
        document_type='bill',
        confidence='HIGH',
        notes='Airtel telecom bill. Amount due till 06-Feb-2026 = INR 704.05.',
    ),
    ImageFact(
        image_id='image_06',
        related_event_id='event_3051',
        verified_amount=Decimal('1995'),
        currency='INR',
        document_type='invoice',
        confidence='HIGH',
        notes='Grocery tax invoice. Grand Total = INR 1,995.',
    ),
    ImageFact(
        image_id='image_07',
        related_event_id='event_3231',
        verified_amount=Decimal('8528'),
        currency='INR',
        document_type='invoice',
        confidence='HIGH',
        notes='Restaurant tax invoice. Grand Total = INR 8,528.',
    ),
    ImageFact(
        image_id='image_08',
        related_event_id='event_4535',
        verified_amount=Decimal('15339'),
        currency='INR',
        document_type='receipt',
        confidence='HIGH',
        notes='Property maintenance receipt. Total Amount Received = INR 15,339.',
    ),
    ImageFact(
        image_id='image_09',
        related_event_id='event_5170',
        verified_amount=Decimal('723'),
        currency='INR',
        document_type='receipt',
        confidence='HIGH',
        notes='Water bill receipt. Total Amount Received = INR 723.',
    ),
    ImageFact(
        image_id='image_10',
        related_event_id='event_6033',
        verified_amount=Decimal('79679.26'),
        currency='INR',
        document_type='invoice',
        confidence='HIGH',
        notes='Grocery tax invoice. Balance Due = INR 79,679.26.',
    ),
    ImageFact(
        image_id='image_11',
        related_event_id='event_6859',
        verified_amount=Decimal('3650'),
        currency='INR',
        document_type='invoice',
        confidence='HIGH',
        notes='Hospital provisional bill. Total Bill Amount = INR 3,650.',
    ),
    ImageFact(
        image_id='image_12',
        related_event_id='event_7307',
        verified_amount=Decimal('33.50'),
        currency='USD',
        document_type='receipt',
        confidence='HIGH',
        notes='Taxi receipt (CityCab). Total = USD 33.50.',
    ),
    ImageFact(
        image_id='image_13',
        related_event_id='event_7941',
        verified_amount=Decimal('2298'),
        currency='INR',
        document_type='receipt',
        confidence='HIGH',
        notes='E-commerce order. Total paid = INR 2,298.',
    ),
    ImageFact(
        image_id='image_14',
        related_event_id='event_9421',
        verified_amount=Decimal('4543'),
        currency='INR',
        document_type='receipt',
        confidence='MEDIUM',
        notes='Handwritten pharmacy bill. TOTAL = Rs 4,543 (handwritten, arithmetic verified).',
    ),
    ImageFact(
        image_id='image_15',
        related_event_id='event_9806',
        verified_amount=Decimal('9968'),
        currency='INR',
        document_type='invoice',
        confidence='HIGH',
        notes='IndiGo airline e-ticket invoice. Grand Total = INR 9,968.',
    ),
    ImageFact(
        image_id='image_16',
        related_event_id='event_10521',
        verified_amount=Decimal('393.22'),
        currency='INR',
        document_type='invoice',
        confidence='HIGH',
        notes='EV charging invoice. Total = INR 393.22.',
    ),
]}

# Build lookup by related_event_id for fast access
IMAGE_BY_EVENT: Dict[str, ImageFact] = {f.related_event_id: f for f in IMAGE_MANIFEST.values()}


def get_image_amount(event_id: str) -> Optional[ImageFact]:
    """Return the verified ImageFact for an event with a missing amount, or None."""
    return IMAGE_BY_EVENT.get(event_id)


# ---------------------------------------------------------------------------
# Message evidence
# ---------------------------------------------------------------------------

class MessageEvidenceType(Enum):
    SALARY_AMENDMENT = 'salary_amendment'
    SALARY_DATE = 'salary_date'
    RENT_AMENDMENT = 'rent_amendment'
    PENDING_CREDIT_UNCONFIRMED = 'pending_credit_unconfirmed'
    PENDING_REFUND_UNCONFIRMED = 'pending_refund_unconfirmed'
    UNREALIZED_GAIN = 'unrealized_gain'
    INTERNAL_TRANSFER = 'internal_transfer'
    WINDFALL_CLOSED = 'windfall_closed'
    PENDING_INCOME_UNCONFIRMED = 'pending_income_unconfirmed'
    SALARY_CONFIRMED = 'salary_confirmed'
    CONTRACT_TERMINATED = 'contract_terminated'
    UNKNOWN = 'unknown'


@dataclass
class MessageEvidence:
    message_id: str
    source_type: str
    evidence_type: MessageEvidenceType
    # Structured fields (populated when applicable)
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    percentage_change: Optional[Decimal] = None
    effective_date: Optional[date] = None
    confidence: str = 'MEDIUM'
    raw_note: str = ''


# Regex patterns for structured extraction
_AMOUNT_PATTERNS = [
    # "EUR 1,037.52" or "IDR 38760000" or "ZAR 45,760"
    r'(?:EUR|USD|INR|IDR|ZAR)\s*[\d,]+(?:\.\d+)?',
    # currency code after number "1661 EUR"
    r'[\d,]+(?:\.\d+)?\s*(?:EUR|USD|INR|IDR|ZAR)',
]

_AMOUNT_RE = re.compile(
    r'(?P<code>EUR|USD|INR|IDR|ZAR)\s*(?P<amt>[\d,]+(?:\.\d+)?)' +
    r'|(?P<amt2>[\d,]+(?:\.\d+)?)\s*(?P<code2>EUR|USD|INR|IDR|ZAR)',
    re.IGNORECASE
)

_PCT_RE = re.compile(r'(\d+(?:\.\d+)?)\s*%')


def _extract_first_amount(text: str) -> Optional[tuple]:
    """Return (Decimal amount, str currency) from first match, or None."""
    for m in _AMOUNT_RE.finditer(text):
        code = m.group('code') or m.group('code2')
        amt_str = (m.group('amt') or m.group('amt2') or '').replace(',', '')
        if code and amt_str:
            try:
                return Decimal(amt_str), code.upper()
            except Exception:
                pass
    return None


def parse_message_evidence(msg: Message) -> MessageEvidence:
    """
    Parse a message into structured evidence.
    Rules are keyword-based and deterministic.
    No AI/LLM calls.
    """
    text = (msg.message_text or '').lower()
    src = msg.source_type

    # ---- Unrealized / portfolio gain ----
    if any(kw in text for kw in ['portfolio', 'market value', 'displayed value', 'no units have been sold',
                                  'unrealized', 'displayed market value']):
        return MessageEvidence(
            message_id=msg.message_id,
            source_type=src,
            evidence_type=MessageEvidenceType.UNREALIZED_GAIN,
            confidence='HIGH',
            raw_note='Portfolio value increase is non-cash; units not sold.',
        )

    # ---- Pending refund not yet credited ----
    if any(kw in text for kw in ['refund has been initiated', 'refund', 'not reached your account',
                                  'credit is completed', "refund hasn't"]):
        return MessageEvidence(
            message_id=msg.message_id,
            source_type=src,
            evidence_type=MessageEvidenceType.PENDING_REFUND_UNCONFIRMED,
            confidence='HIGH',
            raw_note='Refund initiated but not settled; do not count as available.',
        )

    # ---- Windfall/prize closed (settled, no recurring) ----
    if any(kw in text for kw in ['prize proceeds', 'claim is now closed', 'no further scheduled payments',
                                  'claim has been verified', 'prize claim']):
        ev = _extract_first_amount(msg.message_text or '')
        return MessageEvidence(
            message_id=msg.message_id,
            source_type=src,
            evidence_type=MessageEvidenceType.WINDFALL_CLOSED,
            confidence='HIGH',
            raw_note='Prize/windfall is a one-time settled event; no recurring payments.',
        )

    # ---- Pending payout unconfirmed (platform/service provider earnings not withdrawable) ----
    if any(kw in text for kw in ['payout is still pending', 'payout is pending',
                                  'balance isn\'t withdrawable', 'not withdrawable',
                                  'payout shows as completed']):
        return MessageEvidence(
            message_id=msg.message_id,
            source_type=src,
            evidence_type=MessageEvidenceType.PENDING_CREDIT_UNCONFIRMED,
            confidence='HIGH',
            raw_note='Payout pending; do not treat as available cash.',
        )

    # ---- Pending income unconfirmed (bonus, commission) ----
    if any(kw in text for kw in ['bonus', 'commission', 'not yet approved', 'not been approved',
                                  'performance review', 'jumlah akhir', 'pending result',
                                  'belum disetujui', 'still pending', "hasn't been approved"]):
        return MessageEvidence(
            message_id=msg.message_id,
            source_type=src,
            evidence_type=MessageEvidenceType.PENDING_INCOME_UNCONFIRMED,
            confidence='HIGH',
            raw_note='Bonus/commission not yet confirmed; do not count as income.',
        )

    # ---- Internal transfer (matching debit/credit same person) ----
    if any(kw in text for kw in ['transfer between your two accounts', 'internal transfer',
                                  'same account holder', 'both accounts are registered']):
        return MessageEvidence(
            message_id=msg.message_id,
            source_type=src,
            evidence_type=MessageEvidenceType.INTERNAL_TRANSFER,
            confidence='HIGH',
            raw_note='Matching debit+credit is internal; net cash impact = 0.',
        )

    # ---- Employer salary amendment ----
    if src == 'employer':
        # Check date in message
        date_match = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', msg.message_text or '')
        eff_dt = None
        if date_match:
            try:
                eff_dt = date.fromisoformat(date_match.group(1))
            except Exception:
                pass

        # Contract ended / employment ended
        if any(kw in text for kw in ['contract has ended', 'employment has ended', 'no off-season', 'seasonal contract has ended']):
            return MessageEvidence(
                message_id=msg.message_id,
                source_type=src,
                evidence_type=MessageEvidenceType.CONTRACT_TERMINATED,
                effective_date=eff_dt,
                confidence='HIGH',
                raw_note='Employment/contract ended. No future salary.',
            )

        ev = _extract_first_amount(msg.message_text or '')
        amount = None
        currency = None
        if ev:
            amount, currency = ev

        # Reduced/amended salary or increase
        if any(kw in text for kw in ['reduced to', 'temporary', 'adjusted', 'unpaid leave',
                                      'reduced', 'adjustment', 'temporary monthly pay',
                                      'gaji pokok yang dikonfirmasi', 'gaji rutin', 'naik menjadi', 'increased to']):
            return MessageEvidence(
                message_id=msg.message_id,
                source_type=src,
                evidence_type=MessageEvidenceType.SALARY_AMENDMENT,
                amount=amount,
                currency=currency,
                effective_date=eff_dt,
                confidence='HIGH',
                raw_note=f'Salary amended to {amount} {currency} effective {eff_dt}.',
            )
        # First salary confirmed or regular resumes
        if any(kw in text for kw in ['first salary', 'confirmed credit date', 'resumes on',
                                      'will be eur', 'will be inr', 'will be usd', 'will be zar', 'will be idr',
                                      'gaji pertama']):
            return MessageEvidence(
                message_id=msg.message_id,
                source_type=src,
                evidence_type=MessageEvidenceType.SALARY_CONFIRMED,
                amount=amount,
                currency=currency,
                effective_date=eff_dt,
                confidence='HIGH',
                raw_note=f'Salary confirmed = {amount} {currency} on {eff_dt}.',
            )
        # Regular confirmed payroll
        if any(kw in text for kw in ['gaji rutin', 'dikonfirmasi', 'confirmed', 'payroll', 'scheduled']):
            return MessageEvidence(
                message_id=msg.message_id,
                source_type=src,
                evidence_type=MessageEvidenceType.SALARY_CONFIRMED,
                amount=amount,
                currency=currency,
                effective_date=eff_dt,
                confidence='MEDIUM',
                raw_note=f'Payroll confirmed. Amount={amount} {currency} on {eff_dt}.',
            )

    # ---- Service provider rent amendment ----
    if src == 'service_provider':
        pct_match = _PCT_RE.search(msg.message_text or '')
        if pct_match and any(kw in text for kw in ['rent', 'lease', 'increases', 'new amount']):
            pct = Decimal(pct_match.group(1))
            return MessageEvidence(
                message_id=msg.message_id,
                source_type=src,
                evidence_type=MessageEvidenceType.RENT_AMENDMENT,
                percentage_change=pct,
                confidence='HIGH',
                raw_note=f'Rent increased by {pct}%.',
            )
        ev = _extract_first_amount(msg.message_text or '')
        if ev and any(kw in text for kw in ['rent', 'lease', 'maintenance']):
            return MessageEvidence(
                message_id=msg.message_id,
                source_type=src,
                evidence_type=MessageEvidenceType.RENT_AMENDMENT,
                amount=ev[0],
                currency=ev[1],
                confidence='MEDIUM',
                raw_note=f'Rent new amount = {ev[0]} {ev[1]}.',
            )

    return MessageEvidence(
        message_id=msg.message_id,
        source_type=src,
        evidence_type=MessageEvidenceType.UNKNOWN,
        confidence='LOW',
        raw_note='No specific evidence pattern matched.',
    )


def build_message_evidence_index(dataset: Dataset) -> Dict[str, List[MessageEvidence]]:
    """Build a user_id -> [MessageEvidence] index."""
    index: Dict[str, List[MessageEvidence]] = {}
    all_messages = [m for msgs in dataset.messages_by_user.values() for m in msgs]
    for msg in all_messages:
        ev = parse_message_evidence(msg)
        index.setdefault(msg.user_id, []).append(ev)
    return index
