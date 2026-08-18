import json
import multiprocessing
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


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
REPO = Path(__file__).resolve().parents[1]


def _concurrent_hook_worker(queue, event, installation_dir):
    try:
        from codex_router.hook import handle_user_prompt

        queue.put(("ok", handle_user_prompt(event, Path(installation_dir))))
    except Exception as error:
        queue.put((getattr(error, "code", type(error).__name__), None))


class HookTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.installation_dir = self.root / "installation"
        self.installation_dir.mkdir(mode=0o700)
        self.state_root = self.root / "runs"
        self.binary = self.root / "codex"
        self.binary.write_text("synthetic binary", encoding="utf-8")
        self.binary.chmod(0o700)
        self.secret = bytes(range(32))
        self._write_private(self.installation_dir / "installation-secret", self.secret)
        config = {
            "protocol": "codex-router/global-policy-config/v1",
            "state_root": str(self.state_root),
            "codex_binary": str(self.binary),
            "role_config": ROLE_CONFIG,
        }
        self._write_private(
            self.installation_dir / "config.json",
            json.dumps(config, ensure_ascii=False).encode("utf-8"),
        )

    def _write_private(self, path, content):
        path.write_bytes(content)
        path.chmod(0o600)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def event(self, *, prompt="修改 README", session="session-a", turn="turn-a"):
        return {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session,
            "turn_id": turn,
            "prompt": prompt,
            "cwd": str(self.root),
        }

    def handle(self, event):
        from codex_router.hook import handle_user_prompt

        return handle_user_prompt(event, self.installation_dir)

    def pretool_event(
        self,
        *,
        tool_name,
        session="session-a",
        turn="turn-a",
        tool_use_id="tool-1",
        tool_input=None,
        actor_id=None,
        actor_type=None,
        agent_id=None,
        agent_type=None,
    ):
        event = {
            "hook_event_name": "PreToolUse",
            "session_id": session,
            "turn_id": turn,
            "tool_name": tool_name,
            "tool_use_id": tool_use_id,
            "tool_input": {} if tool_input is None else tool_input,
        }
        for name, value in (
            ("actor_id", actor_id),
            ("actor_type", actor_type),
            ("agent_id", agent_id),
            ("agent_type", agent_type),
        ):
            if value is not None:
                event[name] = value
        return event

    def bind_luna(self, *, session="session-a", agent_id="agent-1"):
        from codex_router import luna_control as control

        control.new_task(
            self.installation_dir,
            self.secret,
            session,
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )
        control.reserve_spawn(
            self.installation_dir,
            self.secret,
            session,
            tool_use_id="spawn-1",
            task_name="luna_worker",
            fork_turns="none",
        )
        control.observe_spawn_result(
            self.installation_dir,
            self.secret,
            session,
            tool_use_id="spawn-1",
            task_path="/root/luna_worker",
        )
        return control.observe_subagent_start(
            self.installation_dir,
            self.secret,
            session,
            agent_id=agent_id,
            agent_type="luna_worker",
        )

    def parse_context(self, output):
        context = output["hookSpecificOutput"]["additionalContext"]
        prefix = "[CODEX_ROUTER_POLICY_V1] "
        self.assertTrue(context.startswith(prefix))
        return json.loads(context[len(prefix) :])


