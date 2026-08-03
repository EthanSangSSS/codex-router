from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import signal
import tempfile
import time
from typing import Any, Iterator, Mapping
import uuid

from .protocol import make_handoff
from .types import RunOutcome, StageAdapter, StageResult


STAGES = ("local_sol", "web_sol", "luna")
STAGE_FILES = {
    "local_sol": "local-sol.json",
    "web_sol": "web-sol.json",
    "luna": "luna.json",
}


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


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _append_event(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)


def _safe_error(error: BaseException) -> str:
    summary = " ".join(str(error).splitlines())[:500]
    patterns = (
        r"(?i)(authorization|cookie|password|secret|token|api[_-]?key)\s*[:=]\s*\S+",
        r"(?i)bearer\s+\S+",
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
        run_id = f"run-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:12]}"
        run_dir = self.state_root / run_id
        run_dir.mkdir(parents=True, mode=0o700)
        run_dir.chmod(0o700)
        events = run_dir / "events.jsonl"
        events.touch(mode=0o600)
        events.chmod(0o600)
        _atomic_json(
            run_dir / "request.json",
            {"run_id": run_id, "task": task, "adapter_mode": self.adapter_mode},
        )
        context: dict[str, Any] = {"run_id": run_id, "task": task}

        for stage in STAGES:
            started = time.perf_counter()
            _append_event(
                events, {"stage": stage, "status": "started", "duration_ms": 0.0}
            )
            try:
                with _timeout(self.timeout_seconds):
                    stage_result = self.adapters[stage].run(task, context.copy())
                if not isinstance(stage_result, StageResult):
                    raise TypeError("adapter must return StageResult")
                if stage_result.stage != stage:
                    raise ValueError(f"adapter returned stage {stage_result.stage!r}, expected {stage!r}")
                if not isinstance(stage_result.content, str):
                    raise TypeError("stage content must be text")
            except BaseException as error:
                duration = round((time.perf_counter() - started) * 1000, 3)
                code = "stage-timeout" if isinstance(error, StageTimedOut) else "adapter-error"
                summary = _safe_error(error)
                failure = {
                    "run_id": run_id,
                    "stage": stage,
                    "status": "failed",
                    "duration_ms": duration,
                    "error": {"code": code, "summary": summary},
                }
                _atomic_json(run_dir / STAGE_FILES[stage], failure)
                _append_event(
                    events,
                    {"stage": stage, "status": "failed", "duration_ms": duration, "error": failure["error"]},
                )
                raise RouterRunError(run_id, run_dir, stage, code, summary) from error

            duration = round((time.perf_counter() - started) * 1000, 3)
            handoff = make_handoff(run_id, stage, stage_result.content)
            stage_record = {
                "run_id": run_id,
                "stage": stage,
                "status": "completed",
                "duration_ms": duration,
                "result": {
                    "content": stage_result.content,
                    "metadata": dict(stage_result.metadata),
                },
                "handoff": handoff,
            }
            _atomic_json(run_dir / STAGE_FILES[stage], stage_record)
            _append_event(
                events,
                {"stage": stage, "status": "completed", "duration_ms": duration},
            )
            context = {"run_id": run_id, "task": task, "handoff": handoff}

        final_result = context["handoff"]["content"]
        _atomic_json(
            run_dir / "result.json",
            {"run_id": run_id, "status": "completed", "result": final_result},
        )
        return RunOutcome(run_id=run_id, run_dir=run_dir, final_result=final_result)
