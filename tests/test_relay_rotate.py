"""Tests skill/relay_rotate.py against a fake Relay server. All keys here are fake."""
import contextlib
import importlib.util
import io
import json
import os
import socket
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
        for patcher in (
            mock.patch.object(rr, "KEYS_URL", self.url),
            mock.patch.object(rr, "TIMEOUT_SECONDS", 0.2),
            mock.patch.object(rr, "store_secret", self.stored.__setitem__),
            mock.patch.dict(os.environ, {"RELAY_KEY": OLD}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_cli(self, *argv):
        out = io.StringIO()
        with mock.patch("sys.argv", ["relay_rotate.py", *argv]):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                with self.assertRaises(SystemExit) as caught:
                    rr.main()
        text = out.getvalue()
        for secret in (OLD, NEW, "rly_", "Bearer"):
            self.assertNotIn(secret, text)
        return caught.exception.code, text

    def token(self):
        return rr.confirm_token(OLD, "billing-sync", ["kid-old"])

    def rotate(self):
        return self.run_cli("rotate", "--service", "billing-sync", "--confirm", self.token())

    def posts(self):
        return [hit for hit in FakeRelay.hits if hit[0] == "POST"]

    # Service name validation

    def test_bad_service_names_are_refused_before_any_call(self):
        for bad in ("-leading", "UPPER", "a b", "a;rm -rf", "../etc", "a\n", "a?x=1", "", "a" * 64, '{"x":1}'):
            with self.subTest(bad=bad):
                # = form, or argparse rejects "-leading" as a flag before the validator sees it.
                code, text = self.run_cli("plan", f"--service={bad}")
                self.assertEqual(code, 1)
                self.assertIn("invalid_service_name", text)
        self.assertEqual(FakeRelay.hits, [])

    def test_longest_valid_service_name_is_accepted(self):
        self.assertEqual(self.run_cli("plan", "--service", "a" * 63)[0], 0)

    # Credential handling

    def test_credential_is_sent_only_in_the_header(self):
        self.rotate()
        for hit in FakeRelay.hits:
            self.assertEqual(hit[2], f"Bearer {OLD}")
            self.assertNotIn("rly_", hit[1])
        self.assertEqual(json.loads(self.posts()[0][3]), {"service": "billing-sync"})

    def test_credential_cannot_come_from_a_flag(self):
        self.assertEqual(self.run_cli("plan", "--service", "billing-sync", "--key", "x")[0], 2)

    def test_missing_credential_makes_no_call(self):
        with mock.patch.dict(os.environ, clear=True):
            code, text = self.run_cli("plan", "--service", "billing-sync")
        self.assertEqual(code, 1)
        self.assertIn("no_credential", text)
        self.assertEqual(FakeRelay.hits, [])

    def test_secret_store_beats_the_environment(self):
        with mock.patch.object(rr, "fetch_secret", return_value="from-store"):
            self.run_cli("plan", "--service", "billing-sync")
        self.assertEqual(FakeRelay.hits[0][2], "Bearer from-store")

    def test_proxy_environment_is_ignored(self):
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9"}):
            self.assertEqual(self.run_cli("plan", "--service", "billing-sync")[0], 0)

    # Plan and confirm

    def test_plan_lists_keys_prints_token_and_changes_nothing(self):
        code, text = self.run_cli("plan", "--service", "billing-sync")
        self.assertEqual(code, 0)
        self.assertIn("id=kid-old", text)
        self.assertIn(f"CONFIRM TOKEN: {self.token()}", text)
        self.assertEqual(self.posts(), [])

    def test_force_flag_does_not_exist(self):
        code, _ = self.run_cli("rotate", "--service", "billing-sync", "--confirm", self.token(), "--force")
        self.assertEqual(code, 2)
        self.assertEqual(FakeRelay.hits, [])

    def test_rotate_requires_a_token(self):
        self.assertEqual(self.run_cli("rotate", "--service", "billing-sync")[0], 2)
        self.assertEqual(FakeRelay.hits, [])

    def test_wrong_token_makes_no_rotate_call(self):
        code, text = self.run_cli("rotate", "--service", "billing-sync", "--confirm", "wrong")
        self.assertEqual(code, 1)
        self.assertIn("confirm_token_invalid", text)
        self.assertEqual(self.posts(), [])

    def test_non_ascii_token_makes_no_rotate_call(self):
        self.assertEqual(self.run_cli("rotate", "--service", "billing-sync", "--confirm", "é")[0], 1)
        self.assertEqual(self.posts(), [])

    def test_token_from_another_service_is_refused(self):
        token = rr.confirm_token(OLD, "other-service", ["kid-old"])
        self.assertEqual(self.run_cli("rotate", "--service", "billing-sync", "--confirm", token)[0], 1)
        self.assertEqual(self.posts(), [])

    def test_token_goes_stale_when_keys_change(self):
        token = self.token()
        FakeRelay.keys = [OLD_KEY, {"id": "kid-surprise"}]
        code, text = self.run_cli("rotate", "--service", "billing-sync", "--confirm", token)
        self.assertEqual(code, 1)
        self.assertIn("confirm_token_invalid", text)
        self.assertEqual(self.posts(), [])

    # Successful rotation

    def test_rotate_stores_key_and_prints_only_id_and_fingerprint(self):
        code, text = self.rotate()
        self.assertEqual(code, 0)
        self.assertEqual(self.stored, {"billing-sync": NEW})
        self.assertIn(f"new_key_id=kid-new fingerprint={rr.fingerprint(NEW)}", text)
        self.assertEqual(len(self.posts()), 1)

    def test_missing_id_still_stores_the_key(self):
        FakeRelay.mode = "no_id"
        code, text = self.rotate()
        self.assertEqual(code, 0)
        self.assertEqual(self.stored, {"billing-sync": NEW})
        self.assertIn("new_key_id=unknown", text)

    def test_key_returned_as_id_is_withheld(self):
        FakeRelay.mode = "key_as_id"
        code, text = self.rotate()
        self.assertEqual(code, 0)
        self.assertIn("new_key_id=WITHHELD", text)

    def test_key_shaped_values_in_the_key_list_are_withheld(self):
        for key_shaped in (OLD, "rly-" + "A" * 24, "rly_AAAA-AAAA-AAAA-AAAA-AAAA-AAAA", "x y"):
            with self.subTest(value=key_shaped):
                self.assertEqual(rr.safe(key_shaped), "WITHHELD")
        FakeRelay.keys = [{"id": OLD}]
        code, text = self.run_cli("plan", "--service", "billing-sync")
        self.assertEqual(code, 0)
        self.assertIn("id=WITHHELD", text)

    def test_short_rly_ids_are_not_withheld(self):
        self.assertEqual(rr.safe("rly_kid_123"), "rly_kid_123")

    def test_store_stub_raises_and_rotate_escalates_without_printing_key(self):
        with mock.patch.object(rr, "store_secret", side_effect=PermissionError(f"could not write {NEW}")):
            code, text = self.rotate()
        self.assertEqual(code, 4)
        self.assertIn("ROTATED NOT STORED", text)
        self.assertIn(f"fingerprint={rr.fingerprint(NEW)}", text)

    def test_shipped_store_stub_refuses_rather_than_dropping_the_key(self):
        with self.assertRaises(NotImplementedError):
            SHIPPED_STORE_SECRET("billing-sync", NEW)

    # Failed rotation

    def test_ambiguous_failures_call_once_and_report_unknown_state(self):
        for mode in ("timeout", "500", "garbage", "no_key", "redirect"):
            with self.subTest(mode=mode):
                FakeRelay.mode = mode
                FakeRelay.keys = [OLD_KEY]
                FakeRelay.hits = []
                code, text = self.rotate()
                self.assertEqual(code, 3)
                self.assertIn("UNKNOWN STATE", text)
                self.assertIn("id=kid-old", text)
                self.assertEqual(len(self.posts()), 1)
                self.assertEqual(self.stored, {})

    def test_redirect_is_not_followed(self):
        FakeRelay.mode = "redirect"
        self.rotate()
        self.assertFalse([hit for hit in FakeRelay.hits if hit[1] == "/stolen"])

    def test_unknown_state_flags_the_key_a_timed_out_call_created(self):
        FakeRelay.mode = "timeout"
        _, text = self.rotate()
        self.assertIn("id=kid-old created_at=2026-11-01T00:00:00Z new_since_call=no", text)
        self.assertIn("id=kid-orphan created_at=2026-11-04T14:02:00Z new_since_call=yes", text)

    def test_unknown_state_survives_listing_failure(self):
        FakeRelay.mode = "500"
        FakeRelay.list_mode = "fail_after_post"
        code, text = self.rotate()
        self.assertEqual(code, 3)
        self.assertIn("UNKNOWN STATE", text)
        self.assertIn("CURRENT KEYS UNAVAILABLE: reason=HTTP_401", text)

    def test_definite_rejection_is_not_unknown_state(self):
        FakeRelay.mode = "401"
        code, text = self.rotate()
        self.assertEqual(code, 1)
        self.assertIn("NOT ROTATED", text)
        self.assertNotIn("UNKNOWN STATE", text)
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
                code, text = self.run_cli("plan", "--service", "billing-sync")
        self.assertEqual(code, 1)
        self.assertIn("reason=connection_refused", text)
        self.assertEqual(sleep.call_count, rr.REFUSED_RETRIES)

    def test_refused_rotate_call_is_not_rotated_rather_than_unknown(self):
        refused = urllib.error.URLError(ConnectionRefusedError())
        with mock.patch.object(rr, "call", side_effect=[{"keys": [OLD_KEY]}, refused]):
            code, text = self.rotate()
        self.assertEqual(code, 1)
        self.assertIn("NOT ROTATED", text)
        self.assertNotIn("UNKNOWN STATE", text)

    # Audit summary

    def test_audit_drops_fields_outside_the_allowlist(self):
        summary = rr.audit_summary(service="s", outcome="ROTATED", request=OLD, response=NEW, key=NEW)
        self.assertNotIn("rly_", summary)
        self.assertNotIn("request", summary)

    def test_audit_withholds_key_shaped_values_in_allowed_fields(self):
        summary = rr.audit_summary(service=OLD, outcome="ROTATED", old_key_ids=[NEW, "kid-1"])
        self.assertNotIn("rly_", summary)
        self.assertIn("service=WITHHELD", summary)
        self.assertIn("old_key_ids=WITHHELD,kid-1", summary)

    def test_every_rotate_outcome_after_the_call_prints_an_audit_line(self):
        for mode, outcome in (("ok", "ROTATED"), ("500", "UNKNOWN_STATE"), ("401", "NOT_ROTATED")):
            with self.subTest(mode=mode):
                FakeRelay.mode = mode
                _, text = self.rotate()
                self.assertIn("AUDIT: relay-rotate", text)
                self.assertIn(f"outcome={outcome}", text)


if __name__ == "__main__":
    unittest.main()
