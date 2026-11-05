#!/usr/bin/env python3
"""Plan and perform a Relay key rotation without showing key values to the caller.

Usage:
  relay_rotate.py plan --service NAME
  relay_rotate.py rotate --service NAME --confirm TOKEN

Exit codes: 0 done, 1 nothing rotated, 2 bad usage, 3 UNKNOWN STATE, 4 rotated but not stored.

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
SERVICE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PRINTABLE_RE = re.compile(r"[A-Za-z0-9_.:+-]{1,64}")
DEFINITE_REJECTIONS = (400, 401, 403, 404, 422)
AUDIT_TEMPLATE = (
    "relay-rotate at={at} service={service} outcome={outcome} old_key_ids={old_key_ids} "
    "new_key_id={new_key_id} new_key_fingerprint={new_key_fingerprint} reason={reason}"
)
AUDIT_FIELDS = ("service", "outcome", "old_key_ids", "new_key_id", "new_key_fingerprint", "reason")


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


def stop(code, *lines):
    print("\n".join(lines))
    sys.exit(code)


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
    keys = call(credential, f"{KEYS_URL}?service={service}")["keys"]
    return [(safe(key["id"]), safe(key.get("created_at", "unknown"))) for key in keys]


def plan(credential, service):
    keys = list_keys(credential, service)
    lines = [f"PLAN: service={service}"]
    lines += [f"CURRENT KEY: id={key_id} created_at={created}" for key_id, created in keys]
    lines.append(f"CONFIRM TOKEN: {confirm_token(credential, service, [k for k, _ in keys])}")
    stop(0, *lines)


def unknown_state(credential, service, old_ids, reason):
    lines = [f"UNKNOWN STATE: service={service} reason={reason}. Do not retry: Relay may have created a key."]
    try:
        for key_id, created in list_keys(credential, service):
            is_new = "yes" if key_id not in old_ids else "no"
            lines.append(f"CURRENT KEY: id={key_id} created_at={created} new_since_call={is_new}")
    except Exception as error:
        lines.append(f"CURRENT KEYS UNAVAILABLE: reason={reason_for(error)}")
    lines.append(audit_summary(service=service, outcome="UNKNOWN_STATE", old_key_ids=old_ids, reason=reason))
    stop(3, *lines)


def rotate(credential, service, token):
    old_ids = [key_id for key_id, _ in list_keys(credential, service)]
    if not hmac.compare_digest(token, confirm_token(credential, service, old_ids)):
        stop(1, f"NOT ROTATED: service={service} reason=confirm_token_invalid. Run plan and confirm again.")

    try:
        response = call(credential, f"{KEYS_URL}/rotate", json.dumps({"service": service}).encode())
        new_key = response["key"]
        if not isinstance(new_key, str) or not new_key:
            raise ValueError("no usable key in response")
        new_id, new_fingerprint = safe(response.get("id", "unknown")), fingerprint(new_key)
    except Exception as error:
        reason = reason_for(error)
        rejected = isinstance(error, urllib.error.HTTPError) and error.code in DEFINITE_REJECTIONS
        if not rejected and not was_refused(error):
            unknown_state(credential, service, old_ids, reason)
        stop(
            1,
            f"NOT ROTATED: service={service} reason={reason}",
            audit_summary(service=service, outcome="NOT_ROTATED", old_key_ids=old_ids, reason=reason),
        )

    audit = {
        "service": service,
        "old_key_ids": old_ids,
        "new_key_id": new_id,
        "new_key_fingerprint": new_fingerprint,
    }
    identity = f"service={service} new_key_id={new_id} fingerprint={new_fingerprint}"
    try:
        store_secret(service, new_key)
    except Exception as error:
        reason = type(error).__name__
        stop(
            4,
            f"ROTATED NOT STORED: {identity} reason={reason}. Escalate now: the new key was not saved.",
            audit_summary(outcome="ROTATED_NOT_STORED", reason=reason, **audit),
        )
    stop(0, f"ROTATED: {identity}", audit_summary(outcome="ROTATED", **audit))


def main():
    parser = argparse.ArgumentParser(description="Plan or perform a Relay key rotation.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan").add_argument("--service", required=True)
    rotate_parser = commands.add_parser("rotate")
    rotate_parser.add_argument("--service", required=True)
    rotate_parser.add_argument("--confirm", required=True)
    args = parser.parse_args()

    # fullmatch, because $ alone would also accept a trailing newline. The name isn't echoed.
    if not SERVICE_RE.fullmatch(args.service):
        stop(1, "NOT ROTATED: reason=invalid_service_name")
    try:
        # The store wins, so setting RELAY_KEY can't override it once one is connected.
        credential = fetch_secret(args.service) or os.environ.get(CREDENTIAL_ENV)
        if not credential:
            stop(1, f"NOT ROTATED: service={args.service} reason=no_credential")
        if args.command == "plan":
            plan(credential, args.service)
        rotate(credential, args.service, args.confirm)
    except Exception as error:
        # Only list_keys and the token check can raise here, and both run before the rotate call.
        stop(1, f"NOT ROTATED: service={args.service} reason={reason_for(error)}")


if __name__ == "__main__":
    main()
