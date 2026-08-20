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
from codex_router import hook
from codex_router.protocol import build_k1_stage_capability, build_luna_packet


class RuntimeOperatorContractTests(unittest.TestCase):
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
        self.session_id = "session-a"
        self.root_turn_id = "root-turn-a"
        control.new_task(
            self.installation, self.secret, self.session_id, "root-parent", "profile-A"
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

    def stage_fields_arguments(self, *extra: str) -> list[str]:
        return [
            "stage-k1-fields",
            "--installation-dir",
            str(self.installation),
            "--session-id",
            self.session_id,
            "--root-turn-id",
            self.root_turn_id,
            "--capability",
            self.capability(),
            "--packet-id",
            "packet-1",
            "--objective",
            "bounded work",
            "--working-directory",
            str(self.installation),
            "--intended-write-scope",
            "README.md",
            "--success-criterion",
            "pass",
            "--stop-condition",
            "blocked",
            *extra,
        ]

    def invoke(self, *extra: str) -> tuple[int, dict[str, object] | None, str]:
        stderr = StringIO()
        outputs: list[dict[str, object]] = []

        def capture(value: dict[str, object], **_kwargs: object) -> None:
            outputs.append(value)

        with (
            patch.object(cli, "_print_json", side_effect=capture),
            redirect_stderr(stderr),
        ):
            result = cli.main(self.stage_fields_arguments(*extra))
        payload = outputs[0] if result == 0 and outputs else None
        return result, payload, stderr.getvalue()

    def test_stage_k1_fields_stages_canonical_generation_one(self) -> None:
        result, payload, stderr = self.invoke()

        self.assertEqual(result, 0, stderr)
        self.assertEqual(
            payload, {"status": "staged", "packet_id": "packet-1", "generation": 1}
        )
        snapshot = self.snapshot()
        assert snapshot is not None
        self.assertEqual(
            snapshot.authority_packet_wire,
            build_luna_packet(
                packet_id="packet-1",
                generation=1,
                objective="bounded work",
                working_directory=str(self.installation),
                intended_write_scope=("README.md",),
                explicit_side_effect_authorizations=(),
                success_criteria=("pass",),
                stop_conditions=("blocked",),
            ),
        )

    def test_stage_k1_fields_rejects_duplicate_singletons_before_state_mutation(self) -> None:
        before = self.snapshot()
        assert before is not None
        result, payload, stderr = self.invoke("--packet-id", "packet-2")

        self.assertEqual(result, 25)
        self.assertIsNone(payload)
        self.assertNotIn(self.capability(), stderr)
        self.assertEqual(self.snapshot(), before)

    def test_v1_native_tool_normalization_is_exact(self) -> None:
        spawn = hook._canonical_hook_tool_name("multi_agent_v1__spawn_agent")
        collapsed_wait = hook._canonical_hook_tool_name("multi_agent_v1wait_agent")

        self.assertEqual(getattr(spawn, "surface_profile", None), "multi_agent_v1")
        self.assertEqual(getattr(spawn, "canonical_operation", None), "spawn_agent")
        self.assertEqual(getattr(spawn, "input_schema", None), "v1_spawn")
        self.assertEqual(
            getattr(collapsed_wait, "canonical_operation", None), "wait_agent"
        )
        self.assertEqual(getattr(collapsed_wait, "input_schema", None), "v1_wait")

    def test_unlisted_v1_names_do_not_normalize(self) -> None:
        self.assertIsNone(hook._canonical_hook_tool_name("multi_agent_v1__list_agents"))
        self.assertIsNone(hook._canonical_hook_tool_name("multi_agent_v1spawn_agents"))

    def test_surface_classification_is_pure_and_does_not_authorize_hook_lifecycle(self) -> None:
        inventory = {
            "sideband_structured_k1_staging": True,
            "multi_agent_v1__spawn_agent": True,
            "followup_task": False,
        }
        original = dict(inventory)
        value = adapter.native_surface_compatibility(inventory)

        self.assertEqual(inventory, original)
        self.assertEqual(value.primary_gen1_readiness, "PASS")
        self.assertEqual(value.persistent_followup_availability, "UNAVAILABLE")
        denied = hook.handle_hook_event(
            {
                "hook_event_name": "PreToolUse",
                "session_id": self.session_id,
                "turn_id": self.root_turn_id,
                "tool_name": "multi_agent_v1__spawn_agent",
                "tool_use_id": "classification-must-not-authorize",
                "tool_input": {
                    "agent_type": "luna_worker",
                    "fork_context": False,
                    "message": "opaque",
                },
            },
            self.installation,
        )
        self.assertEqual(
            denied["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )


if __name__ == "__main__":
    unittest.main()
