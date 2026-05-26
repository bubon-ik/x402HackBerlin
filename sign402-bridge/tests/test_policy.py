import unittest

from sign402_bridge.policy import canonicalize_policy, hash_policy


class PolicyTests(unittest.TestCase):
    def test_canonicalize_policy_sorts_keys_and_removes_spaces(self):
        policy = {
            "maxBudgetAtomic": "1000000",
            "agentId": "hermes-demo",
            "asset": "ALGO_TEST",
        }

        self.assertEqual(
            canonicalize_policy(policy),
            '{"agentId":"hermes-demo","asset":"ALGO_TEST","maxBudgetAtomic":"1000000"}',
        )

    def test_hash_policy_is_stable_for_key_order(self):
        first = {
            "agentId": "hermes-demo",
            "asset": "ALGO_TEST",
            "maxBudgetAtomic": "1000000",
        }
        second = {
            "maxBudgetAtomic": "1000000",
            "asset": "ALGO_TEST",
            "agentId": "hermes-demo",
        }

        self.assertEqual(hash_policy(first), hash_policy(second))
        self.assertEqual(len(hash_policy(first)), 64)


if __name__ == "__main__":
    unittest.main()
