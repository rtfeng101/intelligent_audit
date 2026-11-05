#!/usr/bin/env python3
"""Plan and perform a Relay key rotation. The caller learns only whether it worked.

Usage:
  relay_rotate.py plan --service NAME
  relay_rotate.py rotate --service NAME --ticket TICKET --confirm TOKEN

Prints {"success": "succeeded"} and exits 0, or {"success": "failed"} and exits 1. plan's success
also carries confirm_token. Every detail, including key IDs and fingerprints, goes to AUDIT_LOG.
Nothing here writes to a ticket: look up the log by ticket ID.

Assumed, because the packet only documents POST /v1/keys/rotate and "contains the new key":
  GET /v1/keys?service=NAME returns {"keys": [{"id": ..., "created_at": ...}]}
  POST /v1/keys/rotate returns {"key": ..., "id": ...}
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# Constants, not env vars or flags: a caller who could change the URL could collect the credential.
KEYS_URL = "https://relay.example.internal/v1/keys"
CREDENTIAL_ENV = "RELAY_KEY"
TIMEOUT_SECONDS = 30
REFUSED_RETRIES = 2
REFUSED_WAIT_SECONDS = 5
AUDIT_LOG = "/var/log/relay-rotate/audit.log"
SERVICE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
TICKET_RE = re.compile(r"[A-Z][A-Z0-9]{1,30}-[0-9]{1,10}")
PRINTABLE_RE = re.compile(r"[A-Za-z0-9_.:+-]{1,64}")
DEFINITE_REJECTIONS = (400, 401, 403, 404, 422)
AUDIT_TEMPLATE = (
    "relay-rotate at={at} ticket={ticket} service={service} outcome={outcome} old_key_ids={old_key_ids} "
    "new_key_id={new_key_id} new_key_fingerprint={new_key_fingerprint} new_since_call={new_since_call} "
    "reason={reason}"
)
AUDIT_FIELDS = (
    "ticket",
    "service",
    "outcome",
    "old_key_ids",
    "new_key_id",
    "new_key_fingerprint",
    "new_since_call",
    "reason",
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # urllib keeps the Authorization header on redirects, which could hand it to another host.
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_secret(service):
    # shortcut: no secret store yet, so RELAY_KEY is the only source. Replace when one exists.
    return None


def store_secret(service, value):
    # shortcut: stub. Raises because a silent no-op would lose the only copy of the new key.
    # Replace before any real rotation: until then every successful rotate exits 4.
    raise NotImplementedError("secret store not connected")


def stop(succeeded, **extra):
    # Fixed words only. The agent can repeat anything it is shown, so detail goes to the audit log.
    print(json.dumps({"success": "succeeded" if succeeded else "failed", **extra}))
    sys.exit(0 if succeeded else 1)


class QuietParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse would quote the bad arguments, and those could be a key the agent was handed.
        stop(False)


def safe(value):
    """Relay's responses are untrusted, so print a value only if it can't be a key."""
    text = str(value)
    key_shaped = re.sub(r"[^A-Za-z0-9]", "", text).lower().startswith("rly") and len(text) >= 27
    return text if PRINTABLE_RE.fullmatch(text) and not key_shaped else "WITHHELD"


def fingerprint(key):
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def confirm_token(credential, service, key_ids):
    # Keyed and tied to the current keys, so it can't be guessed and goes stale if they change.
    # It shows plan ran, not that a human approved. Approval needs a platform prompt.
    message = f"{service}|{','.join(sorted(key_ids))}"
    return hmac.new(credential.encode(), message.encode(), "sha256").hexdigest()[:16]


def audit_summary(**fields):
    """Anything not in AUDIT_FIELDS is dropped, so a request or response can't get in."""
    values = {}
    for name in AUDIT_FIELDS:
        value = fields.get(name, "none")
        values[name] = ",".join(map(safe, value)) if isinstance(value, list) else safe(value)
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return "AUDIT: " + AUDIT_TEMPLATE.format(at=at, **values)


def write_audit(**fields):
    # shortcut: a local file only protects the log if the helper runs as relay-rotator, and root can
    # still edit it. Move to an append-only store the agent can't read before the pilot.
    with open(AUDIT_LOG, "a", opener=lambda path, flags: os.open(path, flags, 0o600)) as log:
        log.write(audit_summary(**fields) + "\n")
        log.flush()
        os.fsync(log.fileno())  # A record still in a buffer isn't an audit trail.


def finish(succeeded, **fields):
    """A rotation only counts as done if its outcome is on record."""
    try:
        write_audit(**fields)
    except Exception:
        # The intent record stays. An intent with no outcome means: check Relay, a key may exist.
        succeeded = False
    stop(succeeded)


