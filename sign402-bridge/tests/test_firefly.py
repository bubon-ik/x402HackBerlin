import unittest

from sign402_bridge.firefly import (
    format_payment_context_command,
    parse_payment_approval,
    parse_policy_approval,
)


class FireflyTests(unittest.TestCase):
    def test_parse_policy_approval_response(self):
        policy_hash = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
        raw = "\n".join(
            [
                f"<policy.approved=buffer:{policy_hash} (32 bytes)",
                "<device.model=number:262",
                "<device.serial=number:1056",
                "<OK",
            ]
        )

        approval = parse_policy_approval(raw)

        self.assertTrue(approval["approved"])
        self.assertEqual(approval["approvedHash"], policy_hash)
        self.assertEqual(approval["deviceModel"], 262)
        self.assertEqual(approval["deviceSerial"], 1056)

    def test_parse_rejects_missing_ok(self):
        raw = "<policy.approved=buffer:00 (1 bytes)\n<device.model=number:262"

        with self.assertRaises(ValueError):
            parse_policy_approval(raw)

    def test_parse_payment_approval_response(self):
        payment_hash = "ffeeddccbbaa99887766554433221100ffeeddccbbaa99887766554433221100"
        raw = "\n".join(
            [
                f"<payment.approved=buffer:{payment_hash} (32 bytes)",
                "<device.model=number:262",
                "<device.serial=number:1056",
                "<OK",
            ]
        )

        approval = parse_payment_approval(raw)

        self.assertTrue(approval["approved"])
        self.assertEqual(approval["approvedHash"], payment_hash)
        self.assertEqual(approval["deviceModel"], 262)
        self.assertEqual(approval["deviceSerial"], 1056)

    def test_parse_payment_rejection_response(self):
        payment_hash = "ffeeddccbbaa99887766554433221100ffeeddccbbaa99887766554433221100"
        raw = "\n".join(
            [
                f"<payment.rejected=buffer:{payment_hash} (32 bytes)",
                "! PAYMENT rejected by user",
                "<ERROR",
            ]
        )

        approval = parse_payment_approval(raw)

        self.assertFalse(approval["approved"])
        self.assertEqual(approval["approvedHash"], payment_hash)
        self.assertEqual(approval["error"], "PAYMENT rejected by user")

    def test_format_payment_context_command_sanitizes_display_lines(self):
        command = format_payment_context_command(
            [
                "x402 WEATHER",
                "0.01 USDC",
                "GoPlausible API | weather\nextra",
                "ignored",
            ]
        )

        self.assertEqual(
            command,
            "PAYMENT-CONTEXT=x402 WEATHER|0.01 USDC|GoPlausible API weather extra",
        )

    def test_format_payment_context_command_truncates_long_lines(self):
        command = format_payment_context_command(
            [
                "official x402 weather resource",
                "100000000000000000000000000000000",
            ]
        )

        self.assertEqual(
            command,
            "PAYMENT-CONTEXT=official x402 weather resource|1000000000000000000000000000000",
        )


if __name__ == "__main__":
    unittest.main()
