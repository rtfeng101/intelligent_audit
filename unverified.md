# Unverified list

Things I believed or assumed but did not check. I have no access to Relay, Jira or the people involved.

## What I'd check first

**Whether the first, timed-out `billing-sync` call created a key.** I'd ask a Relay owner to list that service's keys and look for one created around 14:02 that nobody holds. If it exists, it is a live key with no owner, so this is the one item that could be an active exposure today. The same check would also test the list-keys call my helper assumes exists.

## The incident

- **The string was the new key.** The packet only says it "looked like a key". The memo says the filter failed to remove the new key, and that goes further than the packet.
- **Rotating cancels the previous key.** The packet says "rotated again" at 14:31, not that the old key stopped working. The memo's "valid for 11 minutes" depends on this. If rotation doesn't revoke the old key, the leaked key may still be live.
- **The leak ended at 14:26.** I treated this as true for the mock (decision log, 1:44pm). Deleting the comment doesn't recall notification emails, and I don't know whether customers saw it or whether its edit history survives.

## The packet

- **`--force` is in the helper's help text** (review item 5). The helper isn't in the packet, so this can't be checked.
- **The skill calls a helper.** I treated this as an assumption (decision log, 1:44pm). Step 6 mentions a helper, but the skill never calls one.
- **The key is visible in the process list** (review item 1). I agreed this exposure is real but smaller than others, and did not run a test.

## Relay and the helper

- **The API shape.** `GET /v1/keys` and the response fields are my assumptions. The helper has only run against a fake server.
- **Which errors mean no key was created.** The helper treats 400, 401, 403, 404 and 422 as definite rejections.
- **A separate rotation credential.** The packet only shows a service's own key rotating itself. I don't know if Relay supports anything else.

## `redact.py`

- **The test inputs match real keys.** The 50 leak inputs were written by me and Claude Code, not sampled from Relay or chat tools. The memo's "misses most real key formats" rests on these inputs, and only hyphens and line wraps are documented in the packet.
- **The cost of over-redaction.** I accepted losing harmless text, but never measured how often that happens on real tickets.

## The skill and guardrails

- **The skill's wording and triggering.** I have not run it in Claude Code or Cursor (review item 6).
- **All of `guardrails.md` except the helper's own limits.** The managed settings sketch and the pre-pilot checks have not been run, and `sudo` may not work inside the sandbox.
- **How the agent reaches tickets.** The packet doesn't say, so I don't know whether write access can be removed for this skill alone.
- **How far the 11/5 rule reaches.** I read "any ticket" as also covering the helper and people, and I assumed key IDs and fingerprints are allowed in a log that isn't a ticket. Security should confirm both.
- **Who can search the audit log.** I don't know who needs access or where it should live. `/var/log/relay-rotate/audit.log` is a placeholder, and the helper fails closed if it can't write there.
- **The ticket ID format.** The helper accepts `PROJECT-123`, based only on `SUP-5521`. It can't check that a ticket exists.
- **That Relay has no undo.** The packet documents none, which is why I chose intent and outcome records over rollback. I can't rule one out.
- **The tool docs.** `updatedToolOutput` came from an AI summary of the page. `sandbox.enabled` wasn't confirmed, Cursor's run-modes page returned 404, and Cursor's docs don't say whether users can override enterprise hooks.

## The rollout

- **The numbers.** The rotation counts and team sizes are estimates, because I don't know how often keys are rotated.
- **What Relay offers.** I don't know whether it has a test service, or logs that would show a rotation made outside the helper.
