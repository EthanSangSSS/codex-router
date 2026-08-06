from __future__ import annotations

from collections import Counter
from math import isfinite, log2
import re
from typing import Any, Mapping
import unicodedata

from .types import SecurityResult


FAILURE_SUMMARY_OMITTED = "stage failed; sensitive details omitted"
_MAX_FAILURE_SUMMARY_CHARS = 500
_MAX_FAILURE_SUMMARY_BYTES = 2000

_PROTECTED_PATTERNS = (
    re.compile(r"(?i)\b(?:authorization|proxy-authorization)\s*:\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:cookie|set-cookie)\s*:\s*\S+"),
    re.compile(
        r"(?i)(?:[\"']?(?:password|passwd|pwd|token|secret|api[_-]?key|"
        r"client[_-]?secret|access[_-]?key|session(?:id|token)?|cookie)[\"']?)"
        r"\s*[:=]\s*[^\s,;}]+"
    ),
    re.compile(
        r"(?im)^\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*"
        r"(?:KEY|TOKEN|SECRET|PASSWORD|COOKIE|SESSION|CREDENTIAL)"
        r"[A-Za-z0-9_]*\s*="
    ),
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?(?:PRIVATE|SIGNING) KEY-----"),
    re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?<![A-Za-z0-9])gh(?:p|o|u|s|r)_[A-Za-z0-9]{8,}"),
    re.compile(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{8,}"),
    re.compile(r"(?<![A-Z0-9])AKIA[A-Z0-9]{16}(?![A-Z0-9])"),
    re.compile(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{8,}"),
    re.compile(r"(?<![A-Za-z0-9])AIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?:^|\s)/(?:Users|home|private|tmp|var/folders)/[^\s]+"),
    re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
               r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
               r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+\b"),
)
_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?(?:PRIVATE|SIGNING) KEY-----", re.IGNORECASE
)
_SECRET_FIELD = re.compile(
    r"(?:password|passwd|pwd|token|secret|api[_-]?key|client[_-]?secret|"
    r"access[_-]?key|session(?:[_-]?(?:id|token))?|cookie|authorization|"
    r"credentials?)",
    re.IGNORECASE,
)
_HIGH_RISK_SECRET_FIELD = re.compile(
    r"(?:private|signing)[_-]?key", re.IGNORECASE
)
_ACCOUNT_FIELD = re.compile(
    r"(?:e[-_]?mail|account(?:[_-]?id)?|user[_-]?id)", re.IGNORECASE
)
_HIGH_ENTROPY_CANDIDATE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/=_-]{40,}(?![A-Za-z0-9])")
_REDACTION_TOKEN = re.compile(r"\[REDACTED:[a-z0-9_]+\]")
_MAX_DEPTH = 12
_MAX_FIELDS = 2048
_MAX_CHARS = 1024 * 1024
_MAX_BYTES = 4 * 1024 * 1024

_REDACTABLE_PATTERNS = (
    (
        "authorization",
        re.compile(
            r"(?im)\b(?:authorization|proxy-authorization)\s*:\s*[^\r\n]+"
        ),
    ),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")),
    ("cookie", re.compile(r"(?im)\b(?:cookie|set-cookie)\s*:\s*[^\r\n]+")),
    (
        "environment_assignment",
        re.compile(
            r"(?im)^\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*"
            r"(?:KEY|TOKEN|SECRET|PASSWORD|COOKIE|SESSION|CREDENTIAL)"
            r"[A-Za-z0-9_]*\s*=\s*[^\r\n]*"
        ),
    ),
    (
        "session_identifier",
        re.compile(
            r"(?i)(?:[\"']?session(?:[_-]?(?:id|token))?[\"']?)"
            r"\s*[:=]\s*[^\s,;}]+"
        ),
    ),
    (
        "secret_assignment",
        re.compile(
            r"(?i)(?:[\"']?(?:password|passwd|pwd|token|secret|api[_-]?key|"
            r"client[_-]?secret|access[_-]?key|session(?:[_-]?(?:id|token))?|"
            r"cookie)[\"']?)\s*[:=]\s*[^\s,;}]+"
        ),
    ),
    (
        "provider_token",
        re.compile(
            r"(?<![A-Za-z0-9])(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{8,}|"
            r"gh(?:p|o|u|s|r)_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}|"
            r"AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{8,}|"
            r"AIza[A-Za-z0-9_-]{20,})(?![A-Za-z0-9])"
        ),
    ),
    (
        "private_path",
        re.compile(r"(?:^|(?<=\s))/(?:Users|home|private|tmp|var/folders)/[^\s]+"),
    ),
    (
        "account_identifier",
        re.compile(
            r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
            r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+\b"
        ),
    ),
)


