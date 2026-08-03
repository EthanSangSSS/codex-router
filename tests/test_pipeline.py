import json
import os
from pathlib import Path
import tempfile
import time
import unittest


def load_pipeline_api(testcase):
    try:
        from codex_router.pipeline import Router, RouterRunError
        from codex_router.types import StageResult
    except ModuleNotFoundError:
        testcase.fail("codex_router pipeline is not implemented")
    return Router, RouterRunError, StageResult


class RecordingAdapter:
    def __init__(self, stage, calls, result_type, *, failure=None, delay=0):
        self.stage = stage
        self.calls = calls
        self.result_type = result_type
        self.failure = failure
        self.delay = delay

    def run(self, task, context):
        self.calls.append((self.stage, task, context.copy()))
        if self.delay:
            time.sleep(self.delay)
        if self.failure:
            raise self.failure
        return self.result_type(stage=self.stage, content=f"{self.stage}:{task}")


class RouterPipelineTests(unittest.TestCase):
    def build_router(self, root, failure_stage=None, delay_stage=None, timeout=1):
        Router, RouterRunError, StageResult = load_pipeline_api(self)
        calls = []
        adapters = {}
        for stage in ("local_sol", "web_sol", "luna"):
            adapters[stage] = RecordingAdapter(
                stage,
                calls,
                StageResult,
                failure=RuntimeError(f"{stage} failed") if stage == failure_stage else None,
                delay=0.1 if stage == delay_stage else 0,
            )
        return Router(adapters=adapters, state_root=root, timeout_seconds=timeout), calls, RouterRunError

    def test_stages_run_once_in_fixed_order_with_handoffs(self):
        with tempfile.TemporaryDirectory() as tmp:
            router, calls, _ = self.build_router(Path(tmp))
            outcome = router.run("ship it")

            self.assertEqual([call[0] for call in calls], ["local_sol", "web_sol", "luna"])
            self.assertEqual(len(calls), 3)
            self.assertEqual(calls[1][2]["handoff"]["run_id"], outcome.run_id)
            self.assertEqual(calls[1][2]["handoff"]["stage"], "local_sol")
            self.assertEqual(calls[2][2]["handoff"]["stage"], "web_sol")

    def test_local_failure_stops_web_and_luna(self):
        with tempfile.TemporaryDirectory() as tmp:
            router, calls, error_type = self.build_router(Path(tmp), failure_stage="local_sol")
            with self.assertRaises(error_type) as raised:
                router.run("fail locally")

            self.assertEqual([call[0] for call in calls], ["local_sol"])
            failure = json.loads((raised.exception.run_dir / "local-sol.json").read_text())
            self.assertEqual(failure["status"], "failed")
            self.assertFalse((raised.exception.run_dir / "web-sol.json").exists())
            self.assertFalse((raised.exception.run_dir / "luna.json").exists())

    def test_web_failure_stops_luna_without_retrying(self):
        with tempfile.TemporaryDirectory() as tmp:
            router, calls, error_type = self.build_router(Path(tmp), failure_stage="web_sol")
            with self.assertRaises(error_type) as raised:
                router.run("fail on review")

            self.assertEqual([call[0] for call in calls], ["local_sol", "web_sol"])
            self.assertFalse((raised.exception.run_dir / "luna.json").exists())

    def test_keyboard_interrupt_propagates_without_running_downstream_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            router, calls, _ = self.build_router(Path(tmp))
            _, _, StageResult = load_pipeline_api(self)
            router.adapters["local_sol"] = RecordingAdapter(
                "local_sol", calls, StageResult, failure=KeyboardInterrupt()
            )

            with self.assertRaises(KeyboardInterrupt):
                router.run("interrupt locally")

            self.assertEqual([call[0] for call in calls], ["local_sol"])

    def test_run_directory_and_final_result_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            router, _, _ = self.build_router(Path(tmp))
            outcome = router.run("persist me")

            self.assertEqual(outcome.run_dir.parent, Path(tmp))
            self.assertEqual(outcome.final_result, "luna:persist me")
            for name in (
                "request.json",
                "local-sol.json",
                "web-sol.json",
                "luna.json",
                "result.json",
                "events.jsonl",
            ):
                self.assertTrue((outcome.run_dir / name).is_file(), name)
            persisted = json.loads((outcome.run_dir / "result.json").read_text())
            self.assertEqual(persisted["run_id"], outcome.run_id)
            self.assertEqual(persisted["result"], "luna:persist me")
            events = [
                json.loads(line)
                for line in (outcome.run_dir / "events.jsonl").read_text().splitlines()
            ]
            self.assertTrue(events)
            for event in events:
                self.assertIn("stage", event)
                self.assertIn("status", event)
                self.assertIn("duration_ms", event)

    def test_stage_timeout_is_structured_and_stops_downstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            router, calls, error_type = self.build_router(
                Path(tmp), delay_stage="local_sol", timeout=0.01
            )
            with self.assertRaises(error_type) as raised:
                router.run("too slow")

            self.assertEqual([call[0] for call in calls], ["local_sol"])
            self.assertEqual(raised.exception.code, "stage-timeout")

    def test_secret_like_environment_value_is_not_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            router, _, _ = self.build_router(Path(tmp))
            secret = "router-secret-must-not-leak-987654"
            old = os.environ.get("ROUTER_TEST_SECRET")
            os.environ["ROUTER_TEST_SECRET"] = secret
            try:
                outcome = router.run("safe task")
            finally:
                if old is None:
                    os.environ.pop("ROUTER_TEST_SECRET", None)
                else:
                    os.environ["ROUTER_TEST_SECRET"] = old

            combined = b"".join(
                path.read_bytes() for path in outcome.run_dir.iterdir() if path.is_file()
            )
            self.assertNotIn(secret.encode(), combined)


if __name__ == "__main__":
    unittest.main()
