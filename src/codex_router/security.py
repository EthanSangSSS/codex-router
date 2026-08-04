from __future__ import annotations

import re
import unicodedata


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
