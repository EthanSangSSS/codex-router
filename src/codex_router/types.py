from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol


@dataclass(frozen=True)
class StageResult:
    stage: str
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    run_dir: Path
    final_result: str


@dataclass(frozen=True)
class TransitionResult:
    run_id: str
    run_dir: Path
    revision: int
    status: str
    next_stage: str | None
    stage_packet_path: Path | None
    idempotent: bool = False
    projection_warnings: tuple[str, ...] = ()


SecurityDecision = Literal["allow", "redacted", "block"]


@dataclass(frozen=True)
class SecurityResult:
    decision: SecurityDecision
    value: Any | None
    categories: tuple[str, ...]
    counts: Mapping[str, int]


@dataclass(frozen=True)
class GlobalStatus:
    state: str
    installation_dir: Path
    hook_configured: bool
    agents_managed: bool
    luna_agent_configured: bool
    config_valid: bool
    identity_material_valid: bool
    hook_trust: str
    new_session_required: bool
    compatibility: str = "UNKNOWN_REQUIRES_CAPABILITY_CHECK"
    compatibility_reason: str = "effective primary Codex capability is unverified"
    luna_execution_mode: str = "unknown"
    router_design: str = "v3.1"
    live_activation: str = "BLOCKED_ACCEPTANCE_GATES"
    live_activation_blockers: tuple[str, ...] = ()
    deferred_acceptance_evidence: tuple[str, ...] = ()


class StageAdapter(Protocol):
    def run(self, task: str, context: Mapping[str, Any]) -> StageResult: ...
