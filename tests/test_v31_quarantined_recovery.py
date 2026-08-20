import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_router import luna_control as control
from codex_router.state import RouterStateError


class QuarantinedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.state.chmod(0o700)
        self.secret = b"v3-control-secret-material-32bytes!"
        self.session_id = "root-session"

    def git(self, cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def init_repo(self, name: str = "repo") -> tuple[Path, str]:
        repo = self.root / name
        repo.mkdir()
        self.git(repo, "init")
        self.git(repo, "config", "user.email", "router-tests@example.invalid")
        self.git(repo, "config", "user.name", "Router Tests")
        (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        self.git(repo, "add", "tracked.txt")
        self.git(repo, "commit", "-m", "baseline")
        return repo, self.git(repo, "rev-parse", "HEAD")

    def new_task(self):
        return control.new_task(
            self.state,
            self.secret,
            self.session_id,
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )

    def bind_luna(self):
        control.reserve_spawn(
            self.state,
            self.secret,
            self.session_id,
            tool_use_id="spawn-old",
            task_name="luna_worker",
            fork_turns="none",
        )
        control.observe_spawn_result(
            self.state,
            self.secret,
            self.session_id,
            tool_use_id="spawn-old",
            task_path="/root/luna_worker",
        )
        return control.observe_subagent_start(
            self.state,
            self.secret,
            self.session_id,
            agent_id="agent-old",
            agent_type="luna_worker",
        )

    def begin(self, workspace: Path, *, authorizations=()):
        return control.begin_packet(
            self.state,
            self.secret,
            self.session_id,
            packet_id="packet-1",
            objective="test isolated recovery",
            working_directory=str(workspace),
            intended_write_scope=("tracked.txt",),
            explicit_side_effect_authorizations=authorizations,
            success_criteria=("done",),
            stop_conditions=("blocked",),
        )

    def quarantine(self, workspace: Path, *, authorizations=()):
        self.new_task()
        self.bind_luna()
        packet = self.begin(workspace, authorizations=authorizations)
        control.start_execution(
            self.state,
            self.secret,
            self.session_id,
            child_turn_id="turn-old",
        )
        control.freeze_authority(
            self.state,
            self.secret,
            self.session_id,
            reason="replacement",
        )
        quarantine_execution = getattr(control, "quarantine_execution", None)
        if quarantine_execution is None:
            self.fail("V3.1 quarantine_execution API is not implemented")
        quarantined = quarantine_execution(
            self.state,
            self.secret,
            self.session_id,
            reason="settlement_unobservable",
        )
        return packet, quarantined

    def clone_independent(self, source: Path, name: str = "replacement") -> Path:
        replacement = self.root / name
        subprocess.run(
            ["git", "clone", "--no-local", str(source), str(replacement)],
            check=True,
            capture_output=True,
            text=True,
        )
        return replacement

    def replace_quarantined(self, workspace: Path, *, profile="profile-B"):
        replace_fn = getattr(control, "replace_quarantined_luna_epoch", None)
        if replace_fn is None:
            self.fail("V3.1 quarantined replacement API is not implemented")
        return replace_fn(
            self.state,
            self.secret,
            self.session_id,
            replacement_workspace=str(workspace),
            native_parent_identity="root-parent",
            native_authority_profile=profile,
            tool_use_id="spawn-new",
            expected_agent_id="agent-new",
        )

    def test_clean_git_packet_records_recovery_baseline(self):
        repo, head = self.init_repo()
        self.new_task()
        packet = self.begin(repo)
        self.assertTrue(hasattr(packet, "recovery_baseline"))
        baseline = packet.recovery_baseline
        self.assertIsNotNone(baseline)
        self.assertEqual(baseline.workspace_root, str(repo.resolve()))
        self.assertEqual(baseline.head_commit, head)
        self.assertTrue(Path(baseline.git_common_dir).is_absolute())

    def test_retirement_clears_recovery_baseline_in_the_authority_transaction(self):
        repo, _head = self.init_repo()
        self.new_task()
        self.bind_luna()
        committed = self.begin(repo)
        self.assertIsNotNone(committed.recovery_baseline)

        with patch.object(
            control, "_locked_state", wraps=control._locked_state
        ) as locked:
            retired = control.retire_luna(
                self.state,
                self.secret,
                self.session_id,
                reason="new_task_epoch",
            )

        mutate_calls = [call for call in locked.call_args_list if call.kwargs["mutate"]]
        self.assertEqual(len(mutate_calls), 1)
        self.assertIsNone(retired.active_packet_id)
        self.assertIsNone(retired.active_child_turn_id)
        self.assertIsNone(retired.authority_packet_wire)
        self.assertEqual(retired.intended_write_scope, ())
        self.assertEqual(retired.explicit_side_effect_authorizations, ())
        self.assertIsNone(retired.recovery_baseline)

    def test_retirement_final_store_failure_keeps_prior_recovery_baseline_journal(self):
        repo, _head = self.init_repo()
        self.new_task()
        self.bind_luna()
        committed = self.begin(repo)
        self.assertIsNotNone(committed.recovery_baseline)
        journal = self.state / control._STATE
        before = journal.read_bytes()

        with patch.object(
            control,
            "_write_state_unlocked",
            side_effect=RouterStateError("conflict", "injected final store failure"),
        ) as write:
            with self.assertRaisesRegex(RouterStateError, "injected final store failure"):
                control.retire_luna(
                    self.state,
                    self.secret,
                    self.session_id,
                    reason="new_task_epoch",
                )

        self.assertEqual(write.call_count, 1)
        self.assertEqual(journal.read_bytes(), before)

    def test_dirty_or_non_git_packet_remains_runnable_without_recovery_baseline(self):
        repo, _head = self.init_repo()
        (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        self.new_task()
        dirty = self.begin(repo)
        self.assertTrue(hasattr(dirty, "recovery_baseline"))
        self.assertIsNone(dirty.recovery_baseline)

        other_state = self.root / "other-state"
        other_state.mkdir()
        other_state.chmod(0o700)
        non_git = self.root / "non-git"
        non_git.mkdir()
        control.new_task(
            other_state,
            self.secret,
            "other-session",
            native_parent_identity="root-parent",
            native_authority_profile="profile-A",
        )
        packet = control.begin_packet(
            other_state,
            self.secret,
            "other-session",
            packet_id="packet-1",
            objective="ordinary non-git work",
            working_directory=str(non_git),
            intended_write_scope=("file.txt",),
            explicit_side_effect_authorizations=(),
            success_criteria=("done",),
            stop_conditions=("blocked",),
        )
        self.assertIsNone(packet.recovery_baseline)

    def test_quarantine_is_not_settlement_and_old_result_is_stale(self):
        repo, _head = self.init_repo()
        packet, quarantined = self.quarantine(repo)
        self.assertEqual(quarantined.execution_status, "QUARANTINED")
        self.assertEqual(quarantined.packet_generation, packet.packet_generation)
        self.assertEqual(quarantined.active_child_turn_id, "turn-old")

        with self.assertRaises(RouterStateError):
            control.current_luna(self.state, self.secret, self.session_id)
        with self.assertRaises(RouterStateError):
            control.start_execution(
                self.state,
                self.secret,
                self.session_id,
                child_turn_id="turn-old",
            )
        self.assertEqual(
            control.accept_result(
                self.state,
                self.secret,
                self.session_id,
                generation=packet.packet_generation,
                child_turn_id="turn-old",
            ),
            "STALE",
        )

    def test_interrupted_status_is_rejected_as_settlement(self):
        repo, _head = self.init_repo()
        self.quarantine(repo)
        with self.assertRaises(RouterStateError):
            control.observe_settlement(
                self.state,
                self.secret,
                self.session_id,
                source="verified_native_terminal",
                terminal_status="interrupted",
                child_turn_id="turn-old",
            )

    def test_later_verified_terminal_may_settle_quarantined_execution(self):
        repo, _head = self.init_repo()
        self.quarantine(repo)
        settled = control.observe_settlement(
            self.state,
            self.secret,
            self.session_id,
            source="verified_native_terminal",
            terminal_status="completed",
            child_turn_id="turn-old",
        )
        self.assertEqual(settled.execution_status, "PAUSED_SETTLED")

    def test_isolated_replacement_requires_recovery_baseline(self):
        non_git = self.root / "non-git"
        non_git.mkdir()
        self.quarantine(non_git)
        replacement, _head = self.init_repo("replacement")
        with self.assertRaises(RouterStateError):
            self.replace_quarantined(replacement)

    def test_isolated_replacement_rejects_active_a1_authorization(self):
        repo, _head = self.init_repo()
        self.quarantine(repo, authorizations=("git_push",))
        replacement = self.clone_independent(repo)
        with self.assertRaises(RouterStateError):
            self.replace_quarantined(replacement)

    def test_isolated_replacement_rejects_same_path_linked_dirty_wrong_head_or_profile(self):
        scenarios = ("same-path", "linked", "dirty", "wrong-head", "same-profile")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                case = self.root / scenario
                case.mkdir()
                state = case / "state"
                state.mkdir()
                state.chmod(0o700)
                repo = case / "repo"
                repo.mkdir()
                self.git(repo, "init")
                self.git(repo, "config", "user.email", "router-tests@example.invalid")
                self.git(repo, "config", "user.name", "Router Tests")
                (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
                self.git(repo, "add", "tracked.txt")
                self.git(repo, "commit", "-m", "baseline")

                old_state = self.state
                old_session = self.session_id
                self.state = state
                self.session_id = f"session-{scenario}"
                try:
                    self.quarantine(repo)
                    if scenario == "same-path":
                        replacement = repo
                        profile = "profile-B"
                    elif scenario == "linked":
                        replacement = case / "linked"
                        self.git(repo, "worktree", "add", "-b", f"branch-{scenario}", str(replacement))
                        profile = "profile-B"
                    else:
                        replacement = case / "replacement"
                        subprocess.run(
                            ["git", "clone", "--no-local", str(repo), str(replacement)],
                            check=True,
                            capture_output=True,
                            text=True,
                        )
                        profile = "profile-A" if scenario == "same-profile" else "profile-B"
                        if scenario == "dirty":
                            (replacement / "tracked.txt").write_text("dirty\n", encoding="utf-8")
                        if scenario == "wrong-head":
                            self.git(replacement, "config", "user.email", "router-tests@example.invalid")
                            self.git(replacement, "config", "user.name", "Router Tests")
                            (replacement / "other.txt").write_text("next\n", encoding="utf-8")
                            self.git(replacement, "add", "other.txt")
                            self.git(replacement, "commit", "-m", "different head")
                    with self.assertRaises(RouterStateError):
                        self.replace_quarantined(replacement, profile=profile)
                finally:
                    self.state = old_state
                    self.session_id = old_session

    def test_independent_clean_repo_replaces_quarantined_luna_and_keeps_generation_monotonic(self):
        repo, head = self.init_repo()
        original = self.new_task()
        self.bind_luna()
        packet = self.begin(repo)
        control.start_execution(
            self.state,
            self.secret,
            self.session_id,
            child_turn_id="turn-old",
        )
        control.freeze_authority(
            self.state,
            self.secret,
            self.session_id,
            reason="replacement",
        )
        quarantine_execution = getattr(control, "quarantine_execution", None)
        if quarantine_execution is None:
            self.fail("V3.1 quarantine_execution API is not implemented")
        quarantine_execution(
            self.state,
            self.secret,
            self.session_id,
            reason="settlement_unobservable",
        )

        replacement_repo = self.clone_independent(repo)
        self.assertEqual(self.git(replacement_repo, "rev-parse", "HEAD"), head)
        replacement = self.replace_quarantined(replacement_repo)

        self.assertEqual(replacement.task_epoch, original.task_epoch)
        self.assertNotEqual(replacement.luna_epoch, original.luna_epoch)
        self.assertEqual(replacement.packet_generation, packet.packet_generation)
        self.assertEqual(replacement.execution_status, "IDLE")
        self.assertIsNone(replacement.active_packet_id)
        self.assertIsNone(replacement.active_child_turn_id)
        self.assertIsNone(replacement.recovery_baseline)
        self.assertIsNotNone(replacement.pending_spawn)
        self.assertEqual(replacement.pending_spawn.luna_epoch, replacement.luna_epoch)

        next_packet = control.begin_packet(
            self.state,
            self.secret,
            self.session_id,
            packet_id="packet-2",
            objective="continue isolated recovery",
            working_directory=str(replacement_repo),
            intended_write_scope=("tracked.txt",),
            explicit_side_effect_authorizations=(),
            success_criteria=("done",),
            stop_conditions=("blocked",),
        )
        self.assertEqual(next_packet.packet_generation, packet.packet_generation + 1)


if __name__ == "__main__":
    unittest.main()
