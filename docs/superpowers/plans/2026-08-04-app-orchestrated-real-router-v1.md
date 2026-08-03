# App-Orchestrated Real Router V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a resumable App-driven `Local Sol -> Web Sol -> Luna` workflow whose canonical state is owned by Router while preserving the existing offline fake command.

**Architecture:** `state.py` owns the locked, atomic state machine and rebuildable projections; `protocol.py` owns canonical encoding, digests, packets, and Web response markers. The CLI exposes `start`, `submit-stage`, `fail-stage`, and `status`, while the existing `run --adapter-mode fake` becomes a synchronous driver over the same domain functions.

**Tech Stack:** Python 3.12 standard library, `argparse`, `dataclasses`, `fcntl.flock`, JSON files, `hashlib.sha256`, `unittest`, repository-scoped self-hosted GitHub Actions.

## Global Constraints

- Codex App is the only execution driver; Router is the only workflow state authority.
- The only success path is `awaiting_local_sol@0 -> awaiting_web_sol@1 -> awaiting_luna@2 -> completed@3`.
- The current stage may transition to `failed@(N+1)`; `completed` and `failed` are terminal.
- `state.json` is the sole canonical state. Stage files, packets, events, request, and result are rebuildable projections.
- Every read-modify-write transition holds `fcntl.flock(LOCK_EX)` on the stable per-run `.lock` file.
- Canonical state commits use a mode-`0600` same-directory temporary file, file `fsync`, `os.replace`, and directory `fsync`.
- Run directories are mode `0700`; state, lock, packet, output, marker, and projection files are mode `0600`.
- Identical success or failure retries are idempotent before revision or terminal checks; different duplicates are conflicts.
- Content normalization is UTF-8 validation, `CRLF`/`CR` to `LF`, and Unicode NFC only.
- Local Sol requests `gpt-5.6-sol` with `max`; Web Sol claims `sol` with `xhigh`; Luna requests `gpt-5.6-luna` with `max`.
- Web execution remains `operator_attested`; local reported values remain distinct from requested values.
- Local profiles are Router-owned and must resolve outside live `~/.codex`; no binary may be resolved through `PATH`.
- V1 is read-only for target workspaces and adds no daemon, database, queue, browser bridge, automatic retry, archive/delete flow, or target-workspace mutation.
- Python remains `>=3.12` with no new runtime dependencies.
- Do not push, open a PR, merge, or start the self-hosted runner unless a later user instruction explicitly authorizes it.

---

## File Structure

- Create `src/codex_router/state.py`: canonical state schema, run/profile creation, per-run locking, transitions, projection rebuilding, domain errors, and result envelopes.
- Modify `src/codex_router/protocol.py`: canonical JSON, normalization, SHA-256 packet/submission/failure digests, cumulative packet construction, and exact Web marker validation.
- Modify `src/codex_router/types.py`: typed immutable `TransitionResult` returned by domain functions.
- Modify `src/codex_router/cli.py`: App-driver subcommands, JSON input/output, stable error schema, and exit-code mapping.
- Modify `src/codex_router/pipeline.py`: preserve timeout/error behavior while driving fake mode through `start_run`, `submit_stage`, and `fail_stage`.
- Modify `src/codex_router/__init__.py`: export the public state-machine API.
- Create `tests/test_state.py`: state, locking, durability, projection, idempotency, failure, profile, and secret-redaction tests.
- Modify `tests/test_protocol.py`: canonical encoding, digests, packets, normalization, and Web marker tests.
- Modify `tests/test_cli.py`: full App-driver CLI lifecycle and stable JSON error/exit-code tests.
- Modify `tests/test_pipeline.py`: prove fake mode uses canonical state and preserves exception propagation.
- Modify `README.md`: document the App-driven workflow, evidence levels, read-only profile contract, and limitations.
- Modify `.github/workflows/ci.yml`: run CI on the new feature branch without changing the repository-scoped self-hosted runner policy.

### Task 1: Canonical Protocol, Digests, and Web Marker

**Files:**
- Modify: `src/codex_router/protocol.py`
- Modify: `tests/test_protocol.py`

**Interfaces:**
- Consumes: Python `json`, `hashlib`, `unicodedata`, and existing `ProtocolError`.
- Produces: `normalize_content(value: str) -> str`, `canonical_json_bytes(value: Any) -> bytes`, `digest_json(value: Any) -> str`, `build_stage_packet(*, driver_context_id: str, run_id: str, packet_id: str, target_stage: str, source_revision: int, payload: Mapping[str, Any]) -> dict[str, Any]`, `submission_digest(driver_context_id: str, run_id: str, stage: str, packet_digest: str, content: str, stable_execution_metadata: Mapping[str, Any]) -> str`, `failure_digest(driver_context_id: str, run_id: str, stage: str, packet_digest: str, failure: Mapping[str, Any], stable_execution_metadata: Mapping[str, Any]) -> str`, `web_response_marker(packet: Mapping[str, Any]) -> str`, and `validate_web_response(content: str, packet: Mapping[str, Any]) -> None`.

- [ ] **Step 1: Add failing normalization and canonical JSON tests**

```python
from codex_router.protocol import canonical_json_bytes, normalize_content


class CanonicalProtocolTests(unittest.TestCase):
    def test_content_normalization_is_nfc_and_newlines_only(self):
        self.assertEqual(normalize_content("  cafe\u0301\r\nline\r\n"), "  café\nline\n")

    def test_canonical_json_is_stable_utf8_without_nan(self):
        left = canonical_json_bytes({"z": "雪", "a": [2, 1]})
        right = canonical_json_bytes({"a": [2, 1], "z": "雪"})
        self.assertEqual(left, b'{"a":[2,1],"z":"\xe9\x9b\xaa"}')
        self.assertEqual(left, right)
        with self.assertRaises(ValueError):
            canonical_json_bytes({"bad": float("nan")})
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_protocol.CanonicalProtocolTests -v`

Expected: FAIL because `canonical_json_bytes` and `normalize_content` do not exist.

- [ ] **Step 3: Implement exact canonical encoding and normalization**

```python
import hashlib
import unicodedata


RUN_PROTOCOL = "codex-router/run-state/v1"
PACKET_PROTOCOL = "codex-router/stage-packet/v1"
WEB_RESPONSE_PREFIX = "[CODEX_ROUTER_RESPONSE_V1]"


def normalize_content(value: str) -> str:
    if not isinstance(value, str):
        raise ProtocolError("content must be text")
    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    normalized.encode("utf-8", errors="strict")
    return normalized


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", errors="strict")


def digest_json(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()
```

- [ ] **Step 4: Add failing packet, digest, and Web marker tests**