class HookSchemaTests(HookTestCase):
    def test_schema_requires_the_official_user_prompt_fields(self):
        from codex_router.state import RouterStateError

        valid = self.event()
        invalid_events = []
        for name in ("hook_event_name", "session_id", "turn_id", "prompt", "cwd"):
            missing = dict(valid)
            missing.pop(name)
            invalid_events.append(missing)
        wrong_event = dict(valid, hook_event_name="OtherHook")
        invalid_events.append(wrong_event)
        for name in ("session_id", "turn_id", "prompt", "cwd"):
            invalid_events.append(dict(valid, **{name: ""}))
            invalid_events.append(dict(valid, **{name: 42}))

        for event in invalid_events:
            with self.subTest(keys=sorted(event)):
                with self.assertRaises(RouterStateError) as raised:
                    self.handle(event)
                self.assertEqual(raised.exception.code, "invalid-input")

    def test_direct_and_bypass_output_are_compact_and_do_not_echo_prompt(self):
        for prompt, decision in (
            ("你好", "direct"),
            ("仅本地执行\n修改 README", "bypass"),
        ):
            with self.subTest(decision=decision):
                output = self.handle(self.event(prompt=prompt))
                self.assertEqual(set(output), {"hookSpecificOutput"})
                hook_output = output["hookSpecificOutput"]
                self.assertEqual(
                    set(hook_output), {"hookEventName", "additionalContext"}
                )
                self.assertEqual(hook_output["hookEventName"], "UserPromptSubmit")
                context = self.parse_context(output)
                self.assertEqual(context["decision"], decision)
                self.assertNotIn(prompt, json.dumps(output, ensure_ascii=False))

    def test_route_initialization_failure_blocks_without_error_or_prompt_echo(self):
        protected_prompt = "修改文件 " + "api_" + "key=synthetic-hook-value"
        (self.installation_dir / "config.json").chmod(0o644)

        output = self.handle(self.event(prompt=protected_prompt))

        self.assertEqual(output["decision"], "block")
        self.assertIn("Router safety state", output["reason"])
        serialized = json.dumps(output, ensure_ascii=False)
        self.assertNotIn(protected_prompt, serialized)
        self.assertNotIn("config", serialized.lower())


