from contextlib import redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_router import cli as cli_module
from codex_router.protocol import web_response_marker
from codex_router.state import RouterStateError
from codex_router.types import GlobalStatus


REPO = Path(__file__).resolve().parents[1]
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


class RouterCliTests(unittest.TestCase):
    def cli(self, *args, env=None):
        merged = os.environ.copy()
        merged["PYTHONPATH"] = str(REPO / "src")
        if env:
            merged.update(env)
        return subprocess.run(
            [sys.executable, "-m", "codex_router", *args],
            cwd=REPO,
            env=merged,
            text=True,
            capture_output=True,
        )

    def start_arguments(self, root):
        binary = root / "codex"
        binary.write_text("binary", encoding="utf-8")
        binary.chmod(0o700)
        state_root = root / "runs"
        arguments = (
            "start",
            "--task",
            "review",
            "--driver-context-id",
            DRIVER_CONTEXT_ID,
            "--state-dir",
            str(state_root),
            "--codex-bin",
            str(binary),
            "--local-model",
            "gpt-5.6-sol",
            "--local-reasoning",
            "max",
            "--web-model",
            "sol",
            "--web-reasoning",
            "xhigh",
            "--luna-model",
            "gpt-5.6-luna",
            "--luna-reasoning",
            "max",
        )
        return state_root, arguments

    def test_start_returns_revision_zero_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_root, arguments = self.start_arguments(Path(tmp))
            completed = self.cli(*arguments)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(
                (payload["status"], payload["revision"], payload["next_stage"]),
                ("awaiting_local_sol", 0, "local_sol"),
            )
            self.assertTrue(Path(payload["stage_packet_path"]).is_file())
            self.assertTrue((state_root / payload["run_id"] / "state.json").is_file())

    def test_all_parser_errors_use_the_bounded_json_contract(self):
        sensitive_value = "synthetic-parser-value-must-not-echo"
        common = (
            "--run-id",
            "run-parser-test",
            "--driver-context-id",
            DRIVER_CONTEXT_ID,
            "--state-dir",
            "/tmp/router-parser-test",
            "--stage",
            "local_sol",
            "--expected-revision",
            "0",
            "--packet-digest",
            "sha256:" + "0" * 64,
            "--output-file",
            "/tmp/output",
            "--execution-file",
            "/tmp/execution",
        )
        cases = (
            (),
            ("start",),
            (
                "submit-stage",
                *common[: common.index("local_sol")],
                sensitive_value,
                *common[common.index("local_sol") + 1 :],
            ),
            (
                "submit-stage",
                *common[: common.index("0")],
                sensitive_value,
                *common[common.index("0") + 1 :],
            ),
            (
                "status",
                "--run-id",
                "run-parser-test",
                "--state-dir",
                "/tmp/router-parser-test",
                "--unexpected",
                sensitive_value,
            ),
            (sensitive_value,),
        )

        for arguments in cases:
            with self.subTest(arguments=arguments[:1]):
                completed = self.cli(*arguments)
                self.assertEqual(completed.returncode, 25)
                self.assertEqual(completed.stdout, "")
                payload = json.loads(completed.stderr)
                self.assertEqual(
                    set(payload),
                    {"status", "code", "message", "run_id", "stage", "revision"},
                )
                self.assertEqual(payload["status"], "error")
                self.assertEqual(payload["code"], "invalid-input")
                self.assertIsNone(payload["run_id"])
                self.assertIsNone(payload["stage"])
                self.assertIsNone(payload["revision"])
                self.assertLessEqual(len(payload["message"]), 200)
                self.assertNotIn(sensitive_value, completed.stderr)

    def test_help_remains_normal_text_with_exit_zero(self):
        completed = self.cli("--help")

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stderr, "")
        self.assertIn("usage: router", completed.stdout)

    def test_app_driver_cli_lifecycle_and_terminal_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_root, start_arguments = self.start_arguments(root)
            started = self.cli(*start_arguments)
            self.assertEqual(started.returncode, 0, started.stderr)
            current = json.loads(started.stdout)
            run_dir = state_root / current["run_id"]
            retry_arguments = None

            for stage, semantic_content in (
                ("local_sol", "local result"),
                ("web_sol", "web result"),
                ("luna", "final result"),
            ):
                packet = json.loads(
                    Path(current["stage_packet_path"]).read_text(encoding="utf-8")
                )
                state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
                content = semantic_content
                if stage == "web_sol":
                    content = web_response_marker(packet) + "\n" + semantic_content
                output_file = root / f"{stage}.txt"
                execution_file = root / f"{stage}-execution.json"
                output_file.write_text(content, encoding="utf-8")
                write_json(execution_file, app_execution(state, stage, packet))
                arguments = (
                    "submit-stage",
                    "--run-id",
                    current["run_id"],
                    "--driver-context-id",
                    DRIVER_CONTEXT_ID,
                    "--state-dir",
                    str(state_root),
                    "--stage",
                    stage,
                    "--expected-revision",
                    str(current["revision"]),
                    "--packet-digest",
                    packet["packet_digest"],
                    "--output-file",
                    str(output_file),
                    "--execution-file",
                    str(execution_file),
                )

                if stage == "local_sol":
                    stale = list(arguments)
                    stale[stale.index("--expected-revision") + 1] = "99"
                    self.assertEqual(self.cli(*stale).returncode, 22)
                    wrong_packet = list(arguments)
                    wrong_packet[wrong_packet.index("--packet-digest") + 1] = (
                        "sha256:" + "0" * 64
                    )
                    self.assertEqual(self.cli(*wrong_packet).returncode, 23)
                    execution_file.write_text("{invalid router-secret-123", encoding="utf-8")
                    malformed = self.cli(*arguments)
                    self.assertEqual(malformed.returncode, 25)
                    self.assertEqual(json.loads(malformed.stderr)["code"], "invalid-input")
                    self.assertNotIn("router-secret-123", malformed.stderr)
                    write_json(execution_file, app_execution(state, stage, packet))
                elif stage == "web_sol":
                    output_file.write_text("wrong marker\nweb result", encoding="utf-8")
                    marker_error = self.cli(*arguments)
                    self.assertEqual(marker_error.returncode, 24)
                    self.assertEqual(json.loads(marker_error.stderr)["code"], "marker-mismatch")
                    output_file.write_text(content, encoding="utf-8")

                completed = self.cli(*arguments)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                current = json.loads(completed.stdout)
                if stage == "luna":
                    retry_arguments = arguments

            status = self.cli(
                "status",
                "--run-id",
                current["run_id"],
                "--state-dir",
                str(state_root),
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertEqual(
                (status_payload["status"], status_payload["revision"], status_payload["next_stage"]),
                ("completed", 3, None),
            )

            repeated = self.cli(*retry_arguments)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertTrue(json.loads(repeated.stdout)["idempotent"])
            (root / "luna.txt").write_text("different final", encoding="utf-8")
            conflict = self.cli(*retry_arguments)
            self.assertEqual(conflict.returncode, 20)
            self.assertEqual(json.loads(conflict.stderr)["code"], "conflict")

    def test_fail_stage_and_missing_status_use_structured_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_root, start_arguments = self.start_arguments(root)
            started = self.cli(*start_arguments)
            current = json.loads(started.stdout)
            run_dir = state_root / current["run_id"]
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            packet = state["next_packet"]
            failure_file = root / "failure.json"
            execution_file = root / "execution.json"
            write_json(failure_file, {"code": "app-error", "summary": "failed"})
            write_json(execution_file, app_execution(state, "local_sol", packet))

            failed = self.cli(
                "fail-stage",
                "--run-id",
                current["run_id"],
                "--driver-context-id",
                DRIVER_CONTEXT_ID,
                "--state-dir",
                str(state_root),
                "--stage",
                "local_sol",
                "--expected-revision",
                "0",
                "--packet-digest",
                packet["packet_digest"],
                "--error-file",
                str(failure_file),
                "--execution-file",
                str(execution_file),
            )
            self.assertEqual(failed.returncode, 0, failed.stderr)
            self.assertEqual(json.loads(failed.stdout)["status"], "failed")

            missing = self.cli(
                "status",
                "--run-id",
                "run-missing",
                "--state-dir",
                str(state_root),
            )
            self.assertEqual(missing.returncode, 26)
            self.assertEqual(json.loads(missing.stderr)["code"], "run-not-found")

    def test_sensitive_failure_never_appears_in_cli_or_run_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_root, start_arguments = self.start_arguments(root)
            started = self.cli(*start_arguments)
            current = json.loads(started.stdout)
            run_dir = state_root / current["run_id"]
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            packet = state["next_packet"]
            protected = '{"api_' + 'key":"synthetic-sensitive-value"}'
            failure_file = root / "failure.json"
            execution_file = root / "execution.json"
            write_json(failure_file, {"code": "app-error", "summary": protected})
            write_json(execution_file, app_execution(state, "local_sol", packet))

            failed = self.cli(
                "fail-stage",
                "--run-id",
                current["run_id"],
                "--driver-context-id",
                DRIVER_CONTEXT_ID,
                "--state-dir",
                str(state_root),
                "--stage",
                "local_sol",
                "--expected-revision",
                "0",
                "--packet-digest",
                packet["packet_digest"],
                "--error-file",
                str(failure_file),
                "--execution-file",
                str(execution_file),
            )

            evidence = b"\n".join(
                path.read_bytes() for path in run_dir.rglob("*") if path.is_file()
            ).decode("utf-8", errors="replace")
            self.assertEqual(failed.returncode, 0, failed.stderr)
            self.assertEqual(failed.stderr, "")
            self.assertNotIn(protected, failed.stdout)
            self.assertNotIn(protected, evidence)

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
            "state-root-unowned": 30,
        }
        for error_code, exit_code in expected.items():
            with self.subTest(error_code=error_code):
                error = RouterStateError(
                    error_code,
                    "bounded message",
                    run_id="run-test",
                    revision=1,
                )
                stderr = StringIO()
                with patch.object(cli_module, "get_status", side_effect=error):
                    with redirect_stderr(stderr):
                        actual = cli_module.main(
                            [
                                "status",
                                "--run-id",
                                "run-test",
                                "--state-dir",
                                "/tmp/router-cli-test",
                            ]
                        )
                self.assertEqual(actual, exit_code)
                self.assertEqual(json.loads(stderr.getvalue())["code"], error_code)

    def test_fake_adapter_completes_offline_happy_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            completed = self.cli(
                "run",
                "--task",
                "Return exactly ROUTER_MVP_OK",
                "--adapter-mode",
                "fake",
                "--state-dir",
                tmp,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "ROUTER_MVP_OK")
            runs = list(Path(tmp).glob("run-*"))
            self.assertEqual(len(runs), 1)
            result = json.loads((runs[0] / "result.json").read_text())
            self.assertEqual(result["result"], "ROUTER_MVP_OK")

    def test_real_mode_fails_closed_when_provider_is_not_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            completed = self.cli(
                "run",
                "--task",
                "do real work",
                "--adapter-mode",
                "real",
                "--state-dir",
                tmp,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("provider-not-configured", completed.stderr)

    def test_global_status_payload_exposes_blocked_v33_acceptance(self):
        status = GlobalStatus(
            state="installed",
            installation_dir=Path("/tmp/router-installation"),
            hook_configured=True,
            agents_managed=True,
            luna_agent_configured=True,
            config_valid=True,
            identity_material_valid=True,
            hook_trust="requires-user-check",
            new_session_required=True,
        )
        payload = cli_module._global_status_payload(status)

        self.assertEqual(payload["router_design"], "v3.3")
        self.assertEqual(payload["live_activation"], "BLOCKED_ACCEPTANCE_GATES")
        self.assertEqual(
            set(payload["live_activation_blockers"]),
            {
                "G1_CURRENT_GENERATION_SPAWN_CORRELATION",
                "G2_SETTLEMENT_OBSERVATION",
                "G3_ACTOR_ATTRIBUTION",
                "G4_NO_DESCENDANTS_EFFECTIVE_INVENTORY",
                "G5_NESTED_CODEX",
                "G6_NATIVE_AUTHORITY_PROFILE",
                "G7_A1_CAPABILITY_MATRIX",
                "G8_STALE_GENERATION_REJECTION",
            },
        )
        self.assertNotIn("G9_ECONOMICS", payload["live_activation_blockers"])
        self.assertIn("G9_ECONOMICS", payload["deferred_acceptance_evidence"])


if __name__ == "__main__":
    unittest.main()