```python
from codex_router.protocol import (
    ProtocolError,
    build_stage_packet,
    digest_json,
    failure_digest,
    submission_digest,
    validate_web_response,
    web_response_marker,
)


class StagePacketTests(unittest.TestCase):
    def setUp(self):
        self.packet = build_stage_packet(
            driver_context_id="ctx-550e8400-e29b-41d4-a716-446655440000",
            run_id="run-123",
            packet_id="packet-123",
            target_stage="web_sol",
            source_revision=1,
            payload={"task": "review", "local_sol_output": "done"},
        )

    def test_packet_digest_binds_every_identity_field(self):
        changed = dict(self.packet)
        changed["driver_context_id"] = "ctx-other"
        changed.pop("packet_digest")
        self.assertNotEqual(self.packet["packet_digest"], digest_json(changed))

    def test_submission_digest_excludes_event_time_but_binds_stable_metadata(self):
        stable = {"verification": "operator_attested", "model_claimed": "sol"}
        first = submission_digest("ctx-550e8400-e29b-41d4-a716-446655440000", "run-123", "web_sol", self.packet["packet_digest"], "answer\r\n", stable)
        second = submission_digest("ctx-550e8400-e29b-41d4-a716-446655440000", "run-123", "web_sol", self.packet["packet_digest"], "answer\n", stable)
        changed = submission_digest("ctx-550e8400-e29b-41d4-a716-446655440000", "run-123", "web_sol", self.packet["packet_digest"], "answer\n", {**stable, "model_claimed": "other"})
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)

    def test_failure_digest_is_symmetric_with_success_identity(self):
        first = failure_digest("ctx-550e8400-e29b-41d4-a716-446655440000", "run-123", "web_sol", self.packet["packet_digest"], {"code": "web-failed", "summary": "offline"}, {"verification": "operator_attested"})
        second = failure_digest("ctx-550e8400-e29b-41d4-a716-446655440000", "run-123", "web_sol", self.packet["packet_digest"], {"summary": "offline", "code": "web-failed"}, {"verification": "operator_attested"})
        self.assertEqual(first, second)

    def test_web_marker_must_be_the_unique_first_nonempty_line(self):
        marker = web_response_marker(self.packet)
        validate_web_response("\n" + marker + "\nanalysis", self.packet)
        for invalid in ("analysis\n" + marker, marker + "\n" + marker, marker.replace("run-123", "run-other")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ProtocolError):
                    validate_web_response(invalid, self.packet)
```

- [ ] **Step 5: Run the new protocol tests and confirm they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_protocol.StagePacketTests -v`

Expected: FAIL because packet, digest, and Web marker functions do not exist.

- [ ] **Step 6: Implement packet construction and exact digest inputs**

```python
def build_stage_packet(*, driver_context_id, run_id, packet_id, target_stage, source_revision, payload):
    if target_stage not in STAGES:
        raise ProtocolError(f"unknown stage: {target_stage}")
    packet = {
        "protocol": PACKET_PROTOCOL,
        "driver_context_id": driver_context_id,
        "run_id": run_id,
        "packet_id": packet_id,
        "target_stage": target_stage,
        "source_revision": source_revision,
        "payload": payload,
    }
    return {**packet, "packet_digest": digest_json(packet)}


def submission_digest(driver_context_id, run_id, stage, packet_digest, content, stable_execution_metadata):
    return digest_json({
        "driver_context_id": driver_context_id,
        "run_id": run_id,
        "stage": stage,
        "packet_digest": packet_digest,
        "normalized_content": normalize_content(content),
        "stable_execution_metadata": dict(stable_execution_metadata),
    })


def failure_digest(driver_context_id, run_id, stage, packet_digest, failure, stable_execution_metadata):
    return digest_json({
        "driver_context_id": driver_context_id,
        "run_id": run_id,
        "stage": stage,
        "packet_digest": packet_digest,
        "failure": dict(failure),
        "stable_execution_metadata": dict(stable_execution_metadata),
    })
```

Implement `web_response_marker()` with fields in this exact order: `driver_context_id`, `run_id`, `stage`, `revision`, `packet_id`, `packet_digest`. Implement `validate_web_response()` by selecting non-empty lines, requiring the first to equal the expected marker, and requiring the expected marker to occur exactly once.

- [ ] **Step 7: Run all protocol tests**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_protocol -v`

Expected: all existing handoff tests and all new canonical protocol tests PASS.

- [ ] **Step 8: Commit the protocol unit**

```bash
git add src/codex_router/protocol.py tests/test_protocol.py
git commit -m "feat(router): add canonical stage protocol"
```

### Task 2: Canonical Run Creation, Router-Owned Profiles, and Durable Storage

**Files:**
- Create: `src/codex_router/state.py`
- Modify: `src/codex_router/types.py`
- Modify: `src/codex_router/__init__.py`
- Create: `tests/test_state.py`

**Interfaces:**
- Consumes: Task 1 protocol constants and `build_stage_packet()`.
- Produces: `RouterStateError`, `TransitionResult`, `start_run(*, state_root, task, driver_context_id, role_config, codex_binary, driver_type="codex_app")`, and `get_status(*, state_root, run_id)`.

- [ ] **Step 1: Add failing run-creation and unsafe-root tests**

```python
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from codex_router.state import RouterStateError, start_run


ROLE_CONFIG = {
    "local_sol": {"requested_model": "gpt-5.6-sol", "requested_reasoning": "max"},
    "web_sol": {"model_claimed": "sol", "reasoning_claimed": "xhigh", "verification": "operator_attested"},
    "luna": {"requested_model": "gpt-5.6-luna", "requested_reasoning": "max"},
}


class RunCreationTests(unittest.TestCase):
    def test_start_creates_revision_zero_state_and_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "codex"
            binary.write_text("binary")
            binary.chmod(0o700)
            result = start_run(
                state_root=Path(tmp) / "runs",
                task="review",
                driver_context_id="ctx-550e8400-e29b-41d4-a716-446655440000",
                role_config=ROLE_CONFIG,
                codex_binary=binary,
            )
            state = json.loads((result.run_dir / "state.json").read_text())
            self.assertEqual((state["status"], state["revision"], state["next_stage"]), ("awaiting_local_sol", 0, "local_sol"))
            self.assertEqual(state["driver"]["driver_context_id"], "ctx-550e8400-e29b-41d4-a716-446655440000")
            self.assertEqual(state["next_packet"]["target_stage"], "local_sol")
            self.assertEqual(stat.S_IMODE(result.run_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((result.run_dir / "state.json").stat().st_mode), 0o600)
            for stage in ("local_sol", "luna"):
                profile = state["profiles"][stage]
                self.assertNotEqual(Path(profile["codex_home"]).resolve(), Path.home() / ".codex")
                self.assertTrue(Path(profile["ownership_marker"]).is_file())

    def test_live_codex_root_is_rejected(self):
        with self.assertRaises(RouterStateError) as raised:
            start_run(
                state_root=Path.home() / ".codex" / "router-runs",
                task="unsafe",
                driver_context_id="ctx-550e8400-e29b-41d4-a716-446655440000",
                role_config=ROLE_CONFIG,
                codex_binary=Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
            )
        self.assertEqual(raised.exception.code, "unsafe-state-root")
```