class HookNativeDelegationTests(HookTestCase):
    def test_routed_events_use_persistent_native_luna_context(self):
        from codex_router import luna_control as control

        event = self.event()

        first = self.parse_context(self.handle(event))
        first_snapshot = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )
        repeated = self.parse_context(self.handle(event))
        different = self.parse_context(self.handle(self.event(turn="turn-b")))
        final_snapshot = control.read_snapshot(
            self.installation_dir, self.secret, "session-a"
        )

        self.assertEqual(first, repeated)
        self.assertEqual(first, different)
        self.assertIsNotNone(first_snapshot)
        self.assertIsNotNone(final_snapshot)
        self.assertEqual(first_snapshot.task_epoch, final_snapshot.task_epoch)
        self.assertEqual(first_snapshot.luna_epoch, final_snapshot.luna_epoch)
        self.assertEqual(
            first,
            {
                "protocol": "codex-router/hook-context/v2",
                "decision": "route",
                "reason": "substantive_request",
                "workflow": "persistent_native_luna",
                "sol_role": "plan_review_final_authority",
                "luna_role": "default_execution",
                "delegation_mode": "sequential_work_packets",
                "luna_agent": "luna_worker",
                "luna_model": "gpt-5.6-luna",
                "luna_reasoning": "max",
                "luna_lifecycle": "persistent_task_epoch",
                "parent_terminal_policy": "hard_authority_pause",
                "capacity_failure_policy": "return_to_sol",
                "luna_descendant_policy": "forbidden",
                "luna_codex_runtime_policy": "forbidden",
                "interactive_blocker_policy": "return_to_sol_or_user",
                "initial_context_mode": "packet_only",
                "web_mode": "manual_operator",
                "pause_semantics": "hard_authority_pause",
                "sol_supervision": "event_driven",
                "luna_execution_mode": "full_executor",
            },
        )
        self.assertFalse(self.state_root.exists())

    def test_bound_luna_is_a_full_executor_except_for_lifecycle_tools(self):
        from codex_router import luna_control as control
        from codex_router.hook import handle_hook_event

        self.bind_luna()
        control.begin_packet(
            self.installation_dir,
            self.secret,
            "session-a",
            packet_id="packet-full-executor",
            objective="exercise ordinary Full Executor tools",
            working_directory=str(self.root),
            intended_write_scope=(str(self.root),),
            explicit_side_effect_authorizations=(),
            success_criteria=("ordinary tools remain available",),
            stop_conditions=("scope expansion required",),
        )
        ordinary_tools = (
            "Read",
            "apply_patch",
            "Bash",
            "shell_command",
            "exec_command",
            "mcp__filesystem__read",
        )
        for tool_name in ordinary_tools:
            with self.subTest(tool_name=tool_name):
                output = handle_hook_event(
                    self.pretool_event(
                        tool_name=tool_name,
                        agent_id="agent-1",
                        agent_type="luna_worker",
                    ),
                    self.installation_dir,
                )
                self.assertEqual(output, {})

        for tool_name in ("spawn_agent", "send_message", "resume_agent"):
            with self.subTest(tool_name=tool_name):
                output = handle_hook_event(
                    self.pretool_event(
                        tool_name=tool_name,
                        agent_id="agent-1",
                        agent_type="luna_worker",
                    ),
                    self.installation_dir,
                )
                self.assertEqual(
                    output["hookSpecificOutput"]["permissionDecision"], "deny"
                )

    def test_parent_lifecycle_requires_explicit_actor_and_exact_control_fields(self):
        from codex_router import luna_control as control
        from codex_router.hook import handle_hook_event, handle_user_prompt
        from codex_router.protocol import build_luna_packet

        control.new_task(
            self.installation_dir,
            self.secret,
            "session-parent",
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )
        packet_message = build_luna_packet(
            packet_id="packet-1",
            generation=1,
            objective="continue bounded work",
            working_directory=str(self.root),
            intended_write_scope=("src/example.py",),
            explicit_side_effect_authorizations=(),
            success_criteria=("focused tests pass",),
            stop_conditions=("scope expansion required",),
        )
        spawn_input = {
            "message": packet_message,
            "task_name": "luna_worker",
            "agent_type": "luna_worker",
            "fork_turns": "none",
        }
        spawn = self.pretool_event(
            tool_name="spawn_agent",
            session="session-parent",
            tool_use_id="spawn-parent",
            tool_input=spawn_input,
            actor_id="root-parent",
            actor_type="primary_sol",
        )
        self.assertEqual(handle_hook_event(spawn, self.installation_dir), {})
        post_spawn = {
            "hook_event_name": "PostToolUse",
            "session_id": "session-parent",
            "turn_id": "turn-a",
            "tool_name": "spawn_agent",
            "tool_use_id": "spawn-parent",
            "tool_input": spawn_input,
            "tool_response": {"task_name": "/root/luna_worker"},
            "actor_id": "root-parent",
            "actor_type": "primary_sol",
        }
        self.assertEqual(
            handle_hook_event(post_spawn, self.installation_dir),
            {"hookSpecificOutput": {"hookEventName": "PostToolUse"}},
        )
        start = {
            "hook_event_name": "SubagentStart",
            "session_id": "session-parent",
            "turn_id": "luna-turn-1",
            "agent_id": "agent-parent-bound",
            "agent_type": "luna_worker",
        }
        self.assertEqual(
            handle_hook_event(start, self.installation_dir),
            {"hookSpecificOutput": {"hookEventName": "SubagentStart"}},
        )
        self.assertEqual(
            handle_user_prompt(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-parent",
                    "turn_id": "luna-turn-1",
                    "agent_id": "agent-parent-bound",
                    "agent_type": "luna_worker",
                    "prompt": packet_message,
                    "cwd": str(self.root),
                },
                self.installation_dir,
            ),
            {},
        )
        self.assertEqual(
            handle_hook_event(
                {
                    "hook_event_name": "SubagentStop",
                    "session_id": "session-parent",
                    "turn_id": "luna-turn-1",
                    "agent_id": "agent-parent-bound",
                    "agent_type": "luna_worker",
                },
                self.installation_dir,
            ),
            {"hookSpecificOutput": {"hookEventName": "SubagentStop"}},
        )

        target_event = self.pretool_event(
            tool_name="send_message",
            session="session-parent",
            tool_input={"target": "/root/luna_worker", "message": "continue"},
            actor_id="root-parent",
            actor_type="primary_sol",
        )
        target_output = handle_hook_event(target_event, self.installation_dir)
        self.assertEqual(
            target_output["hookSpecificOutput"]["permissionDecision"], "deny"
        )

        packet_message_2 = build_luna_packet(
            packet_id="packet-2",
            generation=2,
            objective="continue bounded work",
            working_directory=str(self.root),
            intended_write_scope=("src/example.py",),
            explicit_side_effect_authorizations=(),
            success_criteria=("focused tests pass",),
            stop_conditions=("scope expansion required",),
        )
        packet_event = self.pretool_event(
            tool_name="send_message",
            session="session-parent",
            tool_use_id="packet-message",
            tool_input={
                "target": "/root/luna_worker",
                "message": packet_message_2,
            },
            actor_id="root-parent",
            actor_type="primary_sol",
        )
        self.assertEqual(handle_hook_event(packet_event, self.installation_dir), {})
        packet_snapshot = control.read_snapshot(
            self.installation_dir, self.secret, "session-parent"
        )
        self.assertEqual(packet_snapshot.active_packet_id, "packet-2")
        self.assertEqual(packet_snapshot.packet_generation, 2)

        for missing_actor in (
            {},
            {"actor_id": "root-parent"},
            {"actor_type": "primary_sol"},
            {"actor_id": "unknown", "actor_type": "ambiguous"},
        ):
            with self.subTest(missing_actor=missing_actor):
                event = self.pretool_event(
                    tool_name="send_message",
                    session="session-parent",
                    tool_input={"target": "/root/luna_worker"},
                    **missing_actor,
                )
                output = handle_hook_event(event, self.installation_dir)
                self.assertEqual(
                    output["hookSpecificOutput"]["permissionDecision"], "deny"
                )

        unknown_lifecycle = self.pretool_event(
            tool_name="agent_restart",
            session="session-parent",
            actor_id="root-parent",
            actor_type="primary_sol",
        )
        output = handle_hook_event(unknown_lifecycle, self.installation_dir)
        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_concurrent_routed_events_do_not_allocate_runs(self):
        event = self.event()
        expected = self.parse_context(self.handle(event))
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        processes = [
            context.Process(
                target=_concurrent_hook_worker,
                args=(queue, event, str(self.installation_dir)),
            )
            for _ in range(4)
        ]
        for process in processes:
            process.start()
        results = [queue.get(timeout=10) for _ in processes]
        for process in processes:
            process.join(timeout=10)
            self.assertEqual(process.exitcode, 0)

        self.assertTrue(all(status == "ok" for status, _ in results), results)
        contexts = [self.parse_context(output) for _, output in results]
        self.assertEqual(contexts, [expected] * 4)
        self.assertFalse(self.state_root.exists())


