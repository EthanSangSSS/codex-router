import json
from pathlib import Path
import shlex
import unittest

from codex_router import a1
from codex_router import global_install_adapter as adapter
from codex_router.protocol import ProtocolError, build_luna_packet, parse_luna_packet


class A1CapabilityV3Tests(unittest.TestCase):
    def test_categories_and_enforcement_values_are_canonical(self):
        self.assertEqual(
            a1.A1_CATEGORIES,
            (
                "git_push",
                "remote_collaboration_mutation",
                "deploy_release_publish",
                "outbound_user_communication",
                "cloud_resource_mutation",
                "system_level_install",
                "comparable_external_persistent_mutation",
            ),
        )
        self.assertEqual(
            a1.SurfaceEnforcement.__args__,
            (
                "PROVEN_PRE_ACTION",
                "BASELINE_WITHHELD",
                "COOPERATIVE_ONLY",
                "UNVERIFIED",
            ),
        )

    def test_packet_authorizations_accept_only_known_categories(self):
        self.assertEqual(
            a1.validate_packet_authorizations(
                ["git_push", "deploy_release_publish"]
            ),
            ("git_push", "deploy_release_publish"),
        )
        with self.assertRaises(ValueError):
            a1.validate_packet_authorizations(["git push"])
        with self.assertRaises(ValueError):
            a1.validate_packet_authorizations(["unknown_category"])

    def test_unknown_k1_authorization_is_rejected_at_wire_parsing(self):
        packet = {
            "packet_id": "packet-1",
            "generation": 1,
            "objective": "bounded task",
            "working_directory": "/workspace/repo",
            "intended_write_scope": ["src/module.py"],
            "explicit_side_effect_authorizations": ["unknown_category"],
            "success_criteria": ["focused tests pass"],
            "stop_conditions": ["scope expansion required"],
        }
        with self.assertRaises(ProtocolError):
            parse_luna_packet(
                build_luna_packet(
                    packet_id=packet["packet_id"],
                    generation=packet["generation"],
                    objective=packet["objective"],
                    working_directory=packet["working_directory"],
                    intended_write_scope=packet["intended_write_scope"],
                    explicit_side_effect_authorizations=packet[
                        "explicit_side_effect_authorizations"
                    ],
                    success_criteria=packet["success_criteria"],
                    stop_conditions=packet["stop_conditions"],
                )
            )

    def test_generation_authorizations_are_wire_scoped_and_not_inherited(self):
        first = parse_luna_packet(
            build_luna_packet(
                packet_id="packet-1",
                generation=1,
                objective="first packet",
                working_directory="/workspace/repo",
                intended_write_scope=["src/one.py"],
                explicit_side_effect_authorizations=["git_push"],
                success_criteria=["first passes"],
                stop_conditions=["scope expansion required"],
            )
        )
        second = parse_luna_packet(
            build_luna_packet(
                packet_id="packet-2",
                generation=2,
                objective="replacement packet",
                working_directory="/workspace/repo",
                intended_write_scope=["src/two.py"],
                explicit_side_effect_authorizations=[],
                success_criteria=["second passes"],
                stop_conditions=["scope expansion required"],
            )
        )
        self.assertEqual(first["explicit_side_effect_authorizations"], ["git_push"])
        self.assertEqual(second["explicit_side_effect_authorizations"], [])

    def test_hard_claim_requires_proven_pre_action_gate_and_actor(self):
        proven = a1.A1SurfaceCapability(
            category="git_push",
            surface="structured_tool",
            enforcement="PROVEN_PRE_ACTION",
            gate="PermissionRequest",
            actor_attribution="PROVEN",
        )
        self.assertTrue(a1.hard_claim_ready((proven,), "git_push"))

        for enforcement, gate, actor in (
            ("UNVERIFIED", None, "UNVERIFIED"),
            ("COOPERATIVE_ONLY", None, "PROVEN"),
            ("PROVEN_PRE_ACTION", None, "PROVEN"),
            ("PROVEN_PRE_ACTION", "PermissionRequest", "UNVERIFIED"),
        ):
            with self.subTest(enforcement=enforcement, gate=gate, actor=actor):
                surface = a1.A1SurfaceCapability(
                    category="git_push",
                    surface="shell",
                    enforcement=enforcement,
                    gate=gate,
                    actor_attribution=actor,
                )
                self.assertFalse(a1.hard_claim_ready((surface,), "git_push"))
        self.assertFalse(a1.hard_claim_ready((proven,), "unknown_category"))

    def test_a1_module_has_no_general_command_parser(self):
        source = Path(a1.__file__).read_text(encoding="utf-8")
        for forbidden in ("git push", "curl", "subprocess", "shlex"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_permission_request_is_conditional_on_exact_proven_capability(self):
        handler = {
            "type": "command",
            "command": shlex.join(
                (
                    "/usr/bin/python3",
                    "-E",
                    "-P",
                    "-m",
                    "codex_router",
                    "hook-user-prompt",
                    "--installation-dir",
                    "/tmp/router-installation",
                )
            ),
            "statusMessage": "Routing with Codex Router [codex-router-global-policy-v1]",
        }
        baseline = json.loads(
            adapter.install_hook_v3(None, handler).decode("utf-8")
        )["hooks"]
        self.assertEqual(set(baseline), set(adapter.BASELINE_HOOK_EVENTS))

        proven = a1.A1SurfaceCapability(
            category="git_push",
            surface="structured_tool",
            enforcement="PROVEN_PRE_ACTION",
            gate="PermissionRequest",
            actor_attribution="PROVEN",
        )
        raw_tuple = json.loads(
            adapter.install_hook_v3(
                None,
                handler,
                capability_matrix=(proven,),
            ).decode("utf-8")
        )["hooks"]
        self.assertEqual(set(raw_tuple), set(adapter.BASELINE_HOOK_EVENTS))

        exact_runtime_record = {
            "record_type": "exact_runtime",
            "capabilities": (proven,),
        }
        gated = json.loads(
            adapter.install_hook_v3(
                None,
                handler,
                runtime_record=exact_runtime_record,
            ).decode("utf-8")
        )["hooks"]
        self.assertEqual(
            set(gated), set(adapter.BASELINE_HOOK_EVENTS) | {"PermissionRequest"}
        )
        self.assertNotIn("Stop", gated)

        withheld = a1.A1SurfaceCapability(
            category="git_push",
            surface="structured_tool",
            enforcement="COOPERATIVE_ONLY",
            gate="PermissionRequest",
            actor_attribution="PROVEN",
        )
        cooperative_record = {
            "record_type": "exact_runtime",
            "capabilities": (withheld,),
        }
        self.assertEqual(
            set(
                json.loads(
                    adapter.install_hook_v3(
                        None,
                        handler,
                        runtime_record=cooperative_record,
                    ).decode("utf-8")
                )["hooks"]
            ),
            set(adapter.BASELINE_HOOK_EVENTS),
        )


if __name__ == "__main__":
    unittest.main()
