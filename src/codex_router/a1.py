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


def _surface_hard_ready(capability: A1SurfaceCapability) -> bool:
    return (
        capability.enforcement == "PROVEN_PRE_ACTION"
        and isinstance(capability.gate, str)
        and bool(capability.gate.strip())
        and _actor_attribution_is_proven(capability.actor_attribution)
    )


def hard_claim_ready(
    matrix: Iterable[A1SurfaceCapability], category: str
) -> bool:
    """Require every enabled surface in a category to have proven pre-action control."""
    if category not in A1_CATEGORIES:
        return False
    try:
        capabilities = tuple(matrix)
    except TypeError:
        return False
    if any(not isinstance(item, A1SurfaceCapability) for item in capabilities):
        return False

    enabled = tuple(
        capability
        for capability in capabilities
        if capability.category == category
        and capability.enforcement != "BASELINE_WITHHELD"
    )
    if not enabled:
        return False
    if any(capability.enforcement not in _ENFORCEMENTS for capability in enabled):
        return False
    return all(_surface_hard_ready(capability) for capability in enabled)


def permission_request_gate_ready(
    matrix: Iterable[A1SurfaceCapability],
) -> bool:
    """Require category-wide hard readiness before enabling PermissionRequest."""
    try:
        capabilities = tuple(matrix)
    except TypeError:
        return False
    if any(not isinstance(item, A1SurfaceCapability) for item in capabilities):
        return False

    for category in A1_CATEGORIES:
        if not hard_claim_ready(capabilities, category):
            continue
        if any(
            capability.category == category
            and capability.enforcement == "PROVEN_PRE_ACTION"
            and capability.gate == "PermissionRequest"
            for capability in capabilities
        ):
            return True
    return False