class HookCliTests(HookTestCase):
    def cli(self, input_text):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPO / "src")
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "codex_router",
                "hook-user-prompt",
                "--installation-dir",
                str(self.installation_dir),
            ],
            cwd=REPO,
            env=environment,
            input=input_text,
            text=True,
            capture_output=True,
        )

    def test_cli_emits_exactly_one_json_object_for_valid_input(self):
        completed = self.cli(json.dumps(self.event(prompt="你好"), ensure_ascii=False))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(len(completed.stdout.strip().splitlines()), 1)
        self.assertIn("hookSpecificOutput", json.loads(completed.stdout))

    def test_cli_rejects_malformed_nonobject_and_oversized_input_without_echo(self):
        private_value = "synthetic-stdin-value-must-not-echo"
        cases = (
            "{\"prompt\": \"" + private_value,
            json.dumps([private_value]),
            "x" * (1024 * 1024 + 1) + private_value,
        )

        for input_text in cases:
            with self.subTest(size=len(input_text)):
                completed = self.cli(input_text)
                self.assertEqual(completed.returncode, 25)
                self.assertEqual(completed.stdout, "")
                payload = json.loads(completed.stderr)
                self.assertEqual(payload["code"], "invalid-input")
                self.assertNotIn(private_value, completed.stderr)


if __name__ == "__main__":
    unittest.main()