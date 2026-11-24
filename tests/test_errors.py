import unittest
from pathlib import Path

from freerdc.freerdp import Attempt, diagnose, timeout_diagnosis
from freerdc.freerdp.errors import error_names

FIXTURES = Path(__file__).parent / "fixtures"  # trimmed real output, FreeRDP 2.11.7 / 3.15.0
AT = Attempt(target="192.0.2.10:3389", username="someuser")


def log(name: str) -> str:
    return (FIXTURES / f"err_{name}.log").read_text()


class DiagnoseRealLogsTest(unittest.TestCase):
    def test_wrong_password_both_versions(self):
        for name, rc in (("wrongpw_v3", 134), ("wrongpw_v2", 134)):
            d = diagnose(log(name), rc, AT)
            self.assertEqual(d.code, "ERRCONNECT_LOGON_FAILURE", name)
            self.assertIn("someuser", d.message)

    def test_wayland_client_exit_255_is_still_recognised_from_the_log(self):
        self.assertEqual(diagnose(log("wrongpw_v3"), 255, AT).code, "ERRCONNECT_LOGON_FAILURE")

    def test_dns(self):
        self.assertEqual(diagnose(log("dns_v3"), 140, AT).code, "ERRCONNECT_DNS_NAME_NOT_FOUND")

    def test_unreachable_times_out(self):
        d = diagnose(log("unreachable_v3"), 141, AT)
        self.assertEqual(d.code, "ERRCONNECT_CONNECT_FAILED")
        self.assertIn("did not answer", d.message)

    def test_refused_and_reset_are_transport_failures(self):
        for name in ("refused_v3", "reset_v3"):
            self.assertEqual(diagnose(log(name), 147, AT).code, "ERRCONNECT_CONNECT_TRANSPORT_FAILED")

    def test_forced_security_mode_is_called_out_on_transport_failure(self):
        forced = Attempt(target="h:3389", security="rdp")
        self.assertIn("Security is fixed to RDP", diagnose(log("secrdp_nla_v3"), 147, forced).hint)
        self.assertNotIn("fixed", diagnose(log("secrdp_nla_v3"), 147, AT).hint)

    def test_nla_required_names_the_reason(self):
        for name in ("sectls_nla_v3", "sectls_nla_v2"):
            d = diagnose(log(name), 133, Attempt(target="h:3389", security="tls"))
            self.assertEqual(d.code, "ERRCONNECT_SECURITY_NEGO_CONNECT_FAILED")
            self.assertIn("Network Level Authentication", d.message)

    def test_empty_password_on_freerdp3_is_not_reported_as_cancelled(self):
        d = diagnose(log("emptypw_v3"), 145, AT)
        self.assertEqual(d.title, "Credentials missing")

    def test_missing_credentials_freerdp2(self):
        self.assertEqual(diagnose(log("nocreds_v2"), 159, AT).code, "ERRCONNECT_NO_OR_MISSING_CREDENTIALS")

    def test_session_taken_over(self):
        d = diagnose(log("takeover_v2"), 5, AT)
        self.assertTrue(d.informative)
        self.assertEqual(d.title, "Session taken over")
        d3 = diagnose(log("takeover_v3"), 1, AT)
        self.assertTrue(d3.informative)
        self.assertEqual(d3.code, "ERRINFO_RPC_INITIATED_DISCONNECT")


class DiagnoseOtherTest(unittest.TestCase):
    def test_cancelled_by_us_is_silent(self):
        self.assertTrue(diagnose("anything ERRCONNECT_LOGON_FAILURE", 143, AT, cancelled=True).silent)

    def test_normal_end_is_silent(self):
        self.assertTrue(diagnose("", 0, AT).silent)
        self.assertTrue(diagnose("[ERROR] ERRINFO_LOGOFF_BY_USER [0x0001000C]", 12, AT).silent)
        self.assertTrue(diagnose("ERRINFO_RPC_INITIATED_DISCONNECT_BY_USER", 11, AT).silent)

    def test_specific_cause_beats_generic_noise(self):
        text = "ERRCONNECT_CONNECT_TRANSPORT_FAILED ... ERRCONNECT_LOGON_FAILURE ... ERRCONNECT_CONNECT_CANCELLED"
        self.assertEqual(diagnose(text, 255, AT).code, "ERRCONNECT_LOGON_FAILURE")

    def test_names_known_only_from_the_source(self):
        for name, snippet in (("ACCOUNT_LOCKED_OUT", "locked"), ("ACCOUNT_DISABLED", "disabled"),
                              ("PASSWORD_EXPIRED", "expired"), ("LOGON_TYPE_NOT_GRANTED", "log on"),
                              ("INSUFFICIENT_PRIVILEGES", "permission")):
            d = diagnose(f"[ERROR] ERRCONNECT_{name} [0x1]", 255, AT)
            self.assertEqual(d.code, f"ERRCONNECT_{name}")
            self.assertIn(snippet, d.message.lower())

    def test_exit_code_fallback_when_no_name_was_logged(self):
        self.assertEqual(diagnose("", 134, AT).code, "ERRCONNECT_LOGON_FAILURE")
        self.assertEqual(diagnose("", 5, AT).title, "Session taken over")

    def test_unknown_failure_falls_back_to_generic_text(self):
        d = diagnose("something odd", 255, AT)
        self.assertEqual(d.title, "Connection failed")
        self.assertIn("255", d.message)

    def test_saved_certificate_mode_message(self):
        d = diagnose("ERRCONNECT_TLS_CONNECT_FAILED", 143, Attempt(target="h:3389", cert_mode="saved"))
        self.assertIn("trusted list", d.message)

    def test_timeout_message(self):
        d = timeout_diagnosis(Attempt(target="h:3389", timeout_s=30))
        self.assertEqual(d.code, "TIMEOUT")
        self.assertIn("30 seconds", d.message)

    def test_error_names_deduplicated_in_order(self):
        self.assertEqual(error_names("ERRCONNECT_B ERRINFO_X ERRCONNECT_B"), ["ERRCONNECT_B", "ERRINFO_X"])


if __name__ == "__main__":
    unittest.main()
