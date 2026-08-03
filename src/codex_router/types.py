from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol


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


class StageAdapter(Protocol):
    def run(self, task: str, context: Mapping[str, Any]) -> StageResult: ...