- [ ] **Step 2: Run the run-creation tests and confirm they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_state.RunCreationTests -v`

Expected: FAIL because `codex_router.state` does not exist.

- [ ] **Step 3: Add the immutable result and stable domain error types**

```python
# src/codex_router/types.py
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


# src/codex_router/state.py
ERROR_EXIT_CODES = {
    "conflict": 20,
    "invalid-transition": 21,
    "revision-mismatch": 22,
    "packet-mismatch": 23,
    "marker-mismatch": 24,
    "invalid-input": 25,
    "run-not-found": 26,
    "unsafe-state-root": 27,
    "state-corrupt": 28,
    "profile-mismatch": 29,
}


class RouterStateError(RuntimeError):
    def __init__(self, code, message, *, run_id=None, stage=None, revision=None):
        super().__init__(message)
        self.code = code
        self.exit_code = ERROR_EXIT_CODES[code]
        self.run_id = run_id
        self.stage = stage
        self.revision = revision
```

- [ ] **Step 4: Implement safe roots, Router-owned profiles, locks, and atomic state writes**

Use these exact internal boundaries in `state.py`:

```python
@contextmanager
def _exclusive_run_lock(run_dir: Path):
    lock_path = run_dir / ".lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock_path, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _commit_state(run_dir: Path, state: Mapping[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".state.json.", dir=run_dir)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical_json_bytes(state) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, run_dir / "state.json")
        directory_fd = os.open(run_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
```

Resolve `state_root` and reject it when it equals or is below `Path.home() / ".codex"`. Validate `driver_context_id` as `ctx-` followed by a canonical lowercase UUID; this prevents path traversal and user-derived identifiers. Accept only `driver_type="codex_app"` or `driver_type="offline_pipeline"`. Require `codex_binary` to be absolute, exist, be executable, and resolve to the same absolute path; never call `shutil.which()` or another `PATH` lookup.

Create profile roots at `state_root / ".profiles" / driver_context_id / run_id / stage`, outside every run evidence directory and isolated per run, with separate `codex-home`, `sqlite-home`, and a mode-`0600` `profile.json` ownership marker containing a generated `profile_id`, `protocol`, `driver_context_id`, `run_id`, `stage`, `owner="codex-router"`, `workspace_access="read_only"`, the absolute binary realpath, and its SHA-256. Canonical profile records expose the same values as `codex_home`, `codex_sqlite_home`, `codex_binary_realpath`, and `codex_binary_sha256`. Create profiles only for Local Sol and Luna. Tests that enumerate runs must select `run-*` directories and ignore `.profiles`.

- [ ] **Step 5: Implement collision-safe `start_run()` and initial canonical state**

Generate `run-<UTC timestamp>-<12 hex>` and create the run directory with `exist_ok=False`. Retry a collision at most three times. After creating the directory, `fsync` `state_root`, create `.lock`, and hold its exclusive lock through initial state construction and `_commit_state()`. If state initialization fails after directory creation, leave the mode-`0700` directory for diagnosis; `get_status()` must classify a directory without `state.json` as `state-corrupt` and never reuse it.

The initial state must contain:

```python
state = {
    "protocol": RUN_PROTOCOL,
    "run_id": run_id,
    "driver": {"driver_type": driver_type, "driver_context_id": driver_context_id},
    "status": "awaiting_local_sol",
    "revision": 0,
    "next_stage": "local_sol",
    "request": {"task": normalize_content(task)},
    "role_config": deepcopy(dict(role_config)),
    "profiles": profiles,
    "submissions": {},
    "failures": {},
    "next_packet": initial_packet,
    "final_result": None,
    "history": [{"revision": 0, "event": "run_started", "stage": "local_sol"}],
}
```

The Local Sol payload includes the task, requested model/reasoning, read-only permission, profile contract, and output contract. Do not put timestamps, PIDs, temporary paths, environment variables, credentials, or account identifiers in canonical state.

Implement the initial form of `_rebuild_projections()` in this task so `start_run()` writes `request.json`, `events.jsonl`, and `packets/<packet_id>.json` only after canonical state commits. Task 3 extends the same function for stage and result projections; it does not introduce a second projection writer.

- [ ] **Step 6: Add and pass collision, incomplete-run, and file-mode tests**

Patch `_new_run_id` to return a pre-existing ID and then a fresh ID; assert `start_run()` uses the fresh ID. Pre-create an empty run directory and assert `get_status()` raises `state-corrupt`. Assert `.lock`, `state.json`, packet, and profile markers are mode `0600`.

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_state.RunCreationTests -v`

Expected: all run creation, safety, collision, and mode tests PASS.

- [ ] **Step 7: Export the public state API and commit**

```python
# src/codex_router/__init__.py
from .state import RouterStateError, get_status, start_run
from .types import TransitionResult
```

```bash
git add src/codex_router/state.py src/codex_router/types.py src/codex_router/__init__.py tests/test_state.py
git commit -m "feat(router): add canonical run state"
```

### Task 3: Successful Stage Transitions, Idempotency, and Projections

**Files:**
- Modify: `src/codex_router/state.py`
- Modify: `tests/test_state.py`

**Interfaces:**
- Consumes: Task 1 digests/marker functions and Task 2 locking/storage/result types.
- Produces: `submit_stage(*, state_root, run_id, driver_context_id, stage, expected_revision, packet_digest_value, content, execution) -> TransitionResult` and the completed deterministic `_rebuild_projections(run_dir, state)` created in Task 2.

- [ ] **Step 1: Add failing success-path and cumulative-packet tests**

```python
from codex_router.protocol import web_response_marker
from codex_router.state import submit_stage


DRIVER_CONTEXT_ID = "ctx-550e8400-e29b-41d4-a716-446655440000"


class RouterStateTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state_root = self.root / "runs"
        self.binary = self.root / "codex"
        self.binary.write_text("test binary", encoding="utf-8")
        self.binary.chmod(0o700)
        self.started = None

    def start(self):
        self.started = start_run(
            state_root=self.state_root,
            task="review",
            driver_context_id=DRIVER_CONTEXT_ID,
            role_config=ROLE_CONFIG,
            codex_binary=self.binary,
        )
        return self.started

    def read_state(self):
        return json.loads((self.started.run_dir / "state.json").read_text(encoding="utf-8"))

    def local_execution(self, stage="local_sol"):
        state = self.read_state()
        packet = state["next_packet"]
        profile = state["profiles"][stage]
        role = state["role_config"][stage]
        return {
            "requested_model": role["requested_model"],
            "requested_reasoning": role["requested_reasoning"],
            "reported_model": role["requested_model"],
            "reported_reasoning": role["requested_reasoning"],
            "verification": "app_server_reported",
            "thread_id": "thread-test",
            "driver_context_id": DRIVER_CONTEXT_ID,
            "packet_digest": packet["packet_digest"],
            "profile_id": profile["profile_id"],
            "codex_home": profile["codex_home"],
            "codex_sqlite_home": profile["codex_sqlite_home"],
            "codex_binary_realpath": profile["codex_binary_realpath"],
            "codex_binary_sha256": profile["codex_binary_sha256"],
            "app_server_version": "test-version",
            "workspace_access": "read_only",
        }

    def web_execution(self):
        packet = self.read_state()["next_packet"]
        return {
            "driver_context_id": DRIVER_CONTEXT_ID,
            "web_context_ref": "web-context-test",
            "context_mode": "continuous",
            "context_scope": "driver_context_id",
            "context_isolation": "operator_managed",
            "model_claimed": "sol",
            "reasoning_claimed": "xhigh",
            "verification": "operator_attested",
            "packet_digest": packet["packet_digest"],
        }

    def luna_execution(self):
        return self.local_execution(stage="luna")

    def submit(self, transition, stage, content, execution):
        packet = self.read_state()["next_packet"]
        return submit_stage(
            state_root=self.state_root,
            run_id=transition.run_id,
            driver_context_id=DRIVER_CONTEXT_ID,
            stage=stage,
            expected_revision=transition.revision,
            packet_digest_value=packet["packet_digest"],
            content=content,
            execution=execution,
        )

    def submit_local(self):
        started = self.start()
        packet = self.read_state()["next_packet"]
        args = {
            "state_root": self.state_root,
            "run_id": started.run_id,
            "driver_context_id": DRIVER_CONTEXT_ID,
            "stage": "local_sol",
            "expected_revision": 0,
            "packet_digest_value": packet["packet_digest"],
            "content": "local result",
            "execution": self.local_execution(),
        }
        return submit_stage(**args), args

    def complete_run(self):
        local, _ = self.submit_local()
        web_packet = self.read_state()["next_packet"]
        web = self.submit(
            local,
            "web_sol",
            web_response_marker(web_packet) + "\nweb result",
            self.web_execution(),
        )
        luna_packet = self.read_state()["next_packet"]
        args = {
            "state_root": self.state_root,
            "run_id": web.run_id,
            "driver_context_id": DRIVER_CONTEXT_ID,
            "stage": "luna",
            "expected_revision": 2,
            "packet_digest_value": luna_packet["packet_digest"],
            "content": "final result",
            "execution": self.luna_execution(),
        }
        return submit_stage(**args), args


class SuccessfulTransitionTests(RouterStateTestCase):
    def test_success_path_advances_zero_to_three(self):
        started = self.start()
        local = self.submit(started, "local_sol", "local result", self.local_execution())
        self.assertEqual((local.status, local.revision, local.next_stage), ("awaiting_web_sol", 1, "web_sol"))

        web_packet = self.read_state()["next_packet"]
        web_content = web_response_marker(web_packet) + "\nweb result"
        web = self.submit(local, "web_sol", web_content, self.web_execution())
        self.assertEqual((web.status, web.revision, web.next_stage), ("awaiting_luna", 2, "luna"))
        self.assertEqual(self.read_state()["next_packet"]["payload"]["local_sol_output"], "local result")

        luna = self.submit(web, "luna", "final result", self.luna_execution())
        self.assertEqual((luna.status, luna.revision, luna.next_stage), ("completed", 3, None))
        state = self.read_state()
        self.assertEqual(state["final_result"], "final result")
        self.assertEqual(json.loads((luna.run_dir / "result.json").read_text())["result"], "final result")
```

- [ ] **Step 2: Run the success test and confirm it fails**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_state.SuccessfulTransitionTests.test_success_path_advances_zero_to_three -v`

Expected: FAIL because `submit_stage` does not exist.

- [ ] **Step 3: Implement execution metadata whitelisting and profile verification**

Persist only these stable fields when present:

```python
LOCAL_EXECUTION_FIELDS = (
    "requested_model", "requested_reasoning", "reported_model", "reported_reasoning",
    "verification", "thread_id", "driver_context_id", "packet_digest", "profile_id",
    "codex_home", "codex_sqlite_home", "codex_binary_realpath", "codex_binary_sha256",
    "app_server_version", "workspace_access",
)
EXECUTION_TELEMETRY_FIELDS = ("duration_ms",)
WEB_EXECUTION_FIELDS = (
    "driver_context_id", "web_context_ref", "context_mode", "context_scope",
    "context_isolation", "model_claimed", "reasoning_claimed", "verification", "packet_digest",
)
OFFLINE_EXECUTION_FIELDS = (
    "driver_context_id", "packet_digest", "verification", "network_used",
)
```

For `driver_type="codex_app"`, require Local Sol and Luna execution profile ID, `codex_home`, `codex_sqlite_home`, binary realpath, driver context, and `workspace_access="read_only"` to equal canonical state. Require `verification="app_server_reported"`; allow `reported_reasoning=None` but never synthesize it. For Web require `context_mode="continuous"`, `context_scope="driver_context_id"`, `context_isolation="operator_managed"`, and `verification="operator_attested"`. For `driver_type="offline_pipeline"`, accept only `verification="fake_offline"`, `network_used=False`, the current driver context, and current packet digest; this exception exists only so the fake command can exercise the same transition functions without pretending to be App Server evidence. Accept `duration_ms` only as a finite non-negative number under a separate `telemetry` object; store it in canonical history/projections but exclude it from submission and failure digests so an identical retry with a different duration remains idempotent.

- [ ] **Step 4: Implement locked validation, idempotency-first ordering, and transition construction**

Inside `_exclusive_run_lock(run_dir)`:

```python
normalized = normalize_content(content)
stable_execution, telemetry = _normalize_execution(stage, execution, state)
incoming_digest = submission_digest(
    driver_context_id, run_id, stage, packet_digest_value, normalized, stable_execution
)
existing = state["submissions"].get(stage)
if existing is not None:
    if existing["submission_digest"] == incoming_digest:
        return _result(run_dir, state, idempotent=True)
    raise RouterStateError("conflict", "stage already has different content", run_id=run_id, stage=stage, revision=state["revision"])
if state["failures"].get(stage) is not None or state["status"] in {"completed", "failed"}:
    raise RouterStateError("conflict", "run is terminal or stage already failed", run_id=run_id, stage=stage, revision=state["revision"])
```

Then validate driver context, current stage, expected revision, and exact `state["next_packet"]["packet_digest"]`. For Web call `validate_web_response()` and translate `ProtocolError` to `RouterStateError(code="marker-mismatch")`.

Store the accepted packet inside the submission record so all packet projections remain rebuildable. Packet payload keys are fixed: Local Sol uses `task`, `role`, `permission`, `execution_profile`, and `output_contract`; Web Sol adds `local_sol_output` and `response_marker_contract`; Luna includes `task`, `local_sol_output`, `web_sol_output`, `role`, `permission`, and `output_contract`. The Web payload carries the marker format and required fields, not the final marker string: the exact marker is derived by `web_response_marker(packet)` only after `packet_digest` exists, preventing a circular digest dependency. It is not an additional packet field. For Luna, store `final_result=normalized`, set `status="completed"`, `revision=3`, `next_stage=None`, and `next_packet=None` in the same new state before `_commit_state()`.

- [ ] **Step 5: Add failing idempotency and illegal-transition tests**

Cover these exact cases:

```python
def test_identical_terminal_luna_retry_is_idempotent_without_rewrite(self):
    completed, args = self.complete_run()
    before = (completed.run_dir / "state.json").read_bytes()
    with patch("codex_router.state._commit_state") as commit:
        repeated = submit_stage(**args)
    commit.assert_not_called()
    self.assertTrue(repeated.idempotent)
    self.assertEqual(repeated.revision, 3)
    self.assertEqual(before, (completed.run_dir / "state.json").read_bytes())

def test_different_duplicate_conflicts_before_revision_check(self):
    first, args = self.submit_local()
    args.update(content="different", expected_revision=0)
    with self.assertRaises(RouterStateError) as raised:
        submit_stage(**args)
    self.assertEqual(raised.exception.code, "conflict")
```

Also test skip, reverse, wrong driver, wrong packet digest, stale revision for a not-yet-submitted stage, submission after `completed`, and a Web marker with the wrong packet ID.

- [ ] **Step 6: Implement deterministic projections and degraded-success reporting**

`_rebuild_projections()` must derive:

- `request.json` from `state["request"]` and run identity;
- one `packets/<packet_id>.json` for every accepted submission packet plus `next_packet`;
- `local-sol.json`, `web-sol.json`, and `luna.json` from accepted submissions or failures;
- `events.jsonl` from canonical `history` using canonical JSON per line;
- `result.json` only when `status == "completed"`.

Call `_commit_state()` first. Catch projection `OSError`, return the successful transition with `projection_warnings=("projection-rebuild-failed",)`, and do not revert state. `get_status()` always takes the exclusive run lock, rebuilds missing or divergent projections, and never changes state or revision.

- [ ] **Step 7: Add crash-window, projection repair, and concurrent writer tests**

Use `unittest.mock.patch` to make `_rebuild_projections` raise after `_commit_state`; assert canonical revision advanced and `get_status()` recreates projections. Patch `_commit_state` to raise before `os.replace`; assert the old state remains valid and revision is unchanged.

Use two `multiprocessing.Process` workers submitting Local Sol with revision `0` and different content. Assert exactly one exits successfully, the other returns `conflict`, and final revision is `1` with one Local Sol submission.

- [ ] **Step 8: Run the complete state success suite**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_state.SuccessfulTransitionTests tests.test_state.ConcurrencyAndDurabilityTests -v`

Expected: all transition, idempotency, projection, crash-window, and concurrency tests PASS.

- [ ] **Step 9: Commit successful transitions**

```bash
git add src/codex_router/state.py tests/test_state.py
git commit -m "feat(router): add locked stage transitions"
```

### Task 4: Explicit Failure Transitions and Sanitized Evidence

**Files:**
- Modify: `src/codex_router/state.py`
- Modify: `tests/test_state.py`

**Interfaces:**
- Consumes: Task 1 `failure_digest()` and Task 3 transition/error machinery.
- Produces: `fail_stage(*, state_root, run_id, driver_context_id, stage, expected_revision, packet_digest_value, failure, execution) -> TransitionResult`.

- [ ] **Step 1: Add failing failure-transition and terminal-idempotency tests**

```python
from codex_router.state import fail_stage


class FailureTransitionTests(RouterStateTestCase):
    def fail_local(self):
        started = self.start()
        packet = self.read_state()["next_packet"]
        args = {
            "state_root": self.state_root,
            "run_id": started.run_id,
            "driver_context_id": DRIVER_CONTEXT_ID,
            "stage": "local_sol",
            "expected_revision": 0,
            "packet_digest_value": packet["packet_digest"],
            "failure": {"code": "app-server-error", "summary": "local stage failed"},
            "execution": self.local_execution(),
        }
        return fail_stage(**args), args

    def test_current_stage_can_fail_and_becomes_terminal(self):
        started = self.start()
        failed = fail_stage(
            state_root=self.state_root,
            run_id=started.run_id,
            driver_context_id="ctx-550e8400-e29b-41d4-a716-446655440000",
            stage="local_sol",
            expected_revision=0,
            packet_digest_value=self.read_state()["next_packet"]["packet_digest"],
            failure={"code": "app-server-error", "summary": "local stage failed"},
            execution=self.local_execution(),
        )
        self.assertEqual((failed.status, failed.revision, failed.next_stage), ("failed", 1, None))
        self.assertEqual(self.read_state()["failed_stage"], "local_sol")
        self.assertFalse((failed.run_dir / "web-sol.json").exists())

    def test_identical_failure_retry_is_idempotent_but_changed_failure_conflicts(self):
        failed, args = self.fail_local()
        self.assertTrue(fail_stage(**args).idempotent)
        args["failure"] = {"code": "changed", "summary": "different"}
        with self.assertRaises(RouterStateError) as raised:
            fail_stage(**args)
        self.assertEqual(raised.exception.code, "conflict")
```

- [ ] **Step 2: Run the failure tests and confirm they fail**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_state.FailureTransitionTests -v`

Expected: FAIL because `fail_stage` does not exist.

- [ ] **Step 3: Implement bounded failure normalization and redaction**

```python
def _sanitize_failure(value: Mapping[str, Any]) -> dict[str, str]:
    code = str(value.get("code", "stage-failed"))[:64]
    summary = " ".join(str(value.get("summary", "stage failed")).splitlines())[:500]
    for pattern in SECRET_PATTERNS:
        summary = re.sub(pattern, _redacted_match, summary)
    return {"code": code or "stage-failed", "summary": summary or "stage failed"}
```

Discard all unrecognized failure keys. Never persist environment mappings, stack traces, authorization headers, cookies, tokens, account identifiers, temporary paths, or arbitrary exception representations.

- [ ] **Step 4: Implement `fail_stage()` with success-symmetric ordering**

Under the per-run exclusive lock:

1. Normalize execution and failure, then compute `failure_digest`.
2. If the same stage failure digest exists, return idempotently without a write.
3. If a different failure or a success exists for the stage, return `conflict`.
4. Reject terminal state, wrong driver, wrong current stage, stale revision, or wrong packet.
5. Store the accepted packet and failure record, set `status="failed"`, `revision=N+1`, `next_stage=None`, `next_packet=None`, and `failed_stage=stage` in one canonical commit.
6. Rebuild projections after commit with the same degraded-success warning semantics as `submit_stage()`.

- [ ] **Step 5: Add failure security and illegal-stage tests**

Test failure attempts for a non-current stage, wrong driver, stale revision, wrong packet, a success after failure, a second different failure after failure, and secret-like inputs:

```python
failure = {
    "code": "provider-error",
    "summary": "Authorization: Bearer router-secret-123\npassword=hunter2",
    "environment": {"API_KEY": "must-never-persist"},
}
```

Assert none of `router-secret-123`, `hunter2`, `must-never-persist`, `API_KEY`, or `environment` occurs in any file under the run directory.

- [ ] **Step 6: Run and commit the failure unit**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_state.FailureTransitionTests -v`

Expected: all failure transition, idempotency, ordering, and redaction tests PASS.

```bash
git add src/codex_router/state.py tests/test_state.py
git commit -m "feat(router): add explicit failed runs"
```

### Task 5: App-Driver CLI Contract and Stable JSON Errors

**Files:**
- Modify: `src/codex_router/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 2-4 public domain functions and `RouterStateError`.
- Produces: CLI subcommands `start`, `submit-stage`, `fail-stage`, and `status`, plus stable JSON stdout/error schemas.

- [ ] **Step 1: Add failing parser and `start` CLI tests**

```python
def test_start_returns_revision_zero_json(self):
    with tempfile.TemporaryDirectory() as tmp:
        binary = Path(tmp) / "codex"
        binary.write_text("binary")
        binary.chmod(0o700)
        completed = self.cli(
            "start",
            "--task", "review",
            "--driver-context-id", "ctx-550e8400-e29b-41d4-a716-446655440000",
            "--state-dir", str(Path(tmp) / "runs"),
            "--codex-bin", str(binary),
            "--local-model", "gpt-5.6-sol",
            "--local-reasoning", "max",
            "--web-model", "sol",
            "--web-reasoning", "xhigh",
            "--luna-model", "gpt-5.6-luna",
            "--luna-reasoning", "max",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual((payload["status"], payload["revision"], payload["next_stage"]), ("awaiting_local_sol", 0, "local_sol"))
        self.assertTrue(Path(payload["stage_packet_path"]).is_file())
```

- [ ] **Step 2: Run the start CLI test and confirm it fails**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_cli.RouterCliTests.test_start_returns_revision_zero_json -v`

Expected: FAIL because `start` is not a recognized subcommand.

- [ ] **Step 3: Add CLI parsers and shared JSON serialization**

Add exact arguments:

- `start`: task, driver context ID, state dir, absolute codex binary, and six model/reasoning role options.
- `submit-stage`: run ID, driver context ID, state dir, stage, expected revision, packet digest, UTF-8 output file, and JSON execution file.
- `fail-stage`: run ID, driver context ID, state dir, stage, expected revision, packet digest, JSON error file, and JSON execution file.
- `status`: run ID and state dir.

Serialize successful domain results as:

```python
def _result_payload(result: TransitionResult) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "revision": result.revision,
        "status": result.status,
        "next_stage": result.next_stage,
        "stage_packet_path": str(result.stage_packet_path) if result.stage_packet_path else None,
        "idempotent": result.idempotent,
        "projection_warnings": list(result.projection_warnings),
    }
```

Print JSON with `ensure_ascii=False` and `sort_keys=True`. Reject malformed UTF-8/JSON and non-object execution/error files as `invalid-input` without printing file contents.

- [ ] **Step 4: Add failing CLI lifecycle and error-code tests**

Drive this exact offline sequence from `test_cli.py`:

1. `start` and read the Local packet.
2. `submit-stage local_sol` with revision `0` and a local execution JSON file.
3. Read the Web packet, prepend its exact marker to Web output, and `submit-stage web_sol` with revision `1`.
4. `submit-stage luna` with revision `2`.
5. `status` and assert `completed@3` and no next packet.
6. Repeat Luna identically and assert exit `0`, `idempotent=true`, revision `3`.
7. Repeat Luna with different content and assert exit `20`, stderr code `conflict`.

Also assert `revision-mismatch` exits `22`, packet mismatch exits `23`, marker mismatch exits `24`, malformed input exits `25`, and missing run exits `26`.

Use concrete test helpers rather than duplicating command assembly:

```python
from codex_router.protocol import web_response_marker

DRIVER_CONTEXT_ID = "ctx-550e8400-e29b-41d4-a716-446655440000"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def app_execution(state, stage, packet):
    if stage == "web_sol":
        return {
            "driver_context_id": DRIVER_CONTEXT_ID,
            "web_context_ref": "web-context-cli-test",
            "context_mode": "continuous",
            "context_scope": "driver_context_id",
            "context_isolation": "operator_managed",
            "model_claimed": "sol",
            "reasoning_claimed": "xhigh",
            "verification": "operator_attested",
            "packet_digest": packet["packet_digest"],
        }
    profile = state["profiles"][stage]
    role = state["role_config"][stage]
    return {
        "requested_model": role["requested_model"],
        "requested_reasoning": role["requested_reasoning"],
        "reported_model": role["requested_model"],
        "reported_reasoning": role["requested_reasoning"],
        "verification": "app_server_reported",
        "thread_id": f"thread-{stage}",
        "driver_context_id": DRIVER_CONTEXT_ID,
        "packet_digest": packet["packet_digest"],
        "profile_id": profile["profile_id"],
        "codex_home": profile["codex_home"],
        "codex_sqlite_home": profile["codex_sqlite_home"],
        "codex_binary_realpath": profile["codex_binary_realpath"],
        "codex_binary_sha256": profile["codex_binary_sha256"],
        "app_server_version": "test-version",
        "workspace_access": "read_only",
    }
```

The lifecycle test body uses actual files and records the Luna retry arguments:

```python
def test_app_driver_cli_lifecycle_and_terminal_idempotency(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        state_root = root / "runs"
        binary = root / "codex"
        binary.write_text("binary", encoding="utf-8")
        binary.chmod(0o700)
        started = self.cli(
            "start", "--task", "review", "--driver-context-id", DRIVER_CONTEXT_ID,
            "--state-dir", str(state_root), "--codex-bin", str(binary),
            "--local-model", "gpt-5.6-sol", "--local-reasoning", "max",
            "--web-model", "sol", "--web-reasoning", "xhigh",
            "--luna-model", "gpt-5.6-luna", "--luna-reasoning", "max",
        )
        self.assertEqual(started.returncode, 0, started.stderr)
        current = json.loads(started.stdout)
        run_dir = state_root / current["run_id"]

        retry_args = None
        for stage, content in (("local_sol", "local result"), ("web_sol", "web result"), ("luna", "final result")):
            packet = json.loads(Path(current["stage_packet_path"]).read_text(encoding="utf-8"))
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            if stage == "web_sol":
                content = web_response_marker(packet) + "\n" + content
            output_file = root / f"{stage}.txt"
            execution_file = root / f"{stage}-execution.json"
            output_file.write_text(content, encoding="utf-8")
            write_json(execution_file, app_execution(state, stage, packet))
            args = (
                "submit-stage", "--run-id", current["run_id"],
                "--driver-context-id", DRIVER_CONTEXT_ID, "--state-dir", str(state_root),
                "--stage", stage, "--expected-revision", str(current["revision"]),
                "--packet-digest", packet["packet_digest"], "--output-file", str(output_file),
                "--execution-file", str(execution_file),
            )
            completed = self.cli(*args)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            current = json.loads(completed.stdout)
            if stage == "luna":
                retry_args = args

        status = self.cli("status", "--run-id", current["run_id"], "--state-dir", str(state_root))
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual((current["status"], current["revision"], current["next_stage"]), ("completed", 3, None))

        repeated = self.cli(*retry_args)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertTrue(json.loads(repeated.stdout)["idempotent"])
        (root / "luna.txt").write_text("different final", encoding="utf-8")
        conflict = self.cli(*retry_args)
        self.assertEqual(conflict.returncode, 20)
        self.assertEqual(json.loads(conflict.stderr)["code"], "conflict")
```

Lock the state-error-to-exit mapping without repeating the lifecycle setup:

```python
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

from codex_router import cli as cli_module
from codex_router.state import RouterStateError


def test_state_error_codes_have_stable_cli_exit_codes(self):
    expected = {
        "conflict": 20,
        "invalid-transition": 21,
        "revision-mismatch": 22,
        "packet-mismatch": 23,
        "marker-mismatch": 24,
        "invalid-input": 25,
        "run-not-found": 26,
        "unsafe-state-root": 27,
        "state-corrupt": 28,
        "profile-mismatch": 29,
    }
    for error_code, exit_code in expected.items():
        with self.subTest(error_code=error_code):
            error = RouterStateError(error_code, "bounded message", run_id="run-test", revision=1)
            stderr = StringIO()
            with patch.object(cli_module, "get_status", side_effect=error):
                with redirect_stderr(stderr):
                    actual = cli_module.main(["status", "--run-id", "run-test", "--state-dir", "/tmp/router-cli-test"])
            self.assertEqual(actual, exit_code)
            self.assertEqual(json.loads(stderr.getvalue())["code"], error_code)
```

Add four focused integration assertions to the lifecycle fixture: mutate only `expected_revision` and expect `22`; mutate only packet digest and expect `23`; replace the first Web marker line and expect `24`; write invalid JSON to an execution file and expect `25`. A separate `status --run-id run-missing` assertion expects `26`.

- [ ] **Step 5: Implement the stable CLI error schema**

```python
except RouterStateError as error:
    print(json.dumps({
        "status": "error",
        "code": error.code,
        "message": str(error),
        "run_id": error.run_id,
        "stage": error.stage,
        "revision": error.revision,
    }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    return error.exit_code
```

Keep `argparse` usage errors at exit `2`. Preserve existing `run` success output and `RouterRunError` exit `1` behavior.

- [ ] **Step 6: Run and commit the CLI unit**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_cli -v`

Expected: App-driven lifecycle tests and both existing fake/real-mode tests PASS.

```bash
git add src/codex_router/cli.py tests/test_cli.py
git commit -m "feat(router): add app-driver CLI"
```

### Task 6: Refactor Fake Mode onto the Canonical State Machine

**Files:**
- Modify: `src/codex_router/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `start_run`, `submit_stage`, `fail_stage`, `get_status`, and Web marker functions.
- Produces: existing `Router.run(task: str) -> RunOutcome` behavior implemented only through the canonical domain API.

- [ ] **Step 1: Add a failing shared-state fake-mode test**

```python
def test_fake_pipeline_persists_canonical_revision_three_state(self):
    with tempfile.TemporaryDirectory() as tmp:
        router, calls, _ = self.build_router(Path(tmp))
        outcome = router.run("Return exactly ROUTER_MVP_OK")
        state = json.loads((outcome.run_dir / "state.json").read_text())
        self.assertEqual([call[0] for call in calls], ["local_sol", "web_sol", "luna"])
        self.assertEqual((state["status"], state["revision"], state["final_result"]), ("completed", 3, "ROUTER_MVP_OK"))
        self.assertEqual(set(state["submissions"]), {"local_sol", "web_sol", "luna"})
```

- [ ] **Step 2: Run the focused pipeline test and confirm it fails**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_pipeline.RouterPipelineTests.test_fake_pipeline_persists_canonical_revision_three_state -v`

Expected: FAIL because the old pipeline has no `state.json`.

- [ ] **Step 3: Refactor `Router.run()` into a synchronous fake/custom driver**

Use one generated canonical UUID `driver_context_id`, a fake executable created at `state_root / ".profiles" / driver_context_id / "offline-codex"`, and role configuration with `verification="fake_offline"`. Call:

```python
driver_context_id = f"ctx-{uuid.uuid4()}"
fake_binary = self.state_root / ".profiles" / driver_context_id / "offline-codex"
fake_binary.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
fake_binary.write_text("offline pipeline marker\n", encoding="utf-8")
fake_binary.chmod(0o700)
role_config = {
    "local_sol": {"requested_model": "fake-local-sol", "requested_reasoning": "offline"},
    "web_sol": {"model_claimed": "fake-web-sol", "reasoning_claimed": "offline", "verification": "fake_offline"},
    "luna": {"requested_model": "fake-luna", "requested_reasoning": "offline"},
}
transition = start_run(
    state_root=self.state_root,
    task=task,
    driver_context_id=driver_context_id,
    role_config=role_config,
    codex_binary=fake_binary.resolve(),
    driver_type="offline_pipeline",
)
context = {"run_id": transition.run_id, "task": task}
for stage in STAGES:
    packet = json.loads(transition.stage_packet_path.read_text(encoding="utf-8"))
    context = _adapter_context_from_packet(packet)
    started = time.perf_counter()
    try:
        with _timeout(self.timeout_seconds):
            stage_result = self.adapters[stage].run(task, context.copy())
        _validate_stage_result(stage, stage_result)
    except Exception as error:
        duration = round((time.perf_counter() - started) * 1000, 3)
        fail_stage(
            state_root=self.state_root,
            run_id=transition.run_id,
            driver_context_id=driver_context_id,
            stage=stage,
            expected_revision=transition.revision,
            packet_digest_value=packet["packet_digest"],
            failure={"code": "stage-timeout" if isinstance(error, StageTimedOut) else "adapter-error", "summary": _safe_error(error)},
            execution=_fake_execution(stage, driver_context_id, packet, duration_ms=duration),
        )
        raise RouterRunError(
            transition.run_id,
            transition.run_dir,
            stage,
            "stage-timeout" if isinstance(error, StageTimedOut) else "adapter-error",
            _safe_error(error),
        ) from error
    duration = round((time.perf_counter() - started) * 1000, 3)
    content = stage_result.content
    if stage == "web_sol":
        content = web_response_marker(packet) + "\n" + content
    transition = submit_stage(
        state_root=self.state_root,
        run_id=transition.run_id,
        driver_context_id=driver_context_id,
        stage=stage,
        expected_revision=transition.revision,
        packet_digest_value=packet["packet_digest"],
        content=content,
        execution=_fake_execution(stage, driver_context_id, packet, duration_ms=duration),
)
```

Define the two helpers completely:

```python
def _fake_execution(stage, driver_context_id, packet, *, duration_ms):
    return {
        "driver_context_id": driver_context_id,
        "packet_digest": packet["packet_digest"],
        "verification": "fake_offline",
        "network_used": False,
        "duration_ms": duration_ms,
    }


def _adapter_context_from_packet(packet):
    payload = packet["payload"]
    context = {"run_id": packet["run_id"], "task": payload["task"]}
    if packet["target_stage"] == "web_sol":
        context["handoff"] = make_handoff(packet["run_id"], "local_sol", payload["local_sol_output"])
    elif packet["target_stage"] == "luna":
        web_lines = payload["web_sol_output"].splitlines()
        semantic_web_output = "\n".join(web_lines[1:])
        context["handoff"] = make_handoff(packet["run_id"], "web_sol", semantic_web_output)
    return context
```

The adapter context is a projection of the cumulative canonical packet, not a second workflow state machine. The helper strips the Web marker before passing semantic output to Luna while the exact accepted Web content remains in canonical state.

- [ ] **Step 4: Preserve `BaseException` propagation and fail-closed real mode**

Keep the adapter boundary as `except Exception`, so `KeyboardInterrupt` and `SystemExit` are never converted to `RouterRunError` or recorded as ordinary failures. `UnconfiguredAdapter` must still produce `provider-not-configured` on stderr and exit `1`; do not add a model or network call.

Add this explicit companion to the existing keyboard-interrupt test:

```python
def test_system_exit_propagates_without_running_downstream_stages(self):
    with tempfile.TemporaryDirectory() as tmp:
        router, calls, _ = self.build_router(Path(tmp))
        _, _, StageResult = load_pipeline_api(self)
        router.adapters["local_sol"] = RecordingAdapter(
            "local_sol", calls, StageResult, failure=SystemExit(7)
        )
        with self.assertRaises(SystemExit) as raised:
            router.run("exit locally")
        self.assertEqual(raised.exception.code, 7)
        self.assertEqual([call[0] for call in calls], ["local_sol"])
```

- [ ] **Step 5: Update persistence assertions without weakening existing tests**

Require `state.json` in `test_run_directory_and_final_result_are_persisted`. Keep assertions for request, stage, result, and events projections. Add a test that deletes `result.json`, calls `get_status()`, and verifies exact deterministic recreation.

- [ ] **Step 6: Run all pipeline and CLI compatibility tests**

Run: `PYTHONPATH=src python3.12 -m unittest tests.test_pipeline tests.test_cli -v`

Expected: all tests PASS; fake stdout remains exactly `ROUTER_MVP_OK`; real mode remains non-zero with `provider-not-configured`; `KeyboardInterrupt` and `SystemExit` propagate.

- [ ] **Step 7: Commit the shared-state fake driver**

```bash
git add src/codex_router/pipeline.py tests/test_pipeline.py
git commit -m "refactor(router): share canonical workflow state"
```

### Task 7: Documentation, CI Branch Coverage, and Final Verification

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/ci.yml`
- Modify: tests only if final validation exposes a missing assertion; do not change behavior to silence a failing test.

**Interfaces:**
- Consumes: all completed domain and CLI behavior.
- Produces: operator documentation and repository validation evidence; no new runtime API.

- [ ] **Step 1: Update README with the exact authority and recovery model**

Document:

- Codex App drives Local Sol, the continuous in-app Web Sol conversation, and local Luna.
- Router alone creates `run_id`, validates packets/revisions/digests, persists state, and chooses `next_stage`.
- All V1 target-workspace access is read-only.
- Same-Codex-conversation runs reuse one App-managed Web context through `driver_context_id`; a new Codex conversation must not inherit it.
- Web model/reasoning/context are `operator_attested`; Local/Luna requested and App Server-reported values are separate.
- Recovery uses `router status`, canonical `state.json`, and regenerated projections rather than chat memory.
- The four App-driver command examples, including absolute `--codex-bin`, explicit state directory, revision, packet digest, and execution files.
- Failed runs are terminal; starting a new run is the only retry.
- Router runtime does not depend on GitHub, while real model stages still depend on approved OpenAI/ChatGPT service capacity.

- [ ] **Step 2: Add the new feature branch to push CI**

Change only the push branch list:

```yaml
on:
  pull_request:
  push:
    branches:
      - main
      - feat/app-orchestrated-real-router-v1
```

Keep `permissions: contents: read`, Python 3.12, the repository-scoped `[self-hosted, Linux, ARM64, codex-router-ci]` runner, unit tests, compileall, and exact fake smoke assertion. Do not add GitHub-hosted runners, matrices, services, caches, secrets, or provider calls.

- [ ] **Step 3: Run the complete Python 3.12 test suite**

Run: `PYTHONPATH=src python3.12 -m unittest discover -s tests -v`

Expected: all tests PASS with exit `0`.

- [ ] **Step 4: Run bytecode and patch hygiene checks**

Run: `python3.12 -m compileall -q src tests`

Expected: exit `0` and no output.

Run: `git diff --check`

Expected: exit `0` and no output.

- [ ] **Step 5: Run the installed fake smoke test in a temporary Python 3.12 environment**

```bash
smoke_dir="$(mktemp -d)"
python3.12 -m venv "$smoke_dir/venv"
"$smoke_dir/venv/bin/python" -m pip install -e .
output="$($smoke_dir/venv/bin/router run --task "Return exactly ROUTER_MVP_OK" --adapter-mode fake --state-dir "$smoke_dir/state")"
test "$output" = "ROUTER_MVP_OK"
```

Expected: exit `0`; stdout is exactly `ROUTER_MVP_OK`.

- [ ] **Step 6: Verify real mode still fails closed without a provider**

```bash
real_state="$(mktemp -d)"
if router run --task "do real work" --adapter-mode real --state-dir "$real_state" >"$real_state/stdout" 2>"$real_state/stderr"; then
  exit 1
fi
rg -q 'provider-not-configured' "$real_state/stderr"
```

Expected: the Router command is non-zero, stdout is empty, and stderr contains `provider-not-configured`.

- [ ] **Step 7: Inspect the final scope and scan the staged delivery**

Run: `git status --short`

Expected: only the planned source, tests, README, workflow, and plan/spec files are changed.

Run after staging the intended files: `gitleaks protect --staged --redact`

Expected: no leaks found.

- [ ] **Step 8: Commit documentation and validation wiring**

```bash
git add README.md .github/workflows/ci.yml
git commit -m "docs(router): document App-driven workflow"
```

- [ ] **Step 9: Record final local evidence without remote mutation**

Record branch, base SHA, final HEAD, `git status --short`, commit list, exact test count, compile result, smoke output, real-mode exit/result, and remaining operator-attested limitations. Stop before push, PR creation, CI runner startup, or merge unless the user explicitly authorizes those actions.

---

## Plan Self-Review Checklist

- Every design section is implemented by Tasks 1-7: authority, state machine, locking, durability, profiles, digests, marker, idempotency, projections, CLI, failures, fake compatibility, security, tests, and non-goals.
- `canonical_json_bytes`, packet/submission/failure digests, state schema, and CLI names are consistent across tasks.
- The App-driver path never calls a browser or model; it accepts externally executed stage evidence and validates it.
- The plan contains no dependency addition, database, daemon, browser bridge, retry, target-workspace write, archive/delete flow, or GitHub runtime dependency.
- The plan stops before remote delivery and requires fresh authorization for push, PR, runner startup, or merge.
