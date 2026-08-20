from contextlib import redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_router import cli
from codex_router import global_install_adapter as adapter
from codex_router import luna_control as control
from codex_router import policy
from codex_router.hook import HOOK_CONTEXT_PREFIX, handle_hook_event, handle_user_prompt
from codex_router.protocol import build_k1_stage_capability, build_luna_packet


class RouterUsabilityV32Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.installation = self.root / "installation"
        self.installation.mkdir(mode=0o700)
        self.secret = bytes(range(32))
        (self.installation / "installation-secret").write_bytes(self.secret)
        (self.installation / "installation-secret").chmod(0o600)
        binary = self.root / "codex"
        binary.write_text("synthetic", encoding="utf-8")
        binary.chmod(0o700)
        (self.installation / "config.json").write_text(
            json.dumps(
                {
                    "protocol": "codex-router/global-policy-config/v1",
                    "state_root": str(self.installation),
                    "codex_binary": str(binary),
                    "role_config": {
                        "local_sol": {
                            "requested_model": "inherit",
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
                    },
                }
            ),
            encoding="utf-8",
        )
        (self.installation / "config.json").chmod(0o600)
        self.session_id = "session-v32"
        self.root_turn_id = "root-turn-v32"
        control.new_task(
            self.installation,
            self.secret,
            self.session_id,
            "root-parent",
            "profile-A",
        )
        control.set_current_root_turn(
            self.installation,
            self.secret,
            self.session_id,
            turn_id=self.root_turn_id,
        )

    def snapshot(self):
        return control.read_snapshot(self.installation, self.secret, self.session_id)

    def capability(self) -> str:
        snapshot = self.snapshot()
        assert snapshot is not None
        return build_k1_stage_capability(
            self.secret,
            session_tag=control.session_tag(self.secret, self.session_id),
            root_turn_tag=snapshot.current_root_turn_tag,
            task_epoch=snapshot.task_epoch,
            generation=snapshot.packet_generation + 1,
        )

    def routed_context(self, prompt: str = "fix the failing tests") -> dict[str, object]:
        output = handle_user_prompt(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": self.session_id,
                "turn_id": self.root_turn_id,
                "prompt": prompt,
                "cwd": str(self.root),
            },
            self.installation,
        )
        additional = output["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(additional.startswith(HOOK_CONTEXT_PREFIX))
        return json.loads(additional[len(HOOK_CONTEXT_PREFIX) :])

    def _request_path_from_context(self) -> Path:
        context = self.routed_context()
        return Path(str(context["K1_STAGE_REQUEST_PATH"]))

    def _invoke_request(self, request_path: Path) -> tuple[int, list[dict[str, object]], str]:
        stderr = StringIO()
        outputs: list[dict[str, object]] = []

        def capture(value: dict[str, object], **_kwargs: object) -> None:
            outputs.append(value)

        context = self.routed_context()
        command = str(context["K1_STAGE_COMMAND"])
        argv = command.split()
        stage_index = argv.index("stage-k1-request")
        with (
            patch.object(cli, "_print_json", side_effect=capture),
            redirect_stderr(stderr),
        ):
            result = cli.main(argv[stage_index:])
        return result, outputs, stderr.getvalue()

    def _write_request(self, path: Path, **overrides: object) -> dict[str, object]:
        request: dict[str, object] = {
            "packet_id": "packet-v32",
            "objective": "bounded local repair",
            "working_directory": str(self.root),
            "intended_write_scope": ["src", "tests"],
            "explicit_side_effect_authorizations": [],
            "success_criteria": ["focused tests pass"],
            "stop_conditions": ["scope expansion required"],
        }
        request.update(overrides)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(json.dumps(request), encoding="utf-8")
        path.chmod(0o600)
        return request

    def _bind_luna_with_packet(self) -> str:
        packet = build_luna_packet(
            packet_id="packet-v32",
            generation=1,
            objective="bounded work",
            working_directory=str(self.root),
            intended_write_scope=("src", "tests"),
            explicit_side_effect_authorizations=(),
            success_criteria=("pass",),
            stop_conditions=("stop",),
        )
        control.stage_authority_packet(
            self.installation,
            self.secret,
            self.session_id,
            root_turn_id=self.root_turn_id,
            capability=self.capability(),
            packet_wire=packet,
        )
        control.admit_staged_spawn(
            self.installation,
            self.secret,
            self.session_id,
            root_turn_id=self.root_turn_id,
            tool_use_id="spawn-v32",
            task_name="luna_worker",
            agent_type="luna_worker",
            fork_turns="none",
        )
        control.observe_spawn_result(
            self.installation,
            self.secret,
            self.session_id,
            tool_use_id="spawn-v32",
            task_path="/root/luna_worker",
        )
        control.observe_subagent_start(
            self.installation,
            self.secret,
            self.session_id,
            agent_id="luna-v32",
            agent_type="luna_worker",
        )
        return packet

    def test_hook_renders_complete_request_staging_command(self) -> None:
        context = self.routed_context()
        command = str(context["K1_STAGE_COMMAND"])
        request_path = str(context["K1_STAGE_REQUEST_PATH"])

        self.assertIn("stage-k1-request", command)
        self.assertIn("--request-file", command)
        self.assertIn(request_path, command)
        self.assertNotIn("stage-k1-fields", command)
        self.assertNotIn("--packet-id", command)

    def test_stage_k1_request_stages_exact_canonical_packet(self) -> None:
        request_path = self._request_path_from_context()
        request = self._write_request(request_path)

        result, outputs, stderr = self._invoke_request(request_path)

        self.assertEqual(result, 0, stderr)
        self.assertEqual(outputs[-1]["status"], "staged")
        snapshot = self.snapshot()
        assert snapshot is not None
        self.assertEqual(
            snapshot.authority_packet_wire,
            build_luna_packet(
                packet_id=str(request["packet_id"]),
                generation=1,
                objective=str(request["objective"]),
                working_directory=str(request["working_directory"]),
                intended_write_scope=tuple(request["intended_write_scope"]),
                explicit_side_effect_authorizations=(),
                success_criteria=tuple(request["success_criteria"]),
                stop_conditions=tuple(request["stop_conditions"]),
            ),
        )
        self.assertFalse(request_path.exists())

    def test_stage_k1_request_rejects_unknown_key_without_state_mutation(self) -> None:
        request_path = self._request_path_from_context()
        self._write_request(request_path, generation=999)
        before = self.snapshot()

        result, _outputs, _stderr = self._invoke_request(request_path)

        self.assertNotEqual(result, 0)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(request_path.exists())

    def test_primary_fallback_requires_idle_cleared_authority(self) -> None:
        classify = getattr(control, "classify_primary_fallback")
        snapshot = self.snapshot()
        assert snapshot is not None
        self.assertEqual(classify(snapshot), "SAFE_LOCAL_FALLBACK")

        packet = build_luna_packet(
            packet_id="active",
            generation=1,
            objective="work",
            working_directory=str(self.root),
            intended_write_scope=(),
            explicit_side_effect_authorizations=(),
            success_criteria=(),
            stop_conditions=(),
        )
        control.stage_authority_packet(
            self.installation,
            self.secret,
            self.session_id,
            root_turn_id=self.root_turn_id,
            capability=self.capability(),
            packet_wire=packet,
        )
        self.assertEqual(
            classify(self.snapshot()),
            "BLOCKED_ACTIVE_AUTHORITY",
        )

    def test_strict_router_marker_routes_without_fallback_authority(self) -> None:
        decision = policy.classify_prompt(
            "[CODEX_ROUTER_STRICT]\nfix the failing tests"
        )
        self.assertEqual(decision.decision, "route")
        self.assertTrue(decision.strict_router)

        context = self.routed_context(
            "[CODEX_ROUTER_STRICT]\nfix the failing tests"
        )
        self.assertIs(context["strict_router"], True)
        self.assertEqual(
            context["capability_failure_policy"],
            "degrade_primary_safe_local",
        )

    def test_normal_route_exposes_safe_local_fallback_state(self) -> None:
        context = self.routed_context()
        self.assertIs(context["strict_router"], False)
        self.assertEqual(context["primary_fallback_state"], "SAFE_LOCAL_FALLBACK")
        self.assertEqual(
            context["capability_failure_policy"],
            "degrade_primary_safe_local",
        )

    def test_v1_gen1_model_admission_does_not_require_followup(self) -> None:
        self.assertTrue(
            adapter.primary_model_is_admitted(
                requested_model="future-primary-model",
                runtime_capabilities={
                    "sideband_structured_k1_staging": True,
                    "multi_agent_v1__spawn_agent": True,
                    "followup_task": False,
                },
            )
        )

    def test_allowlisted_pwd_bootstrap_receives_k1_without_denial_retry(self) -> None:
        packet = self._bind_luna_with_packet()

        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": self.session_id,
                "turn_id": "luna-turn-v32",
                "tool_name": "Bash",
                "tool_use_id": "pwd-v32",
                "tool_input": {"command": "pwd"},
                "agent_id": "luna-v32",
                "agent_type": "luna_worker",
            },
            self.installation,
        )

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "allow",
        )
        self.assertEqual(
            output["hookSpecificOutput"]["additionalContext"],
            packet,
        )

    def test_substantive_first_luna_tool_is_denied_before_k1(self) -> None:
        self._bind_luna_with_packet()

        output = handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": self.session_id,
                "turn_id": "luna-turn-v32",
                "tool_name": "Bash",
                "tool_use_id": "shell-v32",
                "tool_input": {"command": "echo unsafe"},
                "agent_id": "luna-v32",
                "agent_type": "luna_worker",
            },
            self.installation,
        )

        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        snapshot = self.snapshot()
        assert snapshot is not None
        self.assertEqual(snapshot.execution_status, "IDLE")
        self.assertIsNone(snapshot.active_child_turn_id)

    def test_rendered_policy_degrades_capability_failure_but_not_safety_failure(self) -> None:
        text = adapter.AGENTS_BLOCK_V3
        self.assertIn("SAFE_LOCAL_FALLBACK", text)
        self.assertIn("[CODEX_ROUTER_STRICT]", text)
        self.assertIn("degraded", text.lower())
        self.assertNotIn(
            "return `BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE` before staging Gen2",
            text,
        )


if __name__ == "__main__":
    unittest.main()
