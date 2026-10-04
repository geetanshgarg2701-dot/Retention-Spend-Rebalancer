"""Check AI-written text against the facts the code calculated.

The AI writes words and never calculates a figure. Every number in its text must match a
number in the facts it was given, in a recognized format. Spelled numbers and overclaiming
language are flagged too. The checker needs no AI, so it is tested by hand.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

# A number, with an optional percent sign or the word percent after it, so 33.4%, 33.4 percent and 33.4 per cent
# are all checked as percentages and a bare 33.4 is checked as a plain number.
_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?(?:%|\s*(?:percent|per cent)\b)?", re.IGNORECASE)
_DIGITS = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
# Numbers spelled out as words. "one" is left out, because it is ordinary English in phrases like "one channel".
SPELLED = {
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "twenty", "thirty",
    "forty", "fifty", "hundred", "thousand", "million", "half", "double", "twice", "triple", "quarter", "dozen",
    "third", "thirds", "fourth", "fifth", "tenth",
}
OVERCLAIMS = (
    "will increase", "will grow", "will rise", "will double", "will pay back", "will earn", "guarantee", "guaranteed",
    "proven", "proves", "prove that", "certainly", "definitely", "for sure", "without doubt", "no risk", "risk free",
)


def _canon(token: str) -> str | None:
    """The number inside a token as a canonical string, or None. Sign, commas, percent signs and the word percent
    are ignored here, and is_percent says whether the token was written as a percentage."""
    match = _DIGITS.match(token)
    if not match:
        return None
    try:
        return format(Decimal(match.group(0).replace(",", "").lstrip("-")).normalize(), "f")
    except InvalidOperation:
        return None


def _is_percent(token: str) -> bool:
    return token.rstrip().endswith("%") or token.lower().rstrip().endswith(("percent", "per cent"))


def _plain_variants(value: float) -> set[str]:
    """A fact as it was given, and rounded to 0, 1 or 2 places."""
    value = abs(float(value))
    out = {format(Decimal(str(value)).normalize(), "f")}
    for digits in (0, 1, 2):
        out.add(format(Decimal(str(round(value, digits))).normalize(), "f"))
    return out


def _share_variants(value: float) -> set[str]:
    """A share between 0 and 1 written as a percentage. Only a number written with a percent sign may use these."""
    value = abs(float(value))
    if value > 1:
        return set()
    return {format(Decimal(str(round(value * 100, digits))).normalize(), "f") for digits in (0, 1, 2)}


def allowed_sets(facts: Any) -> tuple[set[str], set[str]]:
    """The numbers the text may use. Plain numbers must match a fact as given or rounded. A number written as a
    percentage may also match a share multiplied by 100. Numbers inside text facts, such as labels and months, count as plain."""
    plain: set[str] = set()
    shares: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, (int, float)):
            plain.update(_plain_variants(node))
            shares.update(_share_variants(node))
        elif isinstance(node, str):
            for token in _NUMBER.findall(node):
                canon = _canon(token)
                if canon is not None:
                    plain.add(canon)
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(key)
                walk(value)
        elif isinstance(node, (list, tuple, set)):
            for item in node:
                walk(item)

    walk(facts)
    return plain, plain | shares


def allowed_numbers(facts: Any) -> set[str]:
    """Every number that may appear in some form, plain or as a percentage."""
    return allowed_sets(facts)[1]


@dataclass
class CheckResult:
    ok: bool
    bad_numbers: list[str] = field(default_factory=list)
    spelled: list[str] = field(default_factory=list)
    overclaims: list[str] = field(default_factory=list)
    too_long: bool = False

    def reason(self) -> str:
        parts = []
        if self.bad_numbers:
            parts.append("figures that are not in your results: " + ", ".join(self.bad_numbers))
        if self.spelled:
            parts.append("spelled-out numbers: " + ", ".join(self.spelled))
        if self.overclaims:
            parts.append("claims that are too certain: " + ", ".join(self.overclaims))
        if self.too_long:
            parts.append("text that is too long")
        return "; ".join(parts)


def check_text(text: str, facts: Any, max_words: int | None = None) -> CheckResult:
    """Check one piece of text. ok is False if it has a figure that is not in facts, a spelled number,
    an overclaim, or more than max_words words."""
    plain, percent = allowed_sets(facts)
    bad, seen = [], set()
    for token in _NUMBER.findall(text):
        token = token.strip()
        canon = _canon(token)
        allowed = percent if _is_percent(token) else plain
        if canon is not None and canon not in allowed and token not in seen:
            bad.append(token)
            seen.add(token)
    lowered = text.lower()
    words = set(re.findall(r"[a-z]+", lowered))
    spelled = sorted(words & SPELLED)
    overclaims = [phrase for phrase in OVERCLAIMS if phrase in lowered]
    too_long = max_words is not None and len(text.split()) > max_words
    return CheckResult(not (bad or spelled or overclaims or too_long), bad, spelled, overclaims, too_long)


def check_all(texts: Iterable[str], facts: Any, max_words: int | None = None) -> list[CheckResult]:
    return [check_text(t, facts, max_words) for t in texts]
