import base64
import json
import unittest


class WebPayloadSecurityTests(unittest.TestCase):
    def secure(self, payload):
        from codex_router.security import secure_web_payload

        return secure_web_payload(payload)

    def test_safe_payload_is_allowed_without_rewrite(self):
        payload = {
            "task": "Review this synthetic design",
            "local_sol_output": "No protected material is present.",
            "metadata": {"revision": 1, "enabled": True},
        }

        result = self.secure(payload)

        self.assertEqual(result.decision, "allow")
        self.assertEqual(result.value, payload)
        self.assertEqual(result.categories, ())
        self.assertEqual(dict(result.counts), {})

    def test_redactable_categories_use_deterministic_category_only_tokens(self):
        provider_value = "sk-" + "syntheticProviderTokenValue123"
        assignment_value = "synthetic-assignment-value"
        email = "operator" + "@" + "example.test"
        private_path = "/" + "Users/example/private/project.txt"
        payload = {
            "case_authorization": "Authorization" + ": Bearer synthetic-authorization",
            "case_bearer": "bearer " + "synthetic-bearer-value",
            "case_cookie": "Cookie" + ": session=synthetic-cookie-value",
            "case_session": "session_" + "id=synthetic-session-value",
            "case_assignment": "configuration api_" + "key=" + assignment_value,
            "case_environment": "OPENAI_API" + "_KEY=synthetic-env-value",
            "case_provider": provider_value,
            "case_email": email,
            "case_path": private_path,
            "structured": {"client_" + "secret": "synthetic-structured-value"},
        }

        first = self.secure(payload)
        repeated = self.secure(payload)

        self.assertEqual(first.decision, "redacted")
        self.assertEqual(first, repeated)
        serialized = json.dumps(first.value, ensure_ascii=False, sort_keys=True)
        for protected in (
            provider_value,
            assignment_value,
            email,
            private_path,
            "synthetic-structured-value",
        ):
            self.assertNotIn(protected, serialized)
        self.assertTrue(first.categories)
        self.assertEqual(
            set(first.categories),
            {
                "account_identifier",
                "authorization",
                "bearer_token",
                "cookie",
                "environment_assignment",
                "private_path",
                "provider_token",
                "secret_assignment",
                "session_identifier",
                "structured_secret",
            },
        )
        self.assertTrue(all(name.replace("_", "").isalnum() for name in first.categories))
        self.assertTrue(all(isinstance(count, int) and count > 0 for count in first.counts.values()))
        self.assertNotIn("synthetic", json.dumps(dict(first.counts), sort_keys=True))
        self.assertEqual(self.secure(first.value).decision, "allow")

    def test_nonremovable_and_ambiguous_material_blocks_without_returning_payload(self):
        private_key = "-----BEGIN " + "PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----"
        card = " ".join(("4242",) * 4)
        high_entropy = base64.b64encode(bytes(range(48))).decode("ascii")
        cases = (
            ({"value": private_key}, "private_key"),
            ({"value": card}, "payment_card"),
            ({"value": high_entropy}, "high_entropy"),
            ({"credentials": {"nested": "synthetic"}}, "ambiguous_secret_structure"),
            ({"value": "\ud800"}, "invalid_unicode"),
        )

        for payload, category in cases:
            with self.subTest(category=category):
                result = self.secure(payload)
                self.assertEqual(result.decision, "block")
                self.assertIsNone(result.value)
                self.assertIn(category, result.categories)
                evidence = json.dumps(
                    {"categories": result.categories, "counts": result.counts},
                    ensure_ascii=True,
                )
                self.assertNotIn("synthetic", evidence)

    def test_depth_and_size_limits_fail_closed(self):
        deep = {"value": "safe"}
        for _ in range(20):
            deep = {"nested": deep}
        oversized = {"value": "a" * (1024 * 1024 + 1)}

        for payload in (deep, oversized):
            with self.subTest(kind=next(iter(payload))):
                result = self.secure(payload)
                self.assertEqual(result.decision, "block")
                self.assertIsNone(result.value)
                self.assertIn("input_limit", result.categories)


if __name__ == "__main__":
    unittest.main()
