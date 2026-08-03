from contextlib import contextmanager
import json
from pathlib import Path
import re
import signal
import time
from typing import Any, Iterator, Mapping
import uuid

from .protocol import make_handoff, web_response_marker
from .state import fail_stage, get_status, start_run, submit_stage
from .types import RunOutcome, StageAdapter, StageResult


STAGES = ("local_sol", "web_sol", "luna")


class StageTimedOut(TimeoutError):
    pass


class RouterRunError(RuntimeError):
    def __init__(self, run_id: str, run_dir: Path, stage: str, code: str, summary: str):
        super().__init__(summary)
        self.run_id = run_id
        self.run_dir = run_dir
        self.stage = stage
        self.code = code
        self.summary = summary


def _safe_error(error: BaseException) -> str:
    summary = " ".join(str(error).splitlines())[:500]
    patterns = (
        r"(?i)bearer\s+\S+",
        r"(?i)(authorization|cookie|password|secret|token|api[_-]?key)\s*[:=]\s*\S+",
    )
    for pattern in patterns:
        summary = re.sub(
            pattern,
            lambda match: (
                f"{match.group(1)}=<redacted>" if match.lastindex else "<redacted>"
            ),
            summary,
        )
    return summary or error.__class__.__name__


@contextmanager
def _timeout(seconds: float) -> Iterator[None]:
    if seconds <= 0:
        yield
        return
    previous = signal.getsignal(signal.SIGALRM)

    def expired(_signum, _frame):
        raise StageTimedOut(f"stage exceeded {seconds:g}s timeout")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _validate_stage_result(stage: str, result: StageResult) -> None:
    if not isinstance(result, StageResult):
        raise TypeError("adapter must return StageResult")
    if result.stage != stage:
        raise ValueError(f"adapter returned stage {result.stage!r}, expected {stage!r}")
    if not isinstance(result.content, str):
        raise TypeError("stage content must be text")


def _fake_execution(
    stage: str,
    driver_context_id: str,
    packet: Mapping[str, Any],
    *,
    duration_ms: float,
) -> dict[str, Any]:
    del stage
    return {
        "driver_context_id": driver_context_id,
        "packet_digest": packet["packet_digest"],
        "verification": "fake_offline",
        "network_used": False,
        "duration_ms": duration_ms,
    }


def _adapter_context_from_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    payload = packet["payload"]
    context = {"run_id": packet["run_id"], "task": payload["task"]}
    if packet["target_stage"] == "web_sol":
        context["handoff"] = make_handoff(
            packet["run_id"], "local_sol", payload["local_sol_output"]
        )
    elif packet["target_stage"] == "luna":
        web_lines = payload["web_sol_output"].splitlines()
        semantic_web_output = "\n".join(web_lines[1:])
        context["handoff"] = make_handoff(
            packet["run_id"], "web_sol", semantic_web_output
        )
    return context


class Router:
    def __init__(
        self,
        adapters: Mapping[str, StageAdapter],
        state_root: Path,
        timeout_seconds: float = 60,
        adapter_mode: str = "custom",
    ):
        missing = [stage for stage in STAGES if stage not in adapters]
        if missing:
            raise ValueError(f"missing adapters: {', '.join(missing)}")
        self.adapters = adapters
        self.state_root = Path(state_root)
        self.timeout_seconds = timeout_seconds
        self.adapter_mode = adapter_mode

    def run(self, task: str) -> RunOutcome:
        resolved_root = self.state_root.expanduser().resolve(strict=False)
        live_root = (Path.home() / ".codex").resolve(strict=False)
        if resolved_root == live_root or live_root in resolved_root.parents:
            raise ValueError("Router state must not use the live Codex profile")
        resolved_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        resolved_root.chmod(0o700)

        driver_context_id = f"ctx-{uuid.uuid4()}"
        fake_binary = resolved_root / ".profiles" / driver_context_id / "offline-codex"
        fake_binary.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fake_binary.parent.chmod(0o700)
        fake_binary.write_text("offline pipeline marker\n", encoding="utf-8")
        fake_binary.chmod(0o700)
        role_config = {
            "local_sol": {
                "requested_model": "fake-local-sol",
                "requested_reasoning": "offline",
            },
            "web_sol": {
                "model_claimed": "fake-web-sol",
                "reasoning_claimed": "offline",
                "verification": "fake_offline",
            },
            "luna": {
                "requested_model": "fake-luna",
                "requested_reasoning": "offline",
            },
        }
        transition = start_run(
            state_root=resolved_root,
            task=task,
            driver_context_id=driver_context_id,
            role_config=role_config,
            codex_binary=fake_binary.resolve(),
            driver_type="offline_pipeline",
        )

        for stage in STAGES:
            packet = json.loads(transition.stage_packet_path.read_text(encoding="utf-8"))
            context = _adapter_context_from_packet(packet)
            canonical_task = packet["payload"]["task"]
            started = time.perf_counter()
            try:
                with _timeout(self.timeout_seconds):
                    stage_result = self.adapters[stage].run(canonical_task, context.copy())
                _validate_stage_result(stage, stage_result)
            except Exception as error:
                duration = round((time.perf_counter() - started) * 1000, 3)
                code = "stage-timeout" if isinstance(error, StageTimedOut) else "adapter-error"
                summary = _safe_error(error)
                fail_stage(
                    state_root=resolved_root,
                    run_id=transition.run_id,
                    driver_context_id=driver_context_id,
                    stage=stage,
                    expected_revision=transition.revision,
                    packet_digest_value=packet["packet_digest"],
                    failure={"code": code, "summary": summary},
                    execution=_fake_execution(
                        stage,
                        driver_context_id,
                        packet,
                        duration_ms=duration,
                    ),
                )
                raise RouterRunError(
                    transition.run_id,
                    transition.run_dir,
                    stage,
                    code,
                    summary,
                ) from error

            duration = round((time.perf_counter() - started) * 1000, 3)
            content = stage_result.content
            if stage == "web_sol":
                content = web_response_marker(packet) + "\n" + content
            transition = submit_stage(
                state_root=resolved_root,
                run_id=transition.run_id,
                driver_context_id=driver_context_id,
                stage=stage,
                expected_revision=transition.revision,
                packet_digest_value=packet["packet_digest"],
                content=content,
                execution=_fake_execution(
                    stage,
                    driver_context_id,
                    packet,
                    duration_ms=duration,
                ),
            )

        completed = get_status(state_root=resolved_root, run_id=transition.run_id)
        result = json.loads((completed.run_dir / "result.json").read_text(encoding="utf-8"))
        return RunOutcome(
            run_id=completed.run_id,
            run_dir=completed.run_dir,
            final_result=result["result"],
        )
