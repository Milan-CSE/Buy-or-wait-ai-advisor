# Financial Statement Ingestion Specification

## 1. Overview & Architectural Goals

The statement ingestion engine is responsible for accepting unstructured or semi-structured user-provided CSV financial statements, validating them for security threats, parsing disparate bank dialects, normalizing fields to strict monetary and temporal invariants, deduplicating records, categorizing transactions deterministically, and presenting an interactive verification preview before committing trusted transactions into the database.

### Core Principles
1. **Zero Silent Guessing**: Ambiguous signs, dates, or column mappings must never enter the trusted ledger silently. Any row with conflicting or unresolvable information is flagged for user verification (`AMBIGUOUS`).
2. **Strict Monetary Invariance**: All parsed amounts use Python `Decimal` quantized to 4 decimal places (`0.0001`). IEEE 754 floating-point arithmetic is strictly prohibited throughout the parsing and storage pipeline.
3. **Security First**: Uploaded statements are treated as untrusted external payloads. They are validated against size limits, binary executable magic signatures, and path traversal vulnerabilities, and stored in a private quarantine location.
4. **Transparent Categorization**: Transactions are categorized using a deterministic regex rule set with explicit provenance reasons (e.g. `regex_match:starbucks`, `internal_transfer_rule`), avoiding non-deterministic LLM hallucination.
5. **Internal Transfer Isolation**: Transfers between a user's own accounts are explicitly detected and tagged as `non_cash` so they do not artificially inflate income or burn rates.

---

## 2. Ingestion State Machine

The lifecycle of an uploaded statement transitions through explicit, deterministic states:

```
[Upload Payload]
       │
       ▼
   UPLOADED
       │
       ▼ (validate size, MIME, magic bytes, sanitize filename, SHA-256)
   VALIDATING ─── (Security / File Type Error) ───► FAILED
       │
       ▼ (detect dialect, parse CSV rows, normalize, deduplicate)
     PARSED
       │
       ├──────────────────────────────────────────────┐
       │ (if ambiguous rows, duplicates, or errors)   │ (if 100% clean)
       ▼                                              ▼
  NEEDS_REVIEW                                     VERIFIED
       │                                              │
       ▼ (user resolves/overrides ambiguities)        │
   VERIFIED ◄─────────────────────────────────────────┘
       │
       ▼ (commit verified rows to PostgreSQL ledger)
   COMMITTED
```

---

## 3. Supported Formats & Dialects

The engine includes a robust heuristic `DialectDetector` and `CSVStatementParser` that sniffs delimiters and dynamically maps column headers:

| Dialect Shape | Example Headers | Handling Strategy |
|---|---|---|
| **Standard Amount** | `Date, Description, Amount` | Detects sign: negative = debit, positive = credit. Checks for embedded `DR`/`CR` indicators. |
| **Separate Debit/Credit** | `Date, Narration, Withdrawal, Deposit, Balance` | Assigns `-abs(withdrawal)` to debits and `+abs(deposit)` to credits. Flags as `AMBIGUOUS` if both are populated. |
| **Signed Prefix** | `Posting Date, Details, Transaction Amount` | Parses explicit `+` or `-` prefixes. Handles accounting parentheses `(1,234.56)` as negative. |
| **Inverted Sign (Credit Card)** | `Date, Description, Amount` | Configurable `sign_convention='inverted'`: inverts charges to negative debits and payments to positive credits. |
| **Formatted Currency & Commas** | `Date, Description, Amount` | Strips currency symbols (`$`, `€`, `£`, `₹`, `¥`), spaces, and thousands commas. |
| **Multiline & Quoted Fields** | `Date, Description, Amount` | Standards-compliant CSV tokenizer handles quoted multiline merchant addresses and memo fields. |

### Supported Date Formats
- ISO 8601: `YYYY-MM-DD`, `YYYY/MM/DD`
- Commonwealth / European / Indian: `DD/MM/YYYY`, `DD-MM-YYYY`, `DD.MM.YYYY`
- US Format: `MM/DD/YYYY`
- Alphanumeric Month: `DD-Mon-YYYY` (e.g. `15-Sep-2026`)

---

## 4. Normalization Rules

1. **Amount Normalization**:
   - Currency symbols (`$`, `€`, `£`, `₹`, `¥`) and whitespace are stripped.
   - Thousands separators (`,`) are removed.
   - Values enclosed in parentheses `(500.00)` are parsed as negative numbers `-500.0000`.
   - All parsed amounts are instantiated as `Decimal` and quantized to 4 decimal places.
2. **Sign Resolution**:
   - Debit: `amount = -abs(debit_val)`, `direction = "debit"`
   - Credit: `amount = +abs(credit_val)`, `direction = "credit"`
   - If both debit and credit columns contain non-zero numbers: marked `AMBIGUOUS` (`"Row has both Debit and Credit amounts populated"`).
   - If neither debit nor credit is populated: marked `REJECTED` (`"Both Debit and Credit fields are empty"`).
