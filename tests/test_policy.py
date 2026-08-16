import re
import unittest


class PromptPolicyTests(unittest.TestCase):
    def policy(self):
        from codex_router.policy import classify_prompt

        return classify_prompt

    def test_exact_first_line_bypass_is_one_turn_only(self):
        classify = self.policy()
        prompts = (
            "本次不用 Router\n修改 README",
            "本次不用 router。\n审查代码",
            "仅本地执行！\n研究这个方案",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt.splitlines()[0]):
                result = classify(prompt)
                self.assertEqual(result.decision, "bypass")
                self.assertEqual(result.reason_code, "explicit_one_turn_bypass")

    def test_router_direct_markers_force_only_current_turn_local(self):
        classify = self.policy()
        for prompt in ("[CODEX_ROUTER_DIRECT]\n修复 Router", "本轮不用 Luna。\n修复 Router"):
            with self.subTest(prompt=prompt.splitlines()[0]):
                result = classify(prompt)
                self.assertEqual(result.decision, "direct")
                self.assertEqual(result.reason_code, "explicit_one_turn_direct")

    def test_quoted_embedded_example_and_code_directives_do_not_bypass(self):
        classify = self.policy()
        prompts = (
            "“本次不用 Router”是什么意思？",
            "例如：本次不用 Router",
            "请记录本次不用 Router 这句话",
            "```text\n本次不用 Router\n```",
            "> 本次不用 Router",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertNotEqual(classify(prompt).decision, "bypass")

    def test_narrow_direct_allowlist(self):
        classify = self.policy()
        cases = {
            "你好": "casual_greeting",
            "谢谢": "acknowledgement",
            "12 * (3 + 4) 等于多少？": "trivial_arithmetic",
            "什么是不可变对象？": "brief_concept",
            "当前任务状态？": "task_metadata",
            "读取 README.md": "one_step_read_only",
        }

        for prompt, reason in cases.items():
            with self.subTest(prompt=prompt):
                result = classify(prompt)
                self.assertEqual(result.decision, "direct")
                self.assertEqual(result.reason_code, reason)

    def test_substantive_and_ambiguous_prompts_route_by_default(self):
        classify = self.policy()
        prompts = (
            "修改这个文件",
            "审查 PR 的安全性",
            "研究并核实这个说法",
            "比较两个方案并做决定",
            "设计实现计划",
            "执行这三步操作",
            "看看这个怎么办",
        )

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                result = classify(prompt)
                self.assertEqual(result.decision, "route")
                self.assertIn(result.reason_code, {"substantive_request", "ambiguous_default"})

    def test_sensitive_prompt_routes_before_direct_allowlist(self):
        classify = self.policy()
        prompt = "解释这个字段：" + "api_" + "key=synthetic-sensitive-value"

        result = classify(prompt)

        self.assertEqual(result.decision, "route")
        self.assertEqual(result.reason_code, "sensitive_detected")
        self.assertTrue(result.sensitive_categories)


class PolicyIdentityTests(unittest.TestCase):
    def test_same_session_is_stable_and_different_sessions_are_isolated(self):
        from codex_router.policy import derive_driver_context

        secret = bytes(range(32))
        first = derive_driver_context(secret, "synthetic-session-a")
        repeated = derive_driver_context(secret, "synthetic-session-a")
        different = derive_driver_context(secret, "synthetic-session-b")

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, different)
        self.assertRegex(first, re.compile(r"ctx-[0-9a-f]{64}\Z"))
        self.assertNotIn("synthetic-session", first)

    def test_event_identity_binds_session_and_turn(self):
        from codex_router.policy import derive_event_identity

        secret = bytes(reversed(range(32)))
        base = derive_event_identity(secret, "session-a", "turn-a")

        self.assertEqual(base, derive_event_identity(secret, "session-a", "turn-a"))
        self.assertNotEqual(base, derive_event_identity(secret, "session-b", "turn-a"))
        self.assertNotEqual(base, derive_event_identity(secret, "session-a", "turn-b"))
        self.assertRegex(base, re.compile(r"event-[0-9a-f]{64}\Z"))


if __name__ == "__main__":
    unittest.main()
