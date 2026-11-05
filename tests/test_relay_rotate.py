"""Tests skill/relay_rotate.py against a fake Relay server. All keys here are fake."""
import contextlib
import importlib.util
import io
import json
import os
import socket
import stat
import tempfile
import threading
import time
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

path = Path(__file__).resolve().parent.parent / "skill" / "relay_rotate.py"
spec = importlib.util.spec_from_file_location("relay_rotate", path)
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)
SHIPPED_STORE_SECRET = rr.store_secret

OLD = "rly_" + "A" * 24
NEW = "rly_" + "B" * 24
OLD_KEY = {"id": "kid-old", "created_at": "2026-11-01T00:00:00Z"}
TICKET = "SUP-5521"
SUCCEEDED = {"success": "succeeded"}
FAILED = {"success": "failed"}


class FakeRelay(BaseHTTPRequestHandler):
    mode = "ok"
    list_mode = "ok"
    keys = []
    hits = []

    def log_message(self, *args):
        pass

    def respond(self, code, body=b"", headers=()):
        self.send_response(code)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        FakeRelay.hits.append(("GET", self.path, self.headers.get("Authorization")))
        if FakeRelay.list_mode == "fail_after_post" and any(h[0] == "POST" for h in FakeRelay.hits):
            self.respond(401, OLD.encode())
        else:
            self.respond(200, json.dumps({"keys": FakeRelay.keys}).encode())

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        FakeRelay.hits.append(("POST", self.path, self.headers.get("Authorization"), body))
        mode = FakeRelay.mode
        echo = json.dumps({"key": NEW, "id": "kid-new", "request_auth": f"Bearer {OLD}"}).encode()
        if mode == "ok":
            self.respond(200, echo)
        elif mode == "timeout":
            # The incident: the key is created but the caller never hears back.
            FakeRelay.keys = FakeRelay.keys + [{"id": "kid-orphan", "created_at": "2026-11-04T14:02:00Z"}]
            time.sleep(0.5)
        elif mode == "500":
            self.respond(500, echo)
        elif mode == "401":
            self.respond(401, echo)
        elif mode == "garbage":
            self.respond(200, b"not json " + NEW.encode())
        elif mode == "no_key":
            self.respond(200, b'{"id": "kid-new"}')
        elif mode == "no_id":
            self.respond(200, json.dumps({"key": NEW}).encode())
        elif mode == "key_as_id":
            self.respond(200, json.dumps({"key": NEW, "id": NEW}).encode())
        elif mode == "redirect":
            self.respond(302, b"", [("Location", "/stolen")])


class RelayRotateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRelay)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/v1/keys"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeRelay.mode = "ok"
        FakeRelay.list_mode = "ok"
        FakeRelay.keys = [OLD_KEY]
        FakeRelay.hits = []
        self.stored = {}
        log_dir = tempfile.TemporaryDirectory()
        self.addCleanup(log_dir.cleanup)
        self.log_path = Path(log_dir.name) / "audit.log"
        for patcher in (
            mock.patch.object(rr, "KEYS_URL", self.url),
            mock.patch.object(rr, "TIMEOUT_SECONDS", 0.2),
            mock.patch.object(rr, "AUDIT_LOG", str(self.log_path)),
            mock.patch.object(rr, "store_secret", self.stored.__setitem__),
            mock.patch.dict(os.environ, {"RELAY_KEY": OLD}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.assert_log_has_no_secrets)

    def assert_log_has_no_secrets(self):
        for secret in (OLD, NEW, "rly_", "Bearer"):
            self.assertNotIn(secret, self.log())

    def log(self):
        return self.log_path.read_text() if self.log_path.exists() else ""

    def last_record(self):
        return self.log().splitlines()[-1]

    def run_cli(self, *argv):
        """Every test goes through here, so every path is held to the output contract."""
        out = io.StringIO()
        with mock.patch("sys.argv", ["relay_rotate.py", *argv]):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                with self.assertRaises(SystemExit) as caught:
                    rr.main()
        result = json.loads(out.getvalue())
        self.assertEqual(result["success"], "succeeded" if caught.exception.code == 0 else "failed")
        self.assertIn(caught.exception.code, (0, 1))
        self.assertLessEqual(set(result), {"success", "confirm_token"})
        for secret in (OLD, NEW, "rly_", "Bearer", "kid-", rr.fingerprint(NEW), "fingerprint"):
            self.assertNotIn(secret, out.getvalue())
        return caught.exception.code, result

    def token(self):
        return rr.confirm_token(OLD, "billing-sync", ["kid-old"])

    def rotate_with(self, token):
        return self.run_cli("rotate", "--service", "billing-sync", "--ticket", TICKET, "--confirm", token)

    def rotate(self):
        return self.rotate_with(self.token())

    def posts(self):
        return [hit for hit in FakeRelay.hits if hit[0] == "POST"]

    # Service name and ticket validation

    def test_bad_service_names_are_refused_before_any_call(self):
        for bad in ("-leading", "UPPER", "a b", "a;rm -rf", "../etc", "a\n", "a?x=1", "", "a" * 64, '{"x":1}'):
            with self.subTest(bad=bad):
                # = form, or argparse rejects "-leading" as a flag before the validator sees it.
                code, result = self.run_cli("plan", f"--service={bad}")
                self.assertEqual((code, result), (1, FAILED))
                self.assertIn("reason=invalid_service_name", self.last_record())
        self.assertEqual(FakeRelay.hits, [])

    def test_longest_valid_service_name_is_accepted(self):
        self.assertEqual(self.run_cli("plan", "--service", "a" * 63)[0], 0)

    def test_bad_tickets_are_refused_before_any_call(self):
        for bad in ("sup-5521", "SUP", "SUP-", "-1", "SUP-1\n", "SUP-1 x", "SUP-1;x", OLD, "kid-old", ""):
            with self.subTest(bad=bad):
                code, result = self.run_cli(
                    "rotate", "--service", "billing-sync", f"--ticket={bad}", "--confirm", self.token()
                )
                self.assertEqual((code, result), (1, FAILED))
                self.assertIn("reason=invalid_ticket", self.last_record())
        self.assertEqual(FakeRelay.hits, [])
        self.assertEqual(len(self.log().splitlines()), 10)  # A bad value can't forge a second line.

    def test_rotate_requires_a_ticket(self):
        code, result = self.run_cli("rotate", "--service", "billing-sync", "--confirm", self.token())
        self.assertEqual((code, result), (1, FAILED))
        self.assertEqual(FakeRelay.hits, [])

    # Credential handling

    def test_credential_is_sent_only_in_the_header(self):
        self.rotate()
        for hit in FakeRelay.hits:
            self.assertEqual(hit[2], f"Bearer {OLD}")
            self.assertNotIn("rly_", hit[1])
        self.assertEqual(json.loads(self.posts()[0][3]), {"service": "billing-sync"})

    def test_credential_cannot_come_from_a_flag(self):
        self.assertEqual(self.run_cli("plan", "--service", "billing-sync", "--key", "x")[0], 1)
        self.assertEqual(FakeRelay.hits, [])

    def test_errors_do_not_echo_what_the_agent_passed(self):
        fingerprint = rr.fingerprint(NEW)
        for argv in (
            ["plan", "--service", "billing-sync", "--key-id", "kid-old"],
            ["plan", "--service", "billing-sync", "--key", OLD],
            ["plan", f"--service={OLD}"],
            ["plan", "--service", f"kid-old {fingerprint}"],
            ["rotate", "--service", "billing-sync", "--ticket", "kid-old", "--confirm", fingerprint],
            [f"kid-old-{fingerprint}"],
        ):
            with self.subTest(argv=argv):
                # run_cli fails if any key, key ID or fingerprint is printed.
                self.assertEqual(self.run_cli(*argv), (1, FAILED))

    def test_missing_credential_makes_no_call(self):
        with mock.patch.dict(os.environ, clear=True):
            code, result = self.run_cli("plan", "--service", "billing-sync")
        self.assertEqual((code, result), (1, FAILED))
        self.assertIn("reason=no_credential", self.last_record())
        self.assertEqual(FakeRelay.hits, [])

    def test_secret_store_beats_the_environment(self):
        with mock.patch.object(rr, "fetch_secret", return_value="from-store"):
            self.run_cli("plan", "--service", "billing-sync")
        self.assertEqual(FakeRelay.hits[0][2], "Bearer from-store")

    def test_proxy_environment_is_ignored(self):
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9"}):
            self.assertEqual(self.run_cli("plan", "--service", "billing-sync")[0], 0)

    # Plan and confirm

    def test_plan_returns_only_the_token_and_changes_nothing(self):
        code, result = self.run_cli("plan", "--service", "billing-sync")
        self.assertEqual(code, 0)
        self.assertEqual(result, {**SUCCEEDED, "confirm_token": self.token()})
        self.assertEqual(self.posts(), [])
        self.assertEqual(self.log(), "")

    def test_force_flag_does_not_exist(self):
        code, _ = self.run_cli(
            "rotate", "--service", "billing-sync", "--ticket", TICKET, "--confirm", self.token(), "--force"
        )
        self.assertEqual(code, 1)
        self.assertEqual(FakeRelay.hits, [])

    def test_rotate_requires_a_token(self):
        self.assertEqual(self.run_cli("rotate", "--service", "billing-sync", "--ticket", TICKET)[0], 1)
        self.assertEqual(FakeRelay.hits, [])

    def test_wrong_token_makes_no_rotate_call(self):
        self.assertEqual(self.rotate_with("wrong"), (1, FAILED))
        self.assertIn("reason=confirm_token_invalid", self.last_record())
        self.assertNotIn("outcome=INTENT", self.log())
        self.assertEqual(self.posts(), [])

    def test_non_ascii_token_makes_no_rotate_call(self):
        self.assertEqual(self.rotate_with("é")[0], 1)
        self.assertEqual(self.posts(), [])

    def test_token_from_another_service_is_refused(self):
        token = rr.confirm_token(OLD, "other-service", ["kid-old"])
        self.assertEqual(self.rotate_with(token)[0], 1)
        self.assertEqual(self.posts(), [])

    def test_token_goes_stale_when_keys_change(self):
        token = self.token()
        FakeRelay.keys = [OLD_KEY, {"id": "kid-surprise"}]
        self.assertEqual(self.rotate_with(token), (1, FAILED))
        self.assertIn("reason=confirm_token_invalid", self.last_record())
        self.assertEqual(self.posts(), [])

    # Successful rotation

    def test_rotate_stores_key_and_records_details_only_in_the_log(self):
        self.assertEqual(self.rotate(), (0, SUCCEEDED))
        self.assertEqual(self.stored, {"billing-sync": NEW})
        self.assertEqual(len(self.posts()), 1)
        self.assertIn(
            f"new_key_id=kid-new new_key_fingerprint={rr.fingerprint(NEW)}", self.last_record()
        )

    def test_missing_id_still_stores_the_key(self):
        FakeRelay.mode = "no_id"
        self.assertEqual(self.rotate()[0], 0)
        self.assertEqual(self.stored, {"billing-sync": NEW})
        self.assertIn("new_key_id=unknown", self.last_record())

    def test_key_returned_as_id_is_withheld(self):
        FakeRelay.mode = "key_as_id"
        self.assertEqual(self.rotate()[0], 0)
        self.assertIn("new_key_id=WITHHELD", self.last_record())

    def test_key_shaped_values_in_the_key_list_are_withheld(self):
        for key_shaped in (OLD, "rly-" + "A" * 24, "rly_AAAA-AAAA-AAAA-AAAA-AAAA-AAAA", "x y"):
            with self.subTest(value=key_shaped):
                self.assertEqual(rr.safe(key_shaped), "WITHHELD")
        FakeRelay.keys = [{"id": OLD}]
        token = rr.confirm_token(OLD, "billing-sync", ["WITHHELD"])
        self.assertEqual(self.rotate_with(token)[0], 0)
        self.assertIn("old_key_ids=WITHHELD", self.last_record())

    def test_short_rly_ids_are_not_withheld(self):
        self.assertEqual(rr.safe("rly_kid_123"), "rly_kid_123")

    def test_store_failure_is_failed_and_the_log_says_what_happened(self):
        with mock.patch.object(rr, "store_secret", side_effect=PermissionError(f"could not write {NEW}")):
            self.assertEqual(self.rotate(), (1, FAILED))
        record = self.last_record()
        self.assertIn("outcome=ROTATED_NOT_STORED", record)
        self.assertIn("reason=PermissionError", record)
        self.assertIn(f"new_key_fingerprint={rr.fingerprint(NEW)}", record)

    def test_shipped_store_stub_refuses_rather_than_dropping_the_key(self):
        with self.assertRaises(NotImplementedError):
            SHIPPED_STORE_SECRET("billing-sync", NEW)

    # Failed rotation

    def test_ambiguous_failures_call_once_and_record_unknown_state(self):
        for mode in ("timeout", "500", "garbage", "no_key", "redirect"):
            with self.subTest(mode=mode):
                FakeRelay.mode = mode
                FakeRelay.keys = [OLD_KEY]
                FakeRelay.hits = []
                self.assertEqual(self.rotate(), (1, FAILED))
                self.assertIn("outcome=UNKNOWN_STATE", self.last_record())
                self.assertIn("old_key_ids=kid-old", self.last_record())
                self.assertEqual(len(self.posts()), 1)
                self.assertEqual(self.stored, {})

    def test_redirect_is_not_followed(self):
        FakeRelay.mode = "redirect"
        self.rotate()
        self.assertFalse([hit for hit in FakeRelay.hits if hit[1] == "/stolen"])

    def test_unknown_state_records_the_key_a_timed_out_call_created(self):
        FakeRelay.mode = "timeout"
        self.rotate()
        self.assertIn("new_since_call=kid-orphan", self.last_record())

    def test_unknown_state_survives_listing_failure(self):
        FakeRelay.mode = "500"
        FakeRelay.list_mode = "fail_after_post"
        self.assertEqual(self.rotate(), (1, FAILED))
        record = self.last_record()
        self.assertIn("outcome=UNKNOWN_STATE", record)
        self.assertIn("new_since_call=unavailable_HTTP_401", record)

    def test_definite_rejection_is_not_unknown_state(self):
        FakeRelay.mode = "401"
        self.assertEqual(self.rotate(), (1, FAILED))
        self.assertIn("outcome=NOT_ROTATED", self.last_record())
        self.assertNotIn("UNKNOWN_STATE", self.log())
        self.assertEqual(len(self.posts()), 1)

    # Retry only on connection refused

    def opener_raising(self, *results):
        opener = mock.Mock()
        opener.open.side_effect = results
        return opener

    def test_refused_retries_then_succeeds(self):
        refused = urllib.error.URLError(ConnectionRefusedError())
        opener = self.opener_raising(refused, refused, io.BytesIO(b'{"ok": true}'))
        with mock.patch.object(rr.urllib.request, "build_opener", return_value=opener):
            with mock.patch.object(rr.time, "sleep") as sleep:
                self.assertEqual(rr.call(OLD, "http://x"), {"ok": True})
        self.assertEqual(opener.open.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_refused_gives_up_after_the_retry_limit(self):
        refused = urllib.error.URLError(ConnectionRefusedError())
        opener = self.opener_raising(*[refused] * 10)
        with mock.patch.object(rr.urllib.request, "build_opener", return_value=opener):
            with mock.patch.object(rr.time, "sleep"):
                with self.assertRaises(urllib.error.URLError):
                    rr.call(OLD, "http://x")
        self.assertEqual(opener.open.call_count, rr.REFUSED_RETRIES + 1)

    def test_other_failures_are_not_retried(self):
        for error in (
            urllib.error.URLError(TimeoutError()),
            urllib.error.URLError(ConnectionResetError()),
            urllib.error.URLError(socket.gaierror()),
            TimeoutError(),
        ):
            with self.subTest(error=repr(error)):
                opener = self.opener_raising(error)
                with mock.patch.object(rr.urllib.request, "build_opener", return_value=opener):
                    with self.assertRaises(type(error)):
                        rr.call(OLD, "http://x")
                self.assertEqual(opener.open.call_count, 1)

    def test_a_real_refused_socket_is_recognised(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with mock.patch.object(rr, "KEYS_URL", f"http://127.0.0.1:{port}/v1/keys"):
            with mock.patch.object(rr.time, "sleep") as sleep:
                code, result = self.run_cli("plan", "--service", "billing-sync")
        self.assertEqual((code, result), (1, FAILED))
        self.assertIn("reason=connection_refused", self.last_record())
        self.assertEqual(sleep.call_count, rr.REFUSED_RETRIES)

    def test_refused_rotate_call_is_not_rotated_rather_than_unknown(self):
        refused = urllib.error.URLError(ConnectionRefusedError())
        with mock.patch.object(rr, "call", side_effect=[{"keys": [OLD_KEY]}, refused]):
            self.assertEqual(self.rotate(), (1, FAILED))
        self.assertIn("outcome=NOT_ROTATED", self.last_record())
        self.assertNotIn("UNKNOWN_STATE", self.log())

    # Audit trail

    def test_audit_drops_fields_outside_the_allowlist(self):
        summary = rr.audit_summary(service="s", outcome="ROTATED", request=OLD, response=NEW, key=NEW)
        self.assertNotIn("rly_", summary)
        self.assertNotIn("request", summary)

    def test_audit_withholds_key_shaped_values_in_allowed_fields(self):
        summary = rr.audit_summary(service=OLD, outcome="ROTATED", old_key_ids=[NEW, "kid-1"])
        self.assertNotIn("rly_", summary)
        self.assertIn("service=WITHHELD", summary)
        self.assertIn("old_key_ids=WITHHELD,kid-1", summary)

    def test_every_rotate_after_the_token_check_leaves_intent_then_outcome_under_the_ticket(self):
        for mode, outcome in (("ok", "ROTATED"), ("500", "UNKNOWN_STATE"), ("401", "NOT_ROTATED")):
            with self.subTest(mode=mode):
                FakeRelay.mode = mode
                self.log_path.unlink(missing_ok=True)
                self.rotate()
                intent, result = self.log().splitlines()
                self.assertIn("outcome=INTENT", intent)
                self.assertIn(f"outcome={outcome}", result)
                for record in (intent, result):
                    self.assertIn(f"ticket={TICKET} service=billing-sync", record)

    def test_intent_is_on_disk_before_the_rotate_call(self):
        seen = []
        real_call = rr.call

        def spy(credential, url, data=None):
            if data is not None:
                seen.append(self.log())
            return real_call(credential, url, data)

        with mock.patch.object(rr, "call", spy):
            self.rotate()
        self.assertEqual(len(seen), 1)
        self.assertIn("outcome=INTENT", seen[0])

    def test_no_rotation_if_the_intent_cannot_be_written(self):
        with mock.patch.object(rr, "AUDIT_LOG", str(self.log_path.parent / "missing" / "audit.log")):
            self.assertEqual(self.rotate(), (1, FAILED))
        self.assertEqual(self.posts(), [])
        self.assertEqual(self.stored, {})

    def test_rotation_does_not_count_as_done_if_the_outcome_cannot_be_written(self):
        real_write = rr.write_audit

        def fail_on_outcome(**fields):
            if fields["outcome"] != "INTENT":
                raise OSError("disk full")
            real_write(**fields)

        with mock.patch.object(rr, "write_audit", fail_on_outcome):
            self.assertEqual(self.rotate(), (1, FAILED))
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(self.stored, {"billing-sync": NEW})  # The only copy of the key survives.
        self.assertEqual(len(self.log().splitlines()), 1)  # The intent is the trail on-call follows.
        self.assertIn("outcome=INTENT", self.last_record())

    def test_log_appends_and_only_its_owner_can_read_it(self):
        self.rotate()
        first = self.log()
        self.rotate_with("wrong")
        self.assertTrue(self.log().startswith(first))
        self.assertEqual(stat.S_IMODE(self.log_path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
