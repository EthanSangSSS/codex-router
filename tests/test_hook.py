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
        self.assertIn("仅本地执行", output["reason"])
        serialized = json.dumps(output, ensure_ascii=False)
        self.assertNotIn(protected_prompt, serialized)
        self.assertNotIn("config", serialized.lower())


class HookNativeDelegationTests(HookTestCase):
    def test_routed_events_are_stateless_native_luna_contexts(self):
        event = self.event()

        first = self.parse_context(self.handle(event))
        repeated = self.parse_context(self.handle(event))
        different = self.parse_context(self.handle(self.event(turn="turn-b")))

        self.assertEqual(first, repeated)
        self.assertEqual(first, different)
        self.assertEqual(
            first,
            {
                "protocol": "codex-router/hook-context/v1",
                "decision": "route",
                "reason": "substantive_request",
                "workflow": "native_luna_worker",
                "sol_role": "plan_review",
                "luna_role": "default_execution",
                "delegation_mode": "sequential_work_packets",
                "luna_agent": "luna_worker",
                "luna_model": "gpt-5.6-luna",
                "luna_reasoning": "max",
                "luna_lifecycle": "persistent_per_parent_task",
                "capacity_failure_policy": "reuse_close_or_block",
                "luna_descendant_policy": "forbidden",
                "initial_context_mode": "packet_only",
                "web_mode": "manual_operator",
            },
        )
        self.assertFalse(self.state_root.exists())

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
