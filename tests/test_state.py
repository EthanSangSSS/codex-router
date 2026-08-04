import json
import multiprocessing
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from codex_router.protocol import digest_json, web_response_marker


DRIVER_CONTEXT_ID = "ctx-550e8400-e29b-41d4-a716-446655440000"
ROLE_CONFIG = {
    "local_sol": {
        "requested_model": "gpt-5.6-sol",
        "requested_reasoning": "max",
    },
    "web_sol": {
        "model_claimed": "sol",
        "reasoning_claimed": "xhigh",
        "verification": "operator_attested",
    },
    "luna": {
        "requested_model": "gpt-5.6-luna",
        "requested_reasoning": "max",
    },
}


def load_state_api(testcase):
    try:
        from codex_router.state import RouterStateError, get_status, start_run
    except ImportError:
        testcase.fail("codex_router canonical state API is not implemented")
    return RouterStateError, get_status, start_run


def load_transition_api(testcase):
    try:
        from codex_router.state import RouterStateError, get_status, start_run, submit_stage
    except ImportError:
        testcase.fail("codex_router submit-stage API is not implemented")
    return RouterStateError, get_status, start_run, submit_stage


def load_failure_api(testcase):
    try:
        from codex_router.state import RouterStateError, fail_stage, submit_stage
    except ImportError:
        testcase.fail("codex_router fail-stage API is not implemented")
    return RouterStateError, fail_stage, submit_stage


def concurrent_submit_worker(queue, arguments):
    try:
        from codex_router.state import submit_stage

        result = submit_stage(**arguments)
        queue.put(("ok", result.revision))
    except Exception as error:
        queue.put((getattr(error, "code", type(error).__name__), None))


class RunCreationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state_root = self.root / "runs"
        self.binary = self.root / "codex"
        self.binary.write_text("test binary", encoding="utf-8")
        self.binary.chmod(0o700)

    def start(self):
        _, _, start_run = load_state_api(self)
        return start_run(
            state_root=self.state_root,
            task="review",
            driver_context_id=DRIVER_CONTEXT_ID,
            role_config=ROLE_CONFIG,
            codex_binary=self.binary,
        )

    def test_start_creates_revision_zero_state_profiles_and_projections(self):
        result = self.start()
        state_path = result.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(
            (state["status"], state["revision"], state["next_stage"]),
            ("awaiting_local_sol", 0, "local_sol"),
        )
        self.assertEqual(state["driver"]["driver_context_id"], DRIVER_CONTEXT_ID)
        self.assertEqual(state["driver"]["driver_type"], "codex_app")
        self.assertEqual(state["next_packet"]["target_stage"], "local_sol")
        self.assertEqual(result.stage_packet_path.name, f"{state['next_packet']['packet_id']}.json")
        self.assertTrue(result.stage_packet_path.is_file())
        self.assertTrue((result.run_dir / "request.json").is_file())
        self.assertTrue((result.run_dir / "events.jsonl").is_file())
        self.assertEqual(stat.S_IMODE(result.run_dir.stat().st_mode), 0o700)
        root_marker = self.state_root / ".codex-router-root.json"
        self.assertTrue(root_marker.is_file())
        self.assertEqual(stat.S_IMODE(self.state_root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(root_marker.stat().st_mode), 0o600)
        self.assertEqual(
            json.loads(root_marker.read_text(encoding="utf-8"))["protocol"],
            "codex-router/state-root/v1",
        )
        for file_path in (
            state_path,
            result.run_dir / ".lock",
            result.stage_packet_path,
            result.run_dir / "request.json",
            result.run_dir / "events.jsonl",
        ):
            self.assertEqual(stat.S_IMODE(file_path.stat().st_mode), 0o600, file_path)

        for stage in ("local_sol", "luna"):
            profile = state["profiles"][stage]
            self.assertNotEqual(Path(profile["codex_home"]).resolve(), Path.home() / ".codex")
            self.assertEqual(Path(profile["codex_binary_realpath"]), self.binary.resolve())
            marker = Path(profile["ownership_marker"])
            self.assertTrue(marker.is_file())
            self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
            marker_data = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(marker_data["workspace_access"], "read_only")
            self.assertEqual(marker_data["run_id"], result.run_id)

    def test_status_repairs_missing_projections_without_changing_state(self):
        _, get_status, _ = load_state_api(self)
        started = self.start()
        state_path = started.run_dir / "state.json"
        before = state_path.read_bytes()
        packet_path = started.stage_packet_path
        (started.run_dir / "request.json").unlink()
        (started.run_dir / "events.jsonl").unlink()
        packet_path.unlink()

        status = get_status(state_root=self.state_root, run_id=started.run_id)

        self.assertEqual((status.status, status.revision), ("awaiting_local_sol", 0))
        self.assertEqual(state_path.read_bytes(), before)
        self.assertTrue((started.run_dir / "request.json").is_file())
        self.assertTrue((started.run_dir / "events.jsonl").is_file())
        self.assertTrue(packet_path.is_file())

    def test_profiles_are_isolated_between_runs_in_one_driver_context(self):
        first = self.start()
        second = self.start()
        first_state = json.loads((first.run_dir / "state.json").read_text(encoding="utf-8"))
        second_state = json.loads((second.run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertNotEqual(first.run_id, second.run_id)
        for stage in ("local_sol", "luna"):
            self.assertNotEqual(
                first_state["profiles"][stage]["codex_home"],
                second_state["profiles"][stage]["codex_home"],
            )

    def test_run_id_collision_uses_a_new_directory(self):
        _, _, start_run = load_state_api(self)
        self.state_root.mkdir(mode=0o700)
        (self.state_root / "run-fixed").mkdir(mode=0o700)

        with patch("codex_router.state._new_run_id", side_effect=("run-fixed", "run-second")):
            result = start_run(
                state_root=self.state_root,
                task="review",
                driver_context_id=DRIVER_CONTEXT_ID,
                role_config=ROLE_CONFIG,
                codex_binary=self.binary,
            )

        self.assertEqual(result.run_id, "run-second")
        self.assertTrue((result.run_dir / "state.json").is_file())

    def test_existing_public_root_is_rejected_without_chmod(self):
        RouterStateError, _, start_run = load_state_api(self)
        self.state_root.mkdir(mode=0o755)

        with self.assertRaises(RouterStateError) as raised:
            start_run(
                state_root=self.state_root,
                task="review",
                driver_context_id=DRIVER_CONTEXT_ID,
                role_config=ROLE_CONFIG,
                codex_binary=self.binary,
            )

        self.assertEqual(raised.exception.code, "state-root-unowned")
        self.assertEqual(stat.S_IMODE(self.state_root.stat().st_mode), 0o755)
        self.assertFalse((self.state_root / ".codex-router-root.json").exists())

    def test_valid_marked_private_root_is_accepted(self):
        first = self.start()
        marker = self.state_root / ".codex-router-root.json"
        marker_before = marker.read_bytes()

        second = self.start()

        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(marker.read_bytes(), marker_before)
        self.assertEqual(stat.S_IMODE(self.state_root.stat().st_mode), 0o700)

    def test_private_legacy_router_root_is_marker_migrated_without_chmod(self):
        self.state_root.mkdir(mode=0o700)
        (self.state_root / ".profiles").mkdir(mode=0o700)
        before_mode = stat.S_IMODE(self.state_root.stat().st_mode)

        self.start()

        marker = self.state_root / ".codex-router-root.json"
        self.assertTrue(marker.is_file())
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.state_root.stat().st_mode), before_mode)

    def test_symlinked_state_root_is_rejected(self):
        RouterStateError, _, start_run = load_state_api(self)
        target = self.root / "real-state-root"
        target.mkdir(mode=0o700)
        self.state_root.symlink_to(target, target_is_directory=True)

        with self.assertRaises(RouterStateError) as raised:
            start_run(
                state_root=self.state_root,
                task="review",
                driver_context_id=DRIVER_CONTEXT_ID,
                role_config=ROLE_CONFIG,
                codex_binary=self.binary,
            )

        self.assertEqual(raised.exception.code, "state-root-unowned")
        self.assertTrue(self.state_root.is_symlink())
        self.assertFalse((target / ".codex-router-root.json").exists())

    def test_unrelated_existing_file_prevents_legacy_migration(self):
        RouterStateError, _, start_run = load_state_api(self)
        self.state_root.mkdir(mode=0o700)
        (self.state_root / "unrelated.txt").write_text("not Router state", encoding="utf-8")

        with self.assertRaises(RouterStateError) as raised:
            start_run(
                state_root=self.state_root,
                task="review",
                driver_context_id=DRIVER_CONTEXT_ID,
                role_config=ROLE_CONFIG,
                codex_binary=self.binary,
            )

        self.assertEqual(raised.exception.code, "state-root-unowned")
        self.assertFalse((self.state_root / ".codex-router-root.json").exists())

    def test_invalid_driver_context_id_is_rejected_without_writes(self):
        RouterStateError, _, start_run = load_state_api(self)

        with self.assertRaises(RouterStateError) as raised:
            start_run(
                state_root=self.state_root,
                task="review",
                driver_context_id="../../personal",
                role_config=ROLE_CONFIG,
                codex_binary=self.binary,
            )

        self.assertEqual(raised.exception.code, "invalid-input")
        self.assertFalse(self.state_root.exists())

    def test_live_codex_root_is_rejected_without_writes(self):
        RouterStateError, _, start_run = load_state_api(self)
        unsafe_root = Path.home() / ".codex" / "router-runs"

        with self.assertRaises(RouterStateError) as raised:
            start_run(
                state_root=unsafe_root,
                task="review",
                driver_context_id=DRIVER_CONTEXT_ID,
                role_config=ROLE_CONFIG,
                codex_binary=self.binary,
            )

        self.assertEqual(raised.exception.code, "unsafe-state-root")

    def test_relative_or_symlinked_binary_is_rejected(self):
        RouterStateError, _, start_run = load_state_api(self)
        symlink = self.root / "codex-link"
        symlink.symlink_to(self.binary)

        for binary in (Path("codex"), symlink):
            with self.subTest(binary=binary):
                with self.assertRaises(RouterStateError) as raised:
                    start_run(
                        state_root=self.state_root,
                        task="review",
                        driver_context_id=DRIVER_CONTEXT_ID,
                        role_config=ROLE_CONFIG,
                        codex_binary=binary,
                    )
                self.assertEqual(raised.exception.code, "invalid-input")

    def test_incomplete_run_directory_is_state_corrupt(self):
        RouterStateError, get_status, _ = load_state_api(self)
        run_dir = self.state_root / "run-incomplete"
        self.state_root.mkdir(mode=0o700)
        run_dir.mkdir(mode=0o700)

        with self.assertRaises(RouterStateError) as raised:
            get_status(state_root=self.state_root, run_id="run-incomplete")

        self.assertEqual(raised.exception.code, "state-corrupt")


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
        _, _, start_run, _ = load_transition_api(self)
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
            "duration_ms": 10,
            "ignored_environment": "must-not-persist",
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

    def submit(self, transition, stage, content, execution, **overrides):
        _, _, _, submit_stage = load_transition_api(self)
        packet = self.read_state()["next_packet"]
        arguments = {
            "state_root": self.state_root,
            "run_id": transition.run_id,
            "driver_context_id": DRIVER_CONTEXT_ID,
            "stage": stage,
            "expected_revision": transition.revision,
            "packet_digest_value": packet["packet_digest"],
            "content": content,
            "execution": execution,
        }
        arguments.update(overrides)
        return submit_stage(**arguments)

    def submit_local(self):
        _, _, _, submit_stage = load_transition_api(self)
        started = self.start()
        packet = self.read_state()["next_packet"]
        arguments = {
            "state_root": self.state_root,
            "run_id": started.run_id,
            "driver_context_id": DRIVER_CONTEXT_ID,
            "stage": "local_sol",
            "expected_revision": 0,
            "packet_digest_value": packet["packet_digest"],
            "content": "local result",
            "execution": self.local_execution(),
        }
        return submit_stage(**arguments), arguments

    def complete_run(self):
        _, _, _, submit_stage = load_transition_api(self)
        local, _ = self.submit_local()
        web_packet = self.read_state()["next_packet"]
        web = self.submit(
            local,
            "web_sol",
            web_response_marker(web_packet) + "\nweb result",
            self.web_execution(),
        )
        luna_packet = self.read_state()["next_packet"]
        arguments = {
            "state_root": self.state_root,
            "run_id": web.run_id,
            "driver_context_id": DRIVER_CONTEXT_ID,
            "stage": "luna",
            "expected_revision": 2,
            "packet_digest_value": luna_packet["packet_digest"],
            "content": "final result",
            "execution": self.luna_execution(),
        }
        return submit_stage(**arguments), arguments


class SuccessfulTransitionTests(RouterStateTestCase):
    def test_success_path_advances_zero_to_three_with_cumulative_packets(self):
        started = self.start()
        local = self.submit(started, "local_sol", "local result", self.local_execution())
        self.assertEqual(
            (local.status, local.revision, local.next_stage),
            ("awaiting_web_sol", 1, "web_sol"),
        )
        state = self.read_state()
        self.assertEqual(state["next_packet"]["payload"]["local_sol_output"], "local result")
        self.assertEqual(
            state["submissions"]["local_sol"]["execution"]["reported_model"],
            ROLE_CONFIG["local_sol"]["requested_model"],
        )

        web_packet = state["next_packet"]
        web_content = web_response_marker(web_packet) + "\nweb result"
        web = self.submit(local, "web_sol", web_content, self.web_execution())
        self.assertEqual(
            (web.status, web.revision, web.next_stage),
            ("awaiting_luna", 2, "luna"),
        )
        state = self.read_state()
        self.assertEqual(state["next_packet"]["payload"]["local_sol_output"], "local result")
        self.assertEqual(state["next_packet"]["payload"]["web_sol_output"], web_content)

        luna = self.submit(web, "luna", "final result", self.luna_execution())
        self.assertEqual((luna.status, luna.revision, luna.next_stage), ("completed", 3, None))
        state = self.read_state()
        self.assertEqual(state["final_result"], "final result")
        self.assertEqual(
            json.loads((luna.run_dir / "result.json").read_text(encoding="utf-8"))["result"],
            "final result",
        )
        self.assertNotIn("ignored_environment", (luna.run_dir / "state.json").read_text())

    def test_identical_terminal_luna_retry_is_idempotent_without_rewrite(self):
        RouterStateError, _, _, submit_stage = load_transition_api(self)
        completed, arguments = self.complete_run()
        before = (completed.run_dir / "state.json").read_bytes()
        arguments["execution"] = {**arguments["execution"], "duration_ms": 99}

        with patch("codex_router.state._commit_state") as commit:
            repeated = submit_stage(**arguments)

        commit.assert_not_called()
        self.assertTrue(repeated.idempotent)
        self.assertEqual(repeated.revision, 3)
        self.assertEqual(before, (completed.run_dir / "state.json").read_bytes())

        arguments.update(content="different final result", expected_revision=0)
        with self.assertRaises(RouterStateError) as raised:
            submit_stage(**arguments)
        self.assertEqual(raised.exception.code, "conflict")

    def test_different_duplicate_conflicts_before_revision_check(self):
        RouterStateError, _, _, submit_stage = load_transition_api(self)
        _, arguments = self.submit_local()
        arguments.update(content="different", expected_revision=99)

        with self.assertRaises(RouterStateError) as raised:
            submit_stage(**arguments)

        self.assertEqual(raised.exception.code, "conflict")

    def test_invalid_transition_revision_driver_packet_and_marker_are_classified(self):
        RouterStateError, _, _, submit_stage = load_transition_api(self)
        started = self.start()
        packet = self.read_state()["next_packet"]
        base = {
            "state_root": self.state_root,
            "run_id": started.run_id,
            "driver_context_id": DRIVER_CONTEXT_ID,
            "stage": "local_sol",
            "expected_revision": 0,
            "packet_digest_value": packet["packet_digest"],
            "content": "local result",
            "execution": self.local_execution(),
        }
        cases = (
            ({"stage": "web_sol"}, "invalid-transition"),
            ({"expected_revision": 1}, "revision-mismatch"),
            ({"driver_context_id": "ctx-00000000-0000-4000-8000-000000000000"}, "conflict"),
            ({"packet_digest_value": "sha256:" + "0" * 64}, "packet-mismatch"),
        )
        for changes, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                arguments = {**base, **changes}
                with self.assertRaises(RouterStateError) as raised:
                    submit_stage(**arguments)
                self.assertEqual(raised.exception.code, expected_code)

        local = submit_stage(**base)
        web_packet = self.read_state()["next_packet"]
        wrong_marker = web_response_marker(
            {**web_packet, "packet_id": "packet-wrong"}
        ) + "\nweb result"
        with self.assertRaises(RouterStateError) as raised:
            self.submit(local, "web_sol", wrong_marker, self.web_execution())
        self.assertEqual(raised.exception.code, "marker-mismatch")

    def test_profile_mismatch_is_rejected(self):
        RouterStateError, _, _, _ = load_transition_api(self)
        started = self.start()
        execution = self.local_execution()
        execution["codex_home"] = str(self.root / "wrong-home")

        with self.assertRaises(RouterStateError) as raised:
            self.submit(started, "local_sol", "local result", execution)

        self.assertEqual(raised.exception.code, "profile-mismatch")

    def test_app_server_reported_model_fields_are_required_and_nonempty(self):
        RouterStateError, _, _, _ = load_transition_api(self)
        cases = (
            ("reported_model", "missing"),
            ("reported_model", "empty"),
            ("reported_reasoning", "missing"),
            ("reported_reasoning", "empty"),
        )

        for field, mutation in cases:
            with self.subTest(field=field, mutation=mutation):
                started = self.start()
                execution = self.local_execution()
                if mutation == "missing":
                    execution.pop(field)
                else:
                    execution[field] = ""
                with self.assertRaises(RouterStateError) as raised:
                    self.submit(started, "local_sol", "local result", execution)
                self.assertEqual(raised.exception.code, "profile-mismatch")

    def test_null_reported_reasoning_and_mismatched_reported_model_are_preserved(self):
        started = self.start()
        execution = self.local_execution()
        execution["reported_model"] = "server-reported-different-model"
        execution["reported_reasoning"] = None

        self.submit(started, "local_sol", "local result", execution)

        persisted = self.read_state()["submissions"]["local_sol"]["execution"]
        self.assertEqual(persisted["reported_model"], "server-reported-different-model")
        self.assertIsNone(persisted["reported_reasoning"])
        self.assertEqual(persisted["requested_model"], ROLE_CONFIG["local_sol"]["requested_model"])

    def test_reverse_duplicate_conflicts_before_current_stage_validation(self):
        RouterStateError, _, _, submit_stage = load_transition_api(self)
        local, arguments = self.submit_local()
        arguments.update(content="changed local result", expected_revision=local.revision)

        with self.assertRaises(RouterStateError) as raised:
            submit_stage(**arguments)

        self.assertEqual(raised.exception.code, "conflict")


class CanonicalPacketIntegrityTests(RouterStateTestCase):
    def _rewrite_state(self, state):
        (self.started.run_dir / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def test_current_packet_tampering_is_state_corrupt(self):
        RouterStateError, get_status, _, _ = load_transition_api(self)
        cases = ("payload-old-digest", "target", "source-revision", "run-id", "malformed-digest")

        for mutation in cases:
            with self.subTest(mutation=mutation):
                started = self.start()
                state = self.read_state()
                packet = state["next_packet"]
                if mutation == "payload-old-digest":
                    packet["payload"]["task"] = "tampered task"
                elif mutation == "target":
                    packet["target_stage"] = "web_sol"
                elif mutation == "source-revision":
                    packet["source_revision"] = 7
                elif mutation == "run-id":
                    packet["run_id"] = "run-other"
                else:
                    packet["packet_digest"] = "malformed"
                if mutation in {"target", "source-revision", "run-id"}:
                    unsigned = {key: value for key, value in packet.items() if key != "packet_digest"}
                    packet["packet_digest"] = digest_json(unsigned)
                self._rewrite_state(state)

                with self.assertRaises(RouterStateError) as raised:
                    get_status(state_root=self.state_root, run_id=started.run_id)
                self.assertEqual(raised.exception.code, "state-corrupt")

    def test_accepted_packet_tampering_blocks_projection_repair(self):
        RouterStateError, get_status, _, _ = load_transition_api(self)
        transition, _ = self.submit_local()
        state = self.read_state()
        state["submissions"]["local_sol"]["packet"]["payload"]["task"] = "tampered task"
        self._rewrite_state(state)
        projection = transition.run_dir / "local-sol.json"
        projection.unlink()

        with self.assertRaises(RouterStateError) as raised:
            get_status(state_root=self.state_root, run_id=transition.run_id)

        self.assertEqual(raised.exception.code, "state-corrupt")
        self.assertFalse(projection.exists())


class ConcurrencyAndDurabilityTests(RouterStateTestCase):
    def test_completed_projections_are_rebuilt_without_changing_state(self):
        _, get_status, _, _ = load_transition_api(self)
        completed, _ = self.complete_run()
        before = (completed.run_dir / "state.json").read_bytes()
        state = self.read_state()
        paths = [
            completed.run_dir / "local-sol.json",
            completed.run_dir / "web-sol.json",
            completed.run_dir / "luna.json",
            completed.run_dir / "result.json",
            completed.run_dir
            / "packets"
            / f"{state['submissions']['web_sol']['packet']['packet_id']}.json",
        ]
        for path in paths:
            path.unlink()

        status = get_status(state_root=self.state_root, run_id=completed.run_id)

        self.assertEqual((status.status, status.revision), ("completed", 3))
        self.assertEqual((completed.run_dir / "state.json").read_bytes(), before)
        for path in paths:
            self.assertTrue(path.is_file(), path)

    def test_projection_failure_after_commit_is_degraded_success_and_repairable(self):
        _, get_status, _, _ = load_transition_api(self)
        started = self.start()
        with patch("codex_router.state._rebuild_projections", side_effect=OSError("disk")):
            result = self.submit(started, "local_sol", "local result", self.local_execution())

        self.assertEqual(result.revision, 1)
        self.assertEqual(result.projection_warnings, ("projection-rebuild-failed",))
        self.assertEqual(self.read_state()["revision"], 1)
        repaired = get_status(state_root=self.state_root, run_id=started.run_id)
        self.assertEqual(repaired.revision, 1)
        self.assertTrue((started.run_dir / "local-sol.json").is_file())

    def test_commit_failure_preserves_previous_state(self):
        _, _, _, _ = load_transition_api(self)
        started = self.start()
        before = (started.run_dir / "state.json").read_bytes()

        with patch("codex_router.state._commit_state", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.submit(started, "local_sol", "local result", self.local_execution())

        self.assertEqual((started.run_dir / "state.json").read_bytes(), before)

    def test_two_processes_produce_one_success_and_one_conflict(self):
        started = self.start()
        packet = self.read_state()["next_packet"]
        execution = self.local_execution()
        base = {
            "state_root": self.state_root,
            "run_id": started.run_id,
            "driver_context_id": DRIVER_CONTEXT_ID,
            "stage": "local_sol",
            "expected_revision": 0,
            "packet_digest_value": packet["packet_digest"],
            "execution": execution,
        }
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        workers = [
            context.Process(
                target=concurrent_submit_worker,
                args=(queue, {**base, "content": content}),
            )
            for content in ("result one", "result two")
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(worker.exitcode, 0)
        outcomes = sorted(queue.get(timeout=2)[0] for _ in workers)

        self.assertEqual(outcomes, ["conflict", "ok"])
        state = self.read_state()
        self.assertEqual(state["revision"], 1)
        self.assertEqual(len(state["submissions"]), 1)


class FailureTransitionTests(RouterStateTestCase):
    def fail_local(self):
        _, fail_stage, _ = load_failure_api(self)
        started = self.start()
        packet = self.read_state()["next_packet"]
        arguments = {
            "state_root": self.state_root,
            "run_id": started.run_id,
            "driver_context_id": DRIVER_CONTEXT_ID,
            "stage": "local_sol",
            "expected_revision": 0,
            "packet_digest_value": packet["packet_digest"],
            "failure": {"code": "app-server-error", "summary": "local stage failed"},
            "execution": self.local_execution(),
        }
        return fail_stage(**arguments), arguments

    def test_current_stage_can_fail_and_becomes_terminal(self):
        failed, _ = self.fail_local()

        self.assertEqual((failed.status, failed.revision, failed.next_stage), ("failed", 1, None))
        state = self.read_state()
        self.assertEqual(state["failed_stage"], "local_sol")
        self.assertIsNone(state["next_packet"])
        self.assertTrue((failed.run_dir / "local-sol.json").is_file())
        self.assertFalse((failed.run_dir / "web-sol.json").exists())

    def test_identical_failure_retry_is_idempotent_but_changed_failure_conflicts(self):
        RouterStateError, fail_stage, _ = load_failure_api(self)
        failed, arguments = self.fail_local()
        before = (failed.run_dir / "state.json").read_bytes()
        arguments["execution"] = {**arguments["execution"], "duration_ms": 999}

        with patch("codex_router.state._commit_state") as commit:
            repeated = fail_stage(**arguments)

        commit.assert_not_called()
        self.assertTrue(repeated.idempotent)
        self.assertEqual((repeated.status, repeated.revision), ("failed", 1))
        self.assertEqual((failed.run_dir / "state.json").read_bytes(), before)

        arguments.update(
            failure={"code": "changed", "summary": "different"},
            expected_revision=99,
        )
        with self.assertRaises(RouterStateError) as raised:
            fail_stage(**arguments)
        self.assertEqual(raised.exception.code, "conflict")

    def test_failure_rejects_wrong_stage_driver_revision_packet_and_prior_success(self):
        RouterStateError, fail_stage, _ = load_failure_api(self)
        started = self.start()
        packet = self.read_state()["next_packet"]
        base = {
            "state_root": self.state_root,
            "run_id": started.run_id,
            "driver_context_id": DRIVER_CONTEXT_ID,
            "stage": "local_sol",
            "expected_revision": 0,
            "packet_digest_value": packet["packet_digest"],
            "failure": {"code": "failed", "summary": "stage failed"},
            "execution": self.local_execution(),
        }
        cases = (
            ({"stage": "web_sol"}, "invalid-transition"),
            ({"driver_context_id": "ctx-00000000-0000-4000-8000-000000000000"}, "conflict"),
            ({"expected_revision": 1}, "revision-mismatch"),
            ({"packet_digest_value": "sha256:" + "0" * 64}, "packet-mismatch"),
        )
        for changes, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(RouterStateError) as raised:
                    fail_stage(**{**base, **changes})
                self.assertEqual(raised.exception.code, expected_code)

        local, local_arguments = self.submit_local()
        with self.assertRaises(RouterStateError) as raised:
            fail_stage(
                state_root=self.state_root,
                run_id=local.run_id,
                driver_context_id=DRIVER_CONTEXT_ID,
                stage="local_sol",
                expected_revision=local.revision,
                packet_digest_value=local_arguments["packet_digest_value"],
                failure=base["failure"],
                execution=local_arguments["execution"],
            )
        self.assertEqual(raised.exception.code, "conflict")

    def test_success_after_failure_conflicts(self):
        RouterStateError, _, submit_stage = load_failure_api(self)
        _, arguments = self.fail_local()

        with self.assertRaises(RouterStateError) as raised:
            submit_stage(
                state_root=self.state_root,
                run_id=arguments["run_id"],
                driver_context_id=DRIVER_CONTEXT_ID,
                stage="local_sol",
                expected_revision=1,
                packet_digest_value=arguments["packet_digest_value"],
                content="late success",
                execution=arguments["execution"],
            )

        self.assertEqual(raised.exception.code, "conflict")

    def test_failure_code_and_summary_reject_non_text_values(self):
        RouterStateError, fail_stage, _ = load_failure_api(self)
        invalid_values = ([], {}, b"bytes", 7, True, object())

        for field in ("code", "summary"):
            for invalid in invalid_values:
                with self.subTest(field=field, value_type=type(invalid).__name__):
                    started = self.start()
                    packet = self.read_state()["next_packet"]
                    failure = {"code": "provider-error", "summary": "stage failed"}
                    failure[field] = invalid
                    with self.assertRaises(RouterStateError) as raised:
                        fail_stage(
                            state_root=self.state_root,
                            run_id=started.run_id,
                            driver_context_id=DRIVER_CONTEXT_ID,
                            stage="local_sol",
                            expected_revision=0,
                            packet_digest_value=packet["packet_digest"],
                            failure=failure,
                            execution=self.local_execution(),
                        )
                    self.assertEqual(raised.exception.code, "invalid-input")
                    self.assertEqual(self.read_state()["status"], "awaiting_local_sol")

    def test_adversarial_failure_summaries_are_completely_omitted(self):
        _, fail_stage, _ = load_failure_api(self)
        card = "4242 " * 3 + "4242"
        email = "user" + "@" + "example.com"
        summaries = (
            '{"to' + 'ken":"secret-value"}',
            "Cookie: session=secret",
            "-----BEGIN PRIVATE KEY-----\nkey material",
            "OPENAI_API" + "_KEY=synthetic-value",
            "/" + "Users/example/private/file",
            "/private/" + "tmp/secret",
            card,
            email,
            "Authorization: Bearer synthetic-credential",
        )

        for summary in summaries:
            with self.subTest(category=summary.splitlines()[0][:16]):
                started = self.start()
                packet = self.read_state()["next_packet"]
                fail_stage(
                    state_root=self.state_root,
                    run_id=started.run_id,
                    driver_context_id=DRIVER_CONTEXT_ID,
                    stage="local_sol",
                    expected_revision=0,
                    packet_digest_value=packet["packet_digest"],
                    failure={
                        "code": "provider-error",
                        "summary": summary,
                        "unrecognized": "discard-this-value",
                    },
                    execution=self.local_execution(),
                )

                evidence = b"\n".join(
                    path.read_bytes() for path in started.run_dir.rglob("*") if path.is_file()
                ).decode("utf-8", errors="replace")
                self.assertNotIn(summary, evidence)
                self.assertNotIn("discard-this-value", evidence)
                self.assertIn("stage failed; sensitive details omitted", evidence)


if __name__ == "__main__":
    unittest.main()