3. **Description Normalization**:
   - Strips extraneous internal spaces and newline breaks.
   - Removes transient point-of-sale terminal IDs or sequence tokens (e.g., `REF# 123456`, `TRX ID 889`).
   - Retains exact `original_description` for auditability.

---

## 5. Deduplication Strategy

The deduplicator enforces two tiers of duplicate defense:

### A. File-Level Deduplication
- Calculates the SHA-256 hash of the entire file byte content upon upload.
- Checks `import_batches` for any previously processed or committed batch belonging to the user with the same hash.
- If found, rejects upload with `DuplicateFileError` to prevent duplicate ledger processing.

### B. Transaction-Level Deduplication
- Computes a deterministic SHA-256 hash for every transaction:
  $$\text{dedup\_hash} = \text{SHA-256}(\text{user\_id} : \text{account\_id} : \text{date} : \text{amount} : \text{normalized\_description})$$
- When an external transaction ID exists in the statement, uses `SHA-256(user_id : external_id)`.
- Checks against in-batch seen hashes and queries existing records in the `transactions` table.
- Duplicate rows are flagged with `verification_status = "duplicate"` and excluded from being committed.

---

## 6. Categorization & Internal Transfers

### Deterministic Rule-Based Categorization
Categorization uses transparent regex pattern matching. Each assigned category includes an audit reason:

| Category | Regex / Keywords | Match Reason Example |
|---|---|---|
| `salary` | `salary`, `payroll`, `direct dep`, `wages`, `stipend` | `regex_match:direct dep` |
| `rent` | `rent`, `lease`, `landlord`, `apartment`, `property mgmt` | `regex_match:rent` |
| `groceries` | `supermarket`, `grocery`, `walmart`, `kroger`, `whole foods`, `trader joe`, `costco` | `regex_match:whole foods` |
| `utilities` | `electric`, `water`, `gas bill`, `internet`, `broadband`, `mobile`, `utility`, `verizon` | `regex_match:electric` |
| `transport` | `uber`, `lyft`, `fuel`, `gas station`, `metro`, `subway`, `transit`, `train`, `parking`, `shell` | `regex_match:metro` |
| `dining` | `restaurant`, `cafe`, `coffee`, `starbucks`, `mcdonald`, `burger`, `uber eats`, `doordash` | `regex_match:starbucks` |
| `shopping` | `amazon`, `target`, `ebay`, `clothing`, `retail`, `zara`, `best buy`, `apple store` | `regex_match:amazon` |
| `entertainment`| `netflix`, `spotify`, `cinema`, `movie`, `hulu`, `steam`, `playstation`, `disney` | `regex_match:netflix` |
| `healthcare` | `pharmacy`, `doctor`, `hospital`, `clinic`, `dental`, `cvs`, `walgreens`, `medical` | `regex_match:pharmacy` |
| `debt` | `loan`, `mortgage`, `interest charge`, `credit card payment` | `regex_match:loan` |
| `cash_withdrawal`| `atm`, `cash withdrawal`, `cash out` | `regex_match:atm` |
| `other` | Fallback when no pattern matches | `unmatched_fallback` |

### Internal Transfer Detection
- Inspects user's registered account names and transaction text.
- Matches transfer keywords: `Transfer to Savings`, `Transfer from Checking`, `Internal Transfer`, `Self Transfer`.
- When detected:
  - Sets `is_internal_transfer = True`
  - Sets `category = "transfer"`
  - Sets `cash_type = "non_cash"` (ensures cash-flow solver does not treat transfers as income or new burn).

---

## 7. Security Controls

1. **File Size Enforcement**: Hard limit of 10 MB (`MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024`). Files exceeding this size raise `FileOversizedError`.
2. **File Extension Whitelist**: Only `.csv`, `.txt`, and `.tsv` files are permitted.
3. **Binary & Executable Defense**: Rejects files beginning with binary magic numbers:
   - Windows PE (`MZ`)
   - Linux ELF (`\x7fELF`)
   - Java class / Mach-O (`\xca\xfe\xba\xbe`, `\xfe\xed\xfa\xce`)
   - Archives (`PK\x03\x04`, `Rar!`, `\x1f\x8b\x08`, `7z`)
   - PDFs (`%PDF-`)
4. **Null Byte Neutralization**: Rejects files containing `\x00` characters.
5. **Path Traversal Defense**: `sanitize_filename()` strips directories (`../`, `..\`), converts separators, and limits names to alphanumeric basenames.
6. **Isolated Quarantine Storage**: Uploaded files are written to `backend/ingestion/quarantine/<user_id>/<random_uuid>.raw` with strict path assertions.
7. **Zero Logged Sensitive Data**: Raw financial records, full statements, and account numbers are never logged to console or log files.

---

## 8. Deferred Formats & Future Integrations

- **OFX / QFX Parsing**: Deferred to future milestones to avoid unnecessary SGML parsing complexity for MVP.
- **Direct Bank APIs / Aggregators**: Open Banking, Plaid, and Yodlee integrations are deferred; users retain control via statement exports.
- **LLM-Based Categorization**: Deferred. The current system uses transparent, verifiable rule-based categorization.
