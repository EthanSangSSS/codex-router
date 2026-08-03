import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch


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
        run_dir.mkdir(parents=True, mode=0o700)

        with self.assertRaises(RouterStateError) as raised:
            get_status(state_root=self.state_root, run_id="run-incomplete")

        self.assertEqual(raised.exception.code, "state-corrupt")


if __name__ == "__main__":
    unittest.main()
