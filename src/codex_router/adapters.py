from typing import Any, Mapping

from .types import StageResult


class ProviderNotConfigured(RuntimeError):
    pass


class FakeAdapter:
    def __init__(self, stage: str):
        self.stage = stage

    def run(self, task: str, context: Mapping[str, Any]) -> StageResult:
        if self.stage == "local_sol":
            content = f"Local Sol completed: {task}"
        elif self.stage == "web_sol":
            upstream = context["handoff"]["content"]
            content = f"Web Sol reviewed: {upstream}"
        else:
            prefix = "Return exactly "
            content = task[len(prefix) :] if task.startswith(prefix) else f"Luna final: {context['handoff']['content']}"
        return StageResult(
            stage=self.stage,
            content=content,
            metadata={"adapter": "fake", "network_used": False},
        )


class UnconfiguredAdapter:
    def __init__(self, stage: str):
        self.stage = stage

    def run(self, task: str, context: Mapping[str, Any]) -> StageResult:
        raise ProviderNotConfigured(
            f"provider-not-configured: real adapter for {self.stage} is not configured"
        )


def adapters_for_mode(mode: str):
    adapter_type = FakeAdapter if mode == "fake" else UnconfiguredAdapter
    return {stage: adapter_type(stage) for stage in ("local_sol", "web_sol", "luna")}
