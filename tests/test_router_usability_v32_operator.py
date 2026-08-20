from contextlib import redirect_stdout
from io import StringIO
import unittest

from codex_router import cli
from codex_router import global_install_adapter as adapter


class RouterUsabilityV32OperatorTests(unittest.TestCase):
    _V1_NO_FOLLOWUP = {
        "sideband_structured_k1_staging": True,
        "multi_agent_v1__spawn_agent": True,
        "followup_task": False,
    }

    def test_stage_k1_fields_help_exposes_request_file_mode(self) -> None:
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
            cli.main(["stage-k1-fields", "--help"])

        self.assertEqual(stopped.exception.code, 0)
        text = output.getvalue()
        self.assertIn("--request-file", text)
        self.assertIn("V3.2", text)
        self.assertNotIn("stage-k1-request", text)

    def test_missing_legacy_fields_still_fail_closed(self) -> None:
        result = cli.main(
            [
                "stage-k1-fields",
                "--installation-dir",
                "/nonexistent",
                "--session-id",
                "session",
                "--root-turn-id",
                "turn",
                "--capability",
                "capability",
            ]
        )
        self.assertNotEqual(result, 0)

    def test_followup_unavailable_degrades_only_when_safe_and_non_strict(self) -> None:
        safe = adapter.primary_gen2_readiness(
            self._V1_NO_FOLLOWUP,
            strict_router=False,
            primary_fallback_state="SAFE_LOCAL_FALLBACK",
        )
        strict = adapter.primary_gen2_readiness(
            self._V1_NO_FOLLOWUP,
            strict_router=True,
            primary_fallback_state="SAFE_LOCAL_FALLBACK",
        )
        unsafe = adapter.primary_gen2_readiness(
            self._V1_NO_FOLLOWUP,
            strict_router=False,
            primary_fallback_state="BLOCKED_ACTIVE_AUTHORITY",
        )

        self.assertEqual(safe["code"], "UNAVAILABLE_DEGRADE_ALLOWED")
        self.assertEqual(strict["code"], "UNAVAILABLE_STRICT_BLOCK")
        self.assertEqual(unsafe["code"], "UNAVAILABLE_SAFETY_BLOCK")

    def test_v31_one_argument_followup_classification_is_preserved(self) -> None:
        legacy = adapter.primary_gen2_readiness(self._V1_NO_FOLLOWUP)
        self.assertEqual(
            legacy["code"],
            "BLOCKED_NATIVE_FOLLOWUP_UNAVAILABLE",
        )

    def test_policy_text_treats_absent_strict_flag_as_non_strict(self) -> None:
        text = adapter.AGENTS_BLOCK_V3
        self.assertIn("ordinary fresh routes omit it", text)
        self.assertIn("structured staging error", text)
        self.assertIn("SAFE_LOCAL_FALLBACK", text)

    def test_v32_luna_instructions_do_not_contain_denial_retry_protocol(self) -> None:
        text = adapter.LUNA_DEVELOPER_INSTRUCTIONS_V3
        self.assertIn("allowlisted bootstrap probe", text)
        self.assertIn('{"command":"pwd"}', text)
        self.assertNotIn("Router is expected to deny the probe", text)
        self.assertNotIn("Legacy deny-retry compatibility text applies", text)


if __name__ == "__main__":
    unittest.main()