def was_refused(error):
    return isinstance(error, urllib.error.URLError) and isinstance(error.reason, ConnectionRefusedError)


def reason_for(error):
    # Never the exception text: it can quote the response or the Authorization header.
    if isinstance(error, urllib.error.HTTPError):
        return f"HTTP_{error.code}"
    return "connection_refused" if was_refused(error) else type(error).__name__


def call(credential, url, data=None):
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {credential}", "Content-Type": "application/json"},
    )
    # The empty ProxyHandler stops HTTPS_PROXY in the caller's environment from rerouting this.
    opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
    for attempt in range(REFUSED_RETRIES + 1):
        try:
            with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                return json.load(response)
        except urllib.error.URLError as error:
            if isinstance(error, urllib.error.HTTPError):
                error.close()
            # Refused is the only retry: it proves the request was never sent.
            if not was_refused(error) or attempt == REFUSED_RETRIES:
                raise
            time.sleep(REFUSED_WAIT_SECONDS)


def list_keys(credential, service):
    return [safe(key["id"]) for key in call(credential, f"{KEYS_URL}?service={service}")["keys"]]


def plan(credential, service):
    stop(True, confirm_token=confirm_token(credential, service, list_keys(credential, service)))


def unknown_state(credential, audit, reason):
    try:
        current = list_keys(credential, audit["service"])
        new_ids = [key_id for key_id in current if key_id not in audit["old_key_ids"]] or "none"
    except Exception as error:
        new_ids = f"unavailable_{reason_for(error)}"
    finish(False, outcome="UNKNOWN_STATE", new_since_call=new_ids, reason=reason, **audit)


def rotate(credential, service, ticket, token):
    old_ids = list_keys(credential, service)
    audit = {"ticket": ticket, "service": service, "old_key_ids": old_ids}
    if not hmac.compare_digest(token, confirm_token(credential, service, old_ids)):
        finish(False, outcome="NOT_ROTATED", reason="confirm_token_invalid", **audit)

    # No trail, no rotation. Relay has no documented undo, so this has to come before the call.
    write_audit(outcome="INTENT", **audit)

    try:
        response = call(credential, f"{KEYS_URL}/rotate", json.dumps({"service": service}).encode())
        new_key = response["key"]
        if not isinstance(new_key, str) or not new_key:
            raise ValueError("no usable key in response")
        audit.update(new_key_id=safe(response.get("id", "unknown")), new_key_fingerprint=fingerprint(new_key))
    except Exception as error:
        reason = reason_for(error)
        rejected = isinstance(error, urllib.error.HTTPError) and error.code in DEFINITE_REJECTIONS
        if not rejected and not was_refused(error):
            unknown_state(credential, audit, reason)
        finish(False, outcome="NOT_ROTATED", reason=reason, **audit)

    # The store comes first: a failed audit write must not cost us the only copy of the new key.
    try:
        store_secret(service, new_key)
    except Exception as error:
        finish(False, outcome="ROTATED_NOT_STORED", reason=type(error).__name__, **audit)
    finish(True, outcome="ROTATED", **audit)


def main():
    parser = QuietParser(description="Plan or perform a Relay key rotation.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan").add_argument("--service", required=True)
    rotate_parser = commands.add_parser("rotate")
    rotate_parser.add_argument("--service", required=True)
    rotate_parser.add_argument("--ticket", required=True)
    rotate_parser.add_argument("--confirm", required=True)
    args = parser.parse_args()

    # Plan failures are recorded too, because the agent no longer sees the reason.
    context = {"ticket": getattr(args, "ticket", "none"), "service": args.service, "outcome": "NOT_ROTATED"}
    # fullmatch, because $ alone would also accept a trailing newline.
    if not SERVICE_RE.fullmatch(args.service):
        finish(False, reason="invalid_service_name", **context)
    if args.command == "rotate" and not TICKET_RE.fullmatch(args.ticket):
        finish(False, reason="invalid_ticket", **context)
    try:
        # The store wins, so setting RELAY_KEY can't override it once one is connected.
        credential = fetch_secret(args.service) or os.environ.get(CREDENTIAL_ENV)
        if not credential:
            finish(False, reason="no_credential", **context)
        if args.command == "plan":
            plan(credential, args.service)
        rotate(credential, args.service, args.ticket, args.confirm)
    except Exception as error:
        # Only list_keys, the token check and the intent write can raise here: all before the rotate call.
        finish(False, reason=reason_for(error), **context)


if __name__ == "__main__":
    main()
