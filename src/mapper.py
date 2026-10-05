"""Match the columns of an order export to the canonical fields.

A rule-based mapper always runs. An AI mapper is optional and only ever sees
column headers plus a few masked sample values. The user confirms the final
mapping before anything else runs.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, replace
from typing import Callable, Optional

import numpy as np
import pandas as pd

from src.parsing import nonblank, to_number

REQUIRED_FIELDS = ("customer_id", "order_date", "order_value")
OPTIONAL_FIELDS = ("order_id", "order_status", "quantity")
FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

FIELD_LABELS = {
    "customer_id": "Customer id",
    "order_date": "Order date",
    "order_value": "Order value",
    "order_id": "Order id",
    "order_status": "Order status",
    "quantity": "Quantity",
}

FIELD_HELP = {
    "customer_id": "Who placed the order. An id or an email address works.",
    "order_date": "When the order was placed.",
    "order_value": "The money amount of the order, or of one unit when a quantity column is also mapped.",
    "order_id": "Groups lines that belong to one order. Leave empty if each row is one order.",
    "order_status": "Used to drop refunded, voided and cancelled orders.",
    "quantity": "Units on the line. Only used when the order value is a unit price.",
}

REQUIRED_MIN_SCORE = 0.38
OPTIONAL_MIN_SCORE = 0.5
HIGH_CONFIDENCE = 0.8
MEDIUM_CONFIDENCE = 0.55
SAMPLE_SIZE = 500
AI_SAMPLES_PER_COLUMN = 3
AI_MAX_VALUE_LENGTH = 40
EMAIL_PLACEHOLDER = "<email>"
NUMBER_PLACEHOLDER = "<number>"
AI_MIN_NUMBER_DIGITS = 10
AI_PERSONAL_TOKENS = (
    "name", "first", "last", "surname", "phone", "mobile", "tel", "telephone", "cell",
    "address", "street", "city", "zip", "postal", "postcode", "province", "state",
    "company", "note", "comment", "message", "ip",
)

# A trailing "!" marks a synonym that only counts as an exact match.
SYNONYMS: dict[str, list[str]] = {
    "customer_id": [
        "customer id", "customer", "customer email", "customer number", "client id",
        "user id", "buyer id", "shopper id", "member id", "account id", "cust id",
        "billing email", "email address", "email",
    ],
    "order_date": [
        "order date", "invoice date", "purchase date", "transaction date", "created at",
        "date created", "created date", "order created", "order placed", "placed at",
        "ordered at", "sale date", "order time", "timestamp", "date",
    ],
    "order_value": [
        "order total", "order value", "order amount", "order revenue", "total amount",
        "grand total", "total price", "total sales", "net sales", "gross sales",
        "line total", "line amount", "net amount", "amount paid", "payment amount",
        "unit price", "item price", "total", "amount", "revenue", "sales", "price",
        "subtotal",
    ],
    "order_id": [
        "order id", "order number", "order no", "order ref", "order reference",
        "invoice no", "invoice number", "invoice id", "transaction id",
        "transaction number", "receipt number", "invoice", "id!",
    ],
    "order_status": [
        "order status", "financial status", "payment status", "order state",
        "transaction status", "status",
    ],
    "quantity": [
        "quantity", "qty", "quantity ordered", "units sold", "units", "item count",
        "number of items", "items",
    ],
}

# A header with one of these words never matches the field. Short words must
# match a whole word, longer ones match as a prefix so plurals and tenses work.
NEGATIVE_TOKENS: dict[str, list[str]] = {
    "customer_id": [
        "name", "first", "last", "phone", "mobile", "tax", "shipping", "discount",
        "quantity", "qty", "address", "city", "state", "country", "zip", "postal",
        "date", "time", "total", "price", "amount", "status", "note", "group", "type",
        "tag", "segment", "since", "created", "count", "marketing", "subscribed",
        "consent", "order", "product", "sku",
    ],
    "order_date": [
        "ship", "deliver", "birth", "dob", "updat", "modif", "cancel", "refund",
        "fulfil", "due", "expir", "closed", "paid", "customer", "signup", "registered",
    ],
    "order_value": [
        "shipping", "tax", "discount", "quantity", "qty", "refund", "fee", "tip", "id",
        "name", "count", "number", "no", "weight", "currency", "code", "method", "date",
        "status", "sku", "cost", "item", "lineitem", "phone", "zip", "postal",
    ],
    "order_id": [
        "customer", "cust", "user", "product", "sku", "stock", "date", "total",
        "subtotal", "status", "amount", "price", "shipping", "tax", "discount",
        "quantity", "qty", "currency", "note", "source", "channel", "type", "count",
        "lineitem", "item", "billing", "phone", "name",
    ],
    "order_status": ["fulfil", "shipping", "delivery", "marketing", "subscri", "date"],
    "quantity": [
        "price", "total", "amount", "cost", "discount", "refund", "return", "available",
        "stock", "weight", "fulfillable", "date", "id",
    ],
}

_DATE_LIKE = re.compile(
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"
    r"|\d{1,2}\s*[A-Za-z]{3,9}\.?,?\s*\d{2,4}"
    r"|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{2,4}"
)
_LONG_INT = re.compile(r"\d{6,}")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_NUMBER_SHAPE = re.compile(r"\+?[\d\s().\-]+")

_PRICE_WORDS = ("unit", "price", "rate")
_TOTAL_WORDS = ("total", "amount", "revenue", "sales", "subtotal", "value")


@dataclass
class FieldMatch:
    field: str
    header: Optional[str]
    score: float = 0.0
    confidence: str = "none"  # high, medium, low or none
    reason: str = ""
    source: str = "rules"  # rules, ai or both
    alternative: Optional[str] = None  # a header the other method preferred


@dataclass
class MappingResult:
    matches: dict[str, FieldMatch]
    multiply_quantity: bool = False
    warnings: list[str] = field(default_factory=list)
    ai_used: bool = False

    def mapping(self) -> dict[str, str]:
        """Field to header, only for fields that have one."""
        return {f: m.header for f, m in self.matches.items() if m.header}

    def missing_required(self) -> list[str]:
        return [f for f in REQUIRED_FIELDS if not self.matches[f].header]


# ---------------------------------------------------------------- rule scoring

def _normalize(header: object) -> str:
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(header))
    return re.sub(r"[^A-Za-z0-9]+", " ", text).lower().strip()


def _compact(text: str) -> str:
    return text.replace(" ", "")


def _blocked(field_name: str, tokens: list[str]) -> bool:
    for neg in NEGATIVE_TOKENS[field_name]:
        for tok in tokens:
            if (len(neg) <= 3 and tok == neg) or (len(neg) > 3 and tok.startswith(neg)):
                return True
    return False


def _name_score(field_name: str, header: object) -> tuple[float, str, int]:
    """Return the name score, how it matched, and the rank of the matching synonym."""
    norm = _normalize(header)
    tokens = norm.split()
    comp = _compact(norm)
    if not comp or _blocked(field_name, tokens):
        return 0.0, "none", 999
    best, kind, rank = 0.0, "none", 999
    for i, syn in enumerate(SYNONYMS[field_name]):
        exact_only = syn.endswith("!")
        sc = _compact(syn.rstrip("!"))
        if comp == sc:
            s, k = 1.0, "exact"
        elif exact_only:
            continue
        elif len(sc) >= 4 and sc in comp:
            s, k = 0.75, "contains"
        elif len(comp) >= 4 and comp in sc:
            s, k = 0.5, "contained"
        else:
            continue
        if s > best:
            best, kind, rank = s, k, i
    return best, kind, rank


# --------------------------------------------------------------- content scoring

def _sample(series: pd.Series, n: int = SAMPLE_SIZE) -> pd.Series:
    values = nonblank(series)
    if len(values) > n:
        values = values.iloc[np.linspace(0, len(values) - 1, n).astype(int)]
    return values.reset_index(drop=True)


def _content_date(series: pd.Series) -> tuple[float, str]:
    s = _sample(series)
    if s.empty:
        return 0.0, "The column is empty."
    share = float(s.map(lambda v: bool(_DATE_LIKE.search(v))).mean())
    return share, f"{share:.0%} of sampled values look like dates."


def _content_value(series: pd.Series) -> tuple[float, str]:
    s = _sample(series)
    if s.empty:
        return 0.0, "The column is empty."
    share = float(to_number(s).notna().mean())
    note = f"{share:.0%} of sampled values read as money amounts."
    long_ints = float(s.map(lambda v: bool(_LONG_INT.fullmatch(v))).mean())
    if long_ints >= 0.9 and s.nunique() / len(s) >= 0.9:
        return share * 0.2, note + " The values look like long unique ids, so the score was lowered."
    return share, note


def _content_customer(series: pd.Series) -> tuple[float, str]:
    head = series.head(5000)
    s = _sample(series)
    if len(head) == 0 or s.empty:
        return 0.0, "The column is empty."
    fill = len(nonblank(head)) / len(head)
    note = f"{fill:.0%} of rows are filled."
    if len(s) >= 20 and s.nunique() == len(s):
        return fill * 0.6, note + " Every sampled value is unique, so the score was lowered."
    return fill, note


def _content_order_id(series: pd.Series) -> tuple[float, str]:
    head = series.head(5000)
    s = _sample(series)
    if len(head) == 0 or s.empty:
        return 0.0, "The column is empty."
    fill = len(nonblank(head)) / len(head)
    uniq = s.nunique() / len(s)
    return uniq * fill, f"{uniq:.0%} of sampled values are unique."


def _content_status(series: pd.Series) -> tuple[float, str]:
    s = _sample(series)
    if s.empty:
        return 0.0, "The column is empty."
    numeric = float(to_number(s).notna().mean())
    dated = float(s.map(lambda v: bool(_DATE_LIKE.search(v))).mean())
    if numeric > 0.2 or dated > 0.2:
        return 0.0, "The values look like numbers or dates, not status words."
    distinct = s.str.lower().nunique()
    if distinct <= 8:
        return 1.0, "The column holds a short list of repeated text values."
    if distinct >= 30:
        return 0.0, "The column has too many distinct values to be a status."
    return (30 - distinct) / 22, "The column holds a fairly short list of text values."


def _content_quantity(series: pd.Series) -> tuple[float, str]:
    s = _sample(series)
    if s.empty:
        return 0.0, "The column is empty."
    nums = to_number(s)
    whole = nums.notna() & (nums > 0) & (nums == nums.round()) & (nums <= 100000)
    share = float(whole.mean())
    return share, f"{share:.0%} of sampled values are whole numbers."


_CONTENT = {
    "order_date": _content_date,
    "order_value": _content_value,
    "customer_id": _content_customer,
    "order_id": _content_order_id,
    "order_status": _content_status,
    "quantity": _content_quantity,
}


@dataclass
class _Candidate:
    field: str
    header: str
    col_index: int
    name: float
    name_kind: str
    syn_rank: int
    content: float
    content_note: str
    total: float


def _confidence(score: float) -> str:
    if score >= HIGH_CONFIDENCE:
        return "high"
    if score >= MEDIUM_CONFIDENCE:
        return "medium"
    return "low"


def _reason(c: _Candidate) -> str:
    label = FIELD_LABELS[c.field].lower()
    if c.name_kind == "exact":
        lead = f'The header "{c.header}" is a common name for {label}.'
    elif c.name_kind == "contains":
        lead = f'The header "{c.header}" contains a common name for {label}.'
    elif c.name_kind == "contained":
        lead = f'The header "{c.header}" resembles a common name for {label}.'
    else:
        lead = f'The header "{c.header}" gave no clue, so this match uses the values only.'
    return f"{lead} {c.content_note}"


def _looks_like_unit_price(header: str) -> bool:
    tokens = _normalize(header).split()
    has_price = any(t.startswith(w) for t in tokens for w in _PRICE_WORDS)
    has_total = any(t.startswith(w) for t in tokens for w in _TOTAL_WORDS)
    return has_price and not has_total


def _quantity_note(matches: dict[str, FieldMatch]) -> tuple[bool, list[str]]:
    qty, val = matches["quantity"].header, matches["order_value"].header
    if not qty or not val:
        return False, []
    if _looks_like_unit_price(val):
        return True, [
            f'"{val}" looks like a unit price, which would mean each line value is "{qty}" times "{val}". '
            "Check the example on this screen before you choose."
        ]
    return False, [
        f'"{qty}" is mapped but "{val}" looks like an order total, so quantity will not be multiplied. '
        "Turn multiplying on if the order value is a unit price."
    ]


def rule_based_map(df: pd.DataFrame) -> MappingResult:
    """Score every header against every field and assign the best matches."""
    headers = [str(c) for c in df.columns]
    candidates: list[_Candidate] = []
    for ci, header in enumerate(headers):
        series = df.iloc[:, ci]
        for f in FIELDS:
            name, kind, rank = _name_score(f, header)
            if f == "customer_id" and name == 0.0:
                continue  # never assign a customer on content alone
            if name == 0.0 and _blocked(f, _normalize(header).split()):
                continue
            content, note = _CONTENT[f](series)
            total = 0.6 * name + 0.4 * content
            if total > 0:
                candidates.append(_Candidate(f, header, ci, name, kind, rank, content, note, total))

    candidates.sort(key=lambda c: (-round(c.total, 6), c.syn_rank, c.col_index))
    chosen: dict[str, _Candidate] = {}
    used: set[int] = set()
    for c in candidates:
        if c.field in chosen or c.col_index in used:
            continue
        minimum = REQUIRED_MIN_SCORE if c.field in REQUIRED_FIELDS else OPTIONAL_MIN_SCORE
        if c.total < minimum:
            continue
        chosen[c.field] = c
        used.add(c.col_index)

    matches: dict[str, FieldMatch] = {}
    for f in FIELDS:
        c = chosen.get(f)
        if c:
            matches[f] = FieldMatch(f, c.header, round(c.total, 3), _confidence(c.total), _reason(c))
        else:
            matches[f] = FieldMatch(f, None, 0.0, "none", f"No column looked like {FIELD_LABELS[f].lower()}.")
    multiply, notes = _quantity_note(matches)
    return MappingResult(matches, multiply, notes)


# -------------------------------------------------------------------- AI mapper

AIFunction = Callable[[str], str]


def mask_value(value: object) -> str:
    """Replace emails and phone-like or long numbers with placeholders and cut long values short."""
    text = _EMAIL.sub(EMAIL_PLACEHOLDER, str(value).strip())
    digits = sum(ch.isdigit() for ch in text)
    if digits >= AI_MIN_NUMBER_DIGITS and _NUMBER_SHAPE.fullmatch(text) and not _DATE_LIKE.search(text):
        return NUMBER_PLACEHOLDER
    if len(text) > AI_MAX_VALUE_LENGTH:
        text = text[:AI_MAX_VALUE_LENGTH] + "..."
    return text


def is_personal_header(header: object) -> bool:
    """Headers that look like names, phones, addresses or free text send no sample values."""
    tokens = _normalize(header).split()
    if any(t.startswith(("product", "item", "lineitem", "sku")) for t in tokens):
        return False
    return any(t == p or (len(p) > 3 and t.startswith(p)) for t in tokens for p in AI_PERSONAL_TOKENS)


def build_ai_payload(df: pd.DataFrame) -> dict[str, list[str]]:
    """Headers with up to three masked sample values each. Nothing else leaves the app.

    Columns whose header looks personal send the header only.
    """
    payload: dict[str, list[str]] = {}
    for ci, header in enumerate(df.columns):
        if is_personal_header(header):
            payload[str(header)] = []
            continue
        masked = nonblank(df.iloc[:, ci]).head(200).map(mask_value)
        payload[str(header)] = list(masked.drop_duplicates().head(AI_SAMPLES_PER_COLUMN))
    return payload


def build_ai_prompt(payload: dict[str, list[str]]) -> str:
    field_lines = "\n".join(f"- {f}: {FIELD_HELP[f]}" for f in FIELDS)
    return (
        "You match columns of an online store order export to fixed fields.\n"
        "Fields:\n"
        f"{field_lines}\n\n"
        "Rules: use each header at most once. Use null when no header fits. "
        "Copy headers exactly as given. Answer with a single JSON object and nothing else, "
        "with one key per field and a header string or null as the value.\n\n"
        "Columns and masked sample values as JSON:\n"
        f"{json.dumps(payload, ensure_ascii=True)}"
    )


def parse_ai_response(text: object, headers: list[str]) -> Optional[dict[str, Optional[str]]]:
    """Strict parse. Return None on anything unexpected so the caller falls back to rules."""
    if not isinstance(text, str):
        return None
    body = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", body, flags=re.S)
    if fenced:
        body = fenced.group(1)
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    known = set(headers)
    result: dict[str, Optional[str]] = {}
    seen: set[str] = set()
    for f in FIELDS:
        value = data.get(f)
        if value is None:
            result[f] = None
            continue
        if not isinstance(value, str) or value not in known or value in seen:
            return None
        seen.add(value)
        result[f] = value
    return result


def ai_suggest(df: pd.DataFrame, ai_fn: AIFunction) -> Optional[dict[str, Optional[str]]]:
    headers = [str(c) for c in df.columns]
    try:
        reply = ai_fn(build_ai_prompt(build_ai_payload(df)))
    except Exception:
        return None
    return parse_ai_response(reply, headers)


def gemini_ai_function(json_mode: bool = True) -> Optional[AIFunction]:
    """Build the real model call, or return None when no key or model is configured.

    The key and model come from src.aiconfig, which reads the environment, a local .env file or
    Streamlit secrets. json_mode asks for a JSON reply, and False asks for plain text.
    """
    from src.aiconfig import get_settings

    key, model = get_settings()
    if not key or not model:
        return None
    try:
        from google import genai
    except ImportError:
        return None
    client = genai.Client(api_key=key)
    config = {"temperature": 0}
    if json_mode:
        config["response_mime_type"] = "application/json"

    def call(prompt: str) -> str:
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        return response.text

    return call


def merge_with_ai(rules: MappingResult, ai: dict[str, Optional[str]]) -> MappingResult:
    """Combine rule matches with an AI suggestion. The user still confirms."""
    matches = {f: replace(m) for f, m in rules.matches.items()}
    used = {m.header for m in matches.values() if m.header}
    for f in FIELDS:
        m, suggested = matches[f], ai.get(f)
        if suggested is None:
            if m.header:
                m.reason += " The AI did not suggest a column for this field."
            continue
        if m.header == suggested:
            m.confidence, m.source = "high", "both"
            m.reason += " The AI suggestion agrees."
        elif m.header:
            m.confidence, m.alternative = "low", suggested
            m.reason += f' The AI preferred "{suggested}" instead. Check this one.'
        elif suggested in used:
            m.alternative = suggested
            m.reason = f'The AI suggested "{suggested}", but another field already uses it. Check this one.'
        else:
            matches[f] = FieldMatch(
                f, suggested, 0.0, "low",
                f'Only the AI suggested "{suggested}". Check this one.', source="ai",
            )
            used.add(suggested)
    multiply, notes = _quantity_note(matches)
    return MappingResult(matches, multiply, notes, ai_used=True)


def map_columns(df: pd.DataFrame, ai_fn: Optional[AIFunction] = None) -> MappingResult:
    """Run the rules, then optionally merge an AI suggestion. Failures fall back to rules."""
    result = rule_based_map(df)
    if ai_fn is None:
        return result
    suggestion = ai_suggest(df, ai_fn)
    if suggestion is None:
        result.warnings.insert(
            0, "AI matching returned nothing usable, so these matches come from the rules only."
        )
        return result
    merged = merge_with_ai(result, suggestion)
    disagreements = [FIELD_LABELS[f] for f, m in merged.matches.items() if m.alternative]
    if disagreements:
        merged.warnings.insert(
            0, "The AI and the rules disagree on: " + ", ".join(disagreements) + ". Check these before you continue."
        )
    return merged
