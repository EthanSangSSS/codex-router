import json
import shlex
from pathlib import Path
import tempfile
import tomllib
import unittest

from codex_router import global_install_adapter as adapter


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


class PrimaryCapabilityV3Tests(unittest.TestCase):
    _PRIMARY_V2_EVIDENCE = {
        "multi_agent_v2": True,
        "capabilities": {
            "spawn_agent": True,
            "followup_task": True,
            "send_message": True,
        },
    }

    def _feature(self, name):
        feature = getattr(adapter, name, None)
        self.assertTrue(callable(feature), f"missing compatibility feature: {name}")
        return feature

    def test_primary_model_defaults_to_runtime_inheritance_not_sol_name(self):
        inherit = getattr(adapter, "PRIMARY_MODEL_INHERIT", None)
        self.assertEqual(inherit, "inherit")
        self.assertNotEqual(inherit, "gpt-5.6-sol")

    def test_runtime_selected_primary_model_is_admitted_by_v2_capability_evidence(self):
        admitted = self._feature("primary_model_is_admitted")
        self.assertTrue(
            admitted(
                requested_model="future-primary-model",
                runtime_capabilities=self._PRIMARY_V2_EVIDENCE,
            )
        )

    def test_primary_model_fails_closed_when_v2_capability_is_missing(self):
        admitted = self._feature("primary_model_is_admitted")
        self.assertFalse(
            admitted(
                requested_model="future-primary-model",
                runtime_capabilities={
                    "multi_agent_v2": True,
                    "capabilities": {
                        "spawn_agent": True,
                        "followup_task": True,
                    },
                },
            )
        )

    def test_sideband_stage_capability_available_from_explicit_runtime_evidence(self):
        classify = self._feature("sideband_stage_capability")
        self.assertEqual(
            classify({"router_stage_k1_exec": True}), "AVAILABLE"
        )

    def test_sideband_stage_capability_unavailable_from_explicit_negative(self):
        classify = self._feature("sideband_stage_capability")
        self.assertEqual(
            classify({"router_stage_k1_exec": False}), "UNAVAILABLE"
        )

    def test_sideband_stage_capability_unknown_when_unproven(self):
        classify = self._feature("sideband_stage_capability")
        self.assertEqual(
            classify(self._PRIMARY_V2_EVIDENCE),
            "UNKNOWN_REQUIRES_CAPABILITY_CHECK",
        )

    def test_primary_readiness_not_compatible_when_sideband_exec_unproven(self):
        status = self._feature("primary_readiness")
        self.assertEqual(status(self._PRIMARY_V2_EVIDENCE), "UNKNOWN_REQUIRES_CAPABILITY_CHECK")

    def test_primary_readiness_incompatible_when_sideband_exec_explicitly_unavailable(self):
        status = self._feature("primary_readiness")
        self.assertEqual(
            status(self._PRIMARY_V2_EVIDENCE | {"router_stage_k1_exec": False}),
            "INCOMPATIBLE",
        )

    def test_static_config_without_sideband_evidence_is_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary)
            (codex_home / "config.toml").write_text(
                "[agents]\nenabled = true\n[features]\nmulti_agent = true\nhooks = true\n",
                encoding="utf-8",
            )

            compatibility, _reason = adapter._primary_capability(codex_home)

        self.assertEqual(compatibility, adapter.UNKNOWN)

    def test_executor_requested_model_is_rendered_explicitly(self):
        render = self._feature("render_executor_config")
        rendered = tomllib.loads(
            render(
                {
                    "requested_model": "custom-executor-model",
                    "requested_reasoning": "high",
                }
            ).decode("utf-8")
        )
        self.assertEqual(rendered["model"], "custom-executor-model")
        self.assertEqual(rendered["model_reasoning_effort"], "high")

    def test_changing_executor_model_does_not_change_primary_semantics(self):
        normalize = self._feature("normalize_role_config")
        first = normalize(
            {
                **ROLE_CONFIG,
                "luna": {
                    "requested_model": "executor-a",
                    "requested_reasoning": "max",
                },
            }
        )
        second = normalize(
            {
                **ROLE_CONFIG,
                "luna": {
                    "requested_model": "executor-b",
                    "requested_reasoning": "max",
                },
            }
        )
        self.assertEqual(first["local_sol"], second["local_sol"])
        self.assertNotEqual(first["luna"]["requested_model"], second["luna"]["requested_model"])

    def test_legacy_role_config_keys_remain_accepted(self):
        normalize = self._feature("normalize_role_config")
        normalized = normalize(ROLE_CONFIG)
        self.assertEqual(normalized["local_sol"], ROLE_CONFIG["local_sol"])
        self.assertEqual(normalized["luna"], ROLE_CONFIG["luna"])

    def test_v3_renderer_exports_full_executor_mode_and_five_hook_events(self):
        self.assertEqual(adapter.LUNA_EXECUTION_MODE, "full_executor_v3_1")
        self.assertEqual(
            adapter.BASELINE_HOOK_EVENTS,
            (
                "UserPromptSubmit",
                "PreToolUse",
                "PostToolUse",
                "SubagentStart",
                "SubagentStop",
            ),
        )

    def test_luna_profile_disables_only_descendant_agent_triad(self):
        rendered = adapter.luna_agent_bytes(ROLE_CONFIG["luna"])
        profile = tomllib.loads(rendered.decode("utf-8"))

        self.assertEqual(profile["agents"], {"enabled": False})
        self.assertEqual(
            profile["features"],
            {"multi_agent": False, "multi_agent_v2": False},
        )
        for removed_restriction in (
            "shell_tool",
            "unified_exec",
            "code_mode",
            "code_mode_only",
            "request_permissions_tool",
            "apps",
            "enable_mcp_apps",
            "plugins",
            "tool_suggest",
        ):
            self.assertNotIn(removed_restriction, profile.get("features", {}))
        self.assertNotIn("web_search", profile)

    def test_hook_renderer_has_exactly_the_v3_baseline_events(self):
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
        rendered = adapter.install_hook_v2(None, handler)
        hooks = json.loads(rendered.decode("utf-8"))["hooks"]

        self.assertEqual(
            tuple(hooks),
            (
                "PostToolUse",
                "PreToolUse",
                "SubagentStart",
                "SubagentStop",
                "UserPromptSubmit",
            ),
        )
        self.assertNotIn("Stop", hooks)
        self.assertNotIn("PermissionRequest", hooks)
        self.assertEqual(
            {
                shlex.split(groups[0]["hooks"][0]["command"])[5]
                for groups in hooks.values()
            },
            {
                "hook-user-prompt",
                "hook-pre-tool",
                "hook-post-tool",
                "hook-subagent-start",
                "hook-subagent-stop",
            },
        )

    def test_generated_policy_text_describes_v3_authority(self):
        agents_block = getattr(adapter, "AGENTS_BLOCK_V3", adapter.AGENTS_BLOCK_V2)
        instructions = getattr(
            adapter,
            "LUNA_DEVELOPER_INSTRUCTIONS_V3",
            adapter.LUNA_DEVELOPER_INSTRUCTIONS_V2,
        )
        combined = f"{agents_block}\n{instructions}"

        for required in (
            "persistent Luna per task epoch",
            "Full Executor ordinary inspect/research/edit/test/debug/retry/verify",
            "no descendants",
            "no nested Codex delegation",
            "packet generation replaces prior authority",
            "Hard Authority Pause freezes Router authority immediately",
            "native turn boundary closes Router scheduling authority",
            "does not prove that detached or background OS processes are dead",
            "A1 hard claims only on proven pre-action surfaces",
            "task_name=luna_worker",
            "agent_type=luna_worker",
            "fork_turns=none",
            "stage canonical K1 through `router stage-k1` first",
            "Native `spawn_agent`/`followup_task` message is a transport trigger, not authority",
            "`send_message` is QueueOnly and cannot advance K1",
            "Native collaboration messages are transport triggers, not work authority.",
            "The authoritative work packet is `[CODEX_ROUTER_PACKET_V3_1]` injected by Router as developer context.",
            "Only after canonical `[CODEX_ROUTER_PACKET_V3_1]` is present may substantive packet work begin.",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)
        for stale in (
            "hard_mode_no_process",
            "persistent_while_root_turn_active",
            "revoke-only terminal semantics",
            "revoke_only_security_boundary",
            "later generations use `send_message` or `followup_task`",
            "generation-1 K1 packet as `message`",
        ):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, combined)


if __name__ == "__main__":
    unittest.main()
