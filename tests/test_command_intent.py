import unittest


class CommandIntentTests(unittest.TestCase):
    def classify(self, command):
        from codex_router.command_intent import classify_shell_command

        return classify_shell_command(command, codex_binary="/opt/chatgpt/bin/codex")

    def assertDisposition(self, command, expected):
        decision = self.classify(command)
        self.assertEqual(decision.disposition, expected, (command, decision))

    def test_blocks_direct_and_wrapped_codex_execution(self):
        blocked = (
            "codex",
            "codex exec --help",
            "/opt/chatgpt/bin/codex exec --help",
            "env FOO=bar codex exec --help",
            "sh -c 'codex exec --help'",
            "bash -lc 'codex exec --help'",
            "zsh -lc 'codex exec --help'",
            "command codex exec --help",
            "nohup codex exec --help",
        )
        for command in blocked:
            with self.subTest(command=command):
                self.assertDisposition(command, "BLOCK")

    def test_allows_textual_codex_mentions_that_do_not_execute_codex(self):
        allowed = (
            'grep -R "codex" .',
            "cat docs/codex-design.md",
            "find . -name '*codex*'",
            "python -c 'print(\"codex\")'",
            "git diff -- tests/codex_fixture.txt",
        )
        for command in allowed:
            with self.subTest(command=command):
                self.assertDisposition(command, "ALLOW")

    def test_malformed_shell_input_fails_closed(self):
        self.assertDisposition("bash -lc 'unterminated", "FAIL_CLOSED")

    def test_dynamic_interpreter_process_launch_is_explicitly_unverified(self):
        self.assertDisposition(
            "python -c 'import subprocess; subprocess.run([name])'", "UNVERIFIED"
        )


if __name__ == "__main__":
    unittest.main()
