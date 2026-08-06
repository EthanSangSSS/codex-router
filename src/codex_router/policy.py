from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
from typing import Literal
import unicodedata

from .security import contains_protected_material


PolicyAction = Literal["route", "direct", "bypass"]


@dataclass(frozen=True)
class PolicyDecision:
    decision: PolicyAction
    reason_code: str
    sensitive_categories: tuple[str, ...] = ()


_BYPASS = re.compile(
    r"(?:本次不用\s+router|仅本地执行)\s*[。.!！;；:]?\s*\Z", re.IGNORECASE
)
_SUBSTANTIVE = re.compile(
    r"修改|编辑|创建|删除|写入|提交|推送|合并|实现|修复|审查|评审|"
    r"\breview\b|\bPR\b|安全|架构|研究|调研|搜索|核实|事实验证|比较|"
    r"决定|决策|规划|计划|设计|执行|运行|安装|配置|部署|发布|代码|仓库|"
    r"multi[- ]?step|write|implement|fix|research|verify|compare|decide|plan|design",
    re.IGNORECASE,
)
_GREETING = re.compile(r"(?:你好|您好|嗨|hi|hello|hey)[！!。.]?\Z", re.IGNORECASE)
_ACKNOWLEDGEMENT = re.compile(
    r"(?:谢谢|感谢|好的|好吧|明白了?|收到|可以|确认|ok|okay|thanks?)[！!。.]?\Z",
    re.IGNORECASE,
)
_CONCEPT = re.compile(
    r"(?:什么是|解释一下|简要说明|简单解释|what is\b|explain\b|define\b)",
    re.IGNORECASE,
)
_TASK_METADATA = re.compile(
    r"(?:当前)?(?:任务|工作|执行)?(?:状态|进度|分支|head|结果)(?:是什么|如何|怎样)?[？?。.]?\Z",
    re.IGNORECASE,
)
_READ_ONLY = re.compile(r"(?:读取|查看|显示|列出|打开看看|inspect|show|read|list)\s+.+", re.IGNORECASE)


def _normalize_prompt(prompt: str) -> str:
    if not isinstance(prompt, str):
        raise TypeError("prompt must be text")
    normalized = unicodedata.normalize(
        "NFC", prompt.replace("\r\n", "\n").replace("\r", "\n")
    )
    normalized.encode("utf-8", errors="strict")
    return normalized.strip()


def _first_nonempty_line(prompt: str) -> str:
    for line in prompt.split("\n"):
        if line.strip():
            return line.strip()
    return ""


def _is_trivial_arithmetic(prompt: str) -> bool:
    candidate = re.sub(r"(?:等于多少|是多少|求值)?\s*[？?。.]?\s*\Z", "", prompt)
    return bool(candidate) and re.fullmatch(r"[0-9\s()+\-*/%.]+", candidate) is not None


def classify_prompt(prompt: str) -> PolicyDecision:
    normalized = _normalize_prompt(prompt)
    first_line = _first_nonempty_line(normalized)
    if _BYPASS.fullmatch(first_line):
        return PolicyDecision("bypass", "explicit_one_turn_bypass")

    try:
        sensitive = contains_protected_material(normalized)
    except UnicodeEncodeError:
        sensitive = True
    if sensitive:
        return PolicyDecision("route", "sensitive_detected", ("protected_material",))

    if _SUBSTANTIVE.search(normalized):
        return PolicyDecision("route", "substantive_request")
    if _GREETING.fullmatch(normalized):
        return PolicyDecision("direct", "casual_greeting")
    if _ACKNOWLEDGEMENT.fullmatch(normalized):
        return PolicyDecision("direct", "acknowledgement")
    if _is_trivial_arithmetic(normalized):
        return PolicyDecision("direct", "trivial_arithmetic")
    if len(normalized) <= 160 and _CONCEPT.match(normalized):
        return PolicyDecision("direct", "brief_concept")
    if len(normalized) <= 120 and _TASK_METADATA.fullmatch(normalized):
        return PolicyDecision("direct", "task_metadata")
    if (
        len(normalized) <= 160
        and _READ_ONLY.fullmatch(normalized)
        and not re.search(r"并|然后|以及|同时|分析|总结|判断|and then", normalized, re.IGNORECASE)
    ):
        return PolicyDecision("direct", "one_step_read_only")
    return PolicyDecision("route", "ambiguous_default")


def _validated_secret(secret: bytes) -> bytes:
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("installation secret must contain at least 32 bytes")
    return secret


def _keyed_digest(secret: bytes, domain: bytes, value: str) -> str:
    key = _validated_secret(secret)
    if not isinstance(value, str) or not value:
        raise ValueError("identity input must be non-empty text")
    encoded = unicodedata.normalize("NFC", value).encode("utf-8", errors="strict")
    return hmac.new(key, domain + b"\0" + encoded, hashlib.sha256).hexdigest()


def derive_driver_context(secret: bytes, session_id: str) -> str:
    return "ctx-" + _keyed_digest(secret, b"session", session_id)


def derive_turn_digest(secret: bytes, turn_id: str) -> str:
    return _keyed_digest(secret, b"turn", turn_id)


def derive_prompt_digest(secret: bytes, prompt: str) -> str:
    return "hmac-sha256:" + _keyed_digest(secret, b"prompt", _normalize_prompt(prompt))


def derive_event_identity(secret: bytes, session_id: str, turn_id: str) -> str:
    session_digest = _keyed_digest(secret, b"session", session_id)
    turn_digest = derive_turn_digest(secret, turn_id)
    combined = session_digest + ":" + turn_digest
    return "event-" + _keyed_digest(secret, b"event", combined)


def secure_identity_equal(left: str, right: str) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