class _SecurityBlock(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class _ScanContext:
    def __init__(self, *, redact: bool) -> None:
        self.redact = redact
        self.counts: Counter[str] = Counter()
        self.fields = 0
        self.characters = 0
        self.bytes = 0
        self.active_containers: set[int] = set()

    def count_text(self, value: str) -> None:
        self.characters += len(value)
        try:
            self.bytes += len(value.encode("utf-8", errors="strict"))
        except UnicodeEncodeError as error:
            raise _SecurityBlock("invalid_unicode") from error
        if self.characters > _MAX_CHARS or self.bytes > _MAX_BYTES:
            raise _SecurityBlock("input_limit")

    def count_field(self) -> None:
        self.fields += 1
        if self.fields > _MAX_FIELDS:
            raise _SecurityBlock("input_limit")


def _replacement(category: str) -> str:
    return f"[REDACTED:{category}]"


def _entropy(value: str) -> float:
    frequencies = Counter(value)
    length = len(value)
    return -sum((count / length) * log2(count / length) for count in frequencies.values())


def _has_high_entropy(value: str) -> bool:
    for match in _HIGH_ENTROPY_CANDIDATE.finditer(value):
        candidate = match.group(0)
        if _REDACTION_TOKEN.fullmatch(candidate):
            continue
        if len(set(candidate)) >= 12 and _entropy(candidate) >= 4.2:
            return True
    return False


def _blocking_text_category(value: str) -> str | None:
    if _PRIVATE_KEY.search(value):
        return "private_key"
    if any(_luhn_valid(match.group(0)) for match in _CARD_CANDIDATE.finditer(value)):
        return "payment_card"
    return None


def _normalize_scanned_text(value: str) -> str:
    try:
        return _normalize_text(value)
    except UnicodeEncodeError as error:
        raise _SecurityBlock("invalid_unicode") from error


def _redact_text(value: str, context: _ScanContext) -> str:
    normalized = _normalize_scanned_text(value)
    context.count_text(normalized)
    blocked = _blocking_text_category(normalized)
    if blocked:
        raise _SecurityBlock(blocked)
    redacted = normalized
    for category, pattern in _REDACTABLE_PATTERNS:
        matches = tuple(pattern.finditer(redacted))
        if not matches:
            continue
        if not context.redact:
            raise _SecurityBlock("residual_protected_material")
        context.counts[category] += len(matches)
        redacted = pattern.sub(_replacement(category), redacted)
    if _has_high_entropy(redacted):
        raise _SecurityBlock("high_entropy")
    return redacted


def _walk(value: Any, context: _ScanContext, *, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        raise _SecurityBlock("input_limit")
    if isinstance(value, str):
        return _redact_text(value, context)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise _SecurityBlock("invalid_value")
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in context.active_containers:
            raise _SecurityBlock("invalid_value")
        context.active_containers.add(identity)
        try:
            result: dict[str, Any] = {}
            for raw_key, child in value.items():
                context.count_field()
                if not isinstance(raw_key, str):
                    raise _SecurityBlock("invalid_value")
                key = _normalize_scanned_text(raw_key)
                context.count_text(key)
                if _HIGH_RISK_SECRET_FIELD.fullmatch(key):
                    if isinstance(child, str) and _REDACTION_TOKEN.fullmatch(child):
                        result[key] = child
                        continue
                    raise _SecurityBlock("ambiguous_secret_structure")
                category = None
                if _SECRET_FIELD.fullmatch(key):
                    category = "structured_secret"
                elif _ACCOUNT_FIELD.fullmatch(key):
                    category = "account_identifier"
                if category is not None:
                    if isinstance(child, (Mapping, list, tuple, set)):
                        raise _SecurityBlock("ambiguous_secret_structure")
                    if isinstance(child, str) and _REDACTION_TOKEN.fullmatch(child):
                        result[key] = child
                        continue
                    if isinstance(child, str):
                        normalized_child = _normalize_scanned_text(child)
                        context.count_text(normalized_child)
                        blocked = _blocking_text_category(normalized_child)
                        if blocked:
                            raise _SecurityBlock(blocked)
                        if _has_high_entropy(normalized_child):
                            raise _SecurityBlock("high_entropy")
                    if not context.redact:
                        raise _SecurityBlock("residual_protected_material")
                    context.counts[category] += 1
                    result[key] = _replacement(category)
                    continue
                result[key] = _walk(child, context, depth=depth + 1)
            return result
        finally:
            context.active_containers.remove(identity)
    if isinstance(value, list):
        identity = id(value)
        if identity in context.active_containers:
            raise _SecurityBlock("invalid_value")
        context.active_containers.add(identity)
        try:
            result = []
            for child in value:
                context.count_field()
                result.append(_walk(child, context, depth=depth + 1))
            return result
        finally:
            context.active_containers.remove(identity)
    raise _SecurityBlock("invalid_value")


def secure_web_payload(payload: Mapping[str, Any]) -> SecurityResult:
    if not isinstance(payload, Mapping):
        return SecurityResult("block", None, ("invalid_value",), {"invalid_value": 1})
    first = _ScanContext(redact=True)
    try:
        secured = _walk(payload, first)
    except _SecurityBlock as error:
        first.counts[error.category] += 1
        return SecurityResult(
            "block", None, tuple(sorted(first.counts)), dict(sorted(first.counts.items()))
        )
    if not first.counts:
        return SecurityResult("allow", secured, (), {})

    verification = _ScanContext(redact=False)
    try:
        _walk(secured, verification)
    except _SecurityBlock as error:
        first.counts[error.category] += 1
        return SecurityResult(
            "block", None, tuple(sorted(first.counts)), dict(sorted(first.counts.items()))
        )
    return SecurityResult(
        "redacted",
        secured,
        tuple(sorted(first.counts)),
        dict(sorted(first.counts.items())),
    )


def _luhn_valid(candidate: str) -> bool:
    digits = [int(character) for character in candidate if character.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    total = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    )
    normalized.encode("utf-8", errors="strict")
    return normalized


def contains_protected_material(value: str) -> bool:
    normalized = _normalize_text(value)
    if any(pattern.search(normalized) for pattern in _PROTECTED_PATTERNS):
        return True
    return any(_luhn_valid(match.group(0)) for match in _CARD_CANDIDATE.finditer(normalized))


def sanitize_failure_summary(value: str) -> str:
    normalized = _normalize_text(value)
    if (
        len(normalized) > _MAX_FAILURE_SUMMARY_CHARS
        or len(normalized.encode("utf-8")) > _MAX_FAILURE_SUMMARY_BYTES
        or contains_protected_material(normalized)
    ):
        return FAILURE_SUMMARY_OMITTED
    bounded = " ".join(normalized.splitlines()).strip()
    return bounded or "stage failed"


def sanitize_failure_code(value: str) -> str:
    normalized = _normalize_text(value)
    if contains_protected_material(normalized):
        return "stage-failed"
    bounded = normalized[:64]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", bounded).strip("-._")
    return safe or "stage-failed"
