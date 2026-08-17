"""V3.1 packet-scoped A1 capability and readiness primitives."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, get_args


A1_CATEGORIES = (
    "git_push",
    "remote_collaboration_mutation",
    "deploy_release_publish",
    "outbound_user_communication",
    "cloud_resource_mutation",
    "system_level_install",
    "comparable_external_persistent_mutation",
)

SurfaceEnforcement = Literal[
    "PROVEN_PRE_ACTION",
    "BASELINE_WITHHELD",
    "COOPERATIVE_ONLY",
    "UNVERIFIED",
]

_ENFORCEMENTS = frozenset(get_args(SurfaceEnforcement))
_PROVEN_ACTOR_ATTRIBUTIONS = frozenset(
    {
        "PROVEN",
        "PROVEN_ACTOR",
        "PROVEN_NATIVE",
        "PROVEN_NATIVE_ACTOR",
        "RUNTIME_PROVEN",
        "RUNTIME_PROVEN_ACTOR",
    }
)


@dataclass(frozen=True)
class A1SurfaceCapability:
    category: str
    surface: str
    enforcement: SurfaceEnforcement
    gate: str | None
    actor_attribution: str


def _actor_attribution_is_proven(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().upper().replace("-", "_")
    return normalized in _PROVEN_ACTOR_ATTRIBUTIONS


def validate_packet_authorizations(values: Iterable[str]) -> tuple[str, ...]:
    """Validate explicit packet A1 categories without interpreting tool text."""
    if isinstance(values, (str, bytes)):
        raise ValueError("A1 authorizations must be an iterable of categories")
    try:
        iterator = iter(values)
    except TypeError as error:
        raise ValueError("A1 authorizations must be iterable") from error

    result: list[str] = []
    seen: set[str] = set()
    for value in iterator:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("A1 authorization category must be non-empty text")
        if value not in A1_CATEGORIES:
            raise ValueError(f"unknown A1 authorization category: {value}")
        if value in seen:
            raise ValueError(f"duplicate A1 authorization category: {value}")
        seen.add(value)
        result.append(value)
    return tuple(result)


def hard_claim_ready(
    matrix: Iterable[A1SurfaceCapability], category: str
) -> bool:
    """Return true only for a category with a proven gate and actor identity."""
    if category not in A1_CATEGORIES:
        return False
    try:
        capabilities = iter(matrix)
    except TypeError:
        return False
    for capability in capabilities:
        if not isinstance(capability, A1SurfaceCapability):
            continue
        if capability.category != category:
            continue
        if capability.enforcement not in _ENFORCEMENTS:
            continue
        if capability.enforcement != "PROVEN_PRE_ACTION":
            continue
        if not isinstance(capability.gate, str) or not capability.gate.strip():
            continue
        if not _actor_attribution_is_proven(capability.actor_attribution):
            continue
        return True
    return False


def permission_request_gate_ready(
    matrix: Iterable[A1SurfaceCapability],
) -> bool:
    """Check whether a proven A1 surface specifically requires PermissionRequest."""
    try:
        capabilities = tuple(matrix)
    except TypeError:
        return False
    return any(
        capability.gate == "PermissionRequest"
        and hard_claim_ready((capability,), capability.category)
        for capability in capabilities
        if isinstance(capability, A1SurfaceCapability)
    )
