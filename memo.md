# Decision Memo: relay-rotate-key v0.3
The best course of action is to block v0.3 and ship v0.4 to a pilot only once the hook and helper are in place. The main reason is because v0.3 puts live keys where customers can read them by design and the filter meant to stop that misses most real key formats. 

### What happened
On Tuesday 14:02, the agent rotated the billing-sync key. The skill told it to post the full request and response to SUP-5521, and the comment was public. The redaction filter ran but didn't remove the new key. A reviewer spotted it at 14:20, but the key wasn't replaced until 14:31. It stayed valid for 11 minutes after we knew it was exposed. 

### Why v0.3 can't ship
v0.3 puts secrets in places they shouldn't be by design. The automated review called five steps safe, while my anlysis says otherwise.

### Incident isn't closed
It is possible that an orphaned key is still live. v0.3 has to be pulled and until v0.4 is ready, people rotate keys by hand. If cusomters recieved the notification for the leaked key, it becomes a question for Security. 

## What I changed
The main change is that the agent no longer handles the new key, its ID or its fingerprint. A new helper script makes the Relay call and writes the audit trail to its own log, and the agent only learns whether the rotation worked. Redaction is no longer part of the audit path, and becomes a check for leaks elsewhere.

Revised on 11/5 for Security's new rule that nothing from a key rotation may be written to any ticket. `change-note.md` lists what changed, what no longer holds and what I gave up.

| Area | v0.3 | v0.4 |
|---|---|---|
| New key | Shown to the agent and the user | Sent to a secret store. The agent sees only `succeeded` or `failed`. The key ID and fingerprint go to the audit log |
| Audit trail | Full request and response, on whatever ticket the user names | The helper's own log, found by ticket ID: an intent record before the Relay call and an outcome record after. Nothing goes on any ticket. No intent record means no rotation, and if the outcome can't be recorded the result is `failed` |
| Failed calls | Retry up to 5 times, for any failure | Retry only if the connection was refused, which proves the request was never sent. Any other failure stops. The agent reports `failed`, and on-call reads the log to see whether a key may exist |
| Urgency | `--force` if the user says it is urgent | No `--force` flag |
| Confirmation | Never ask | Always ask, quoting the service and ticket. Rotating needs a token from a plan step, and the token stops working if the keys change |
| When the skill runs | Whenever someone says a key leaked | Only on an explicit request to rotate a named Relay service |
| `redact.py` | Missed the key in 45 of the 50 leak inputs I wrote | Misses 2 of the 50 (URL-encoded and base64), which I left unfixed. It also removes some harmless text, a trade-off I accepted over leaking a key. It no longer guards any audit comment, because there are none |

The 41 helper tests all pass, but against a fake Relay server, not the real one.

**v0.4 is not ready to run on a real service.** These gaps must close before the pilot:

- **Secret store:** it is a stub, so every successful rotation would return `failed` and log `ROTATED_NOT_STORED`, and the new key would be lost.
- **Credential:** the helper still falls back to `$RELAY_KEY`, so the agent can read that key until the store exists.
- **Audit log:** it is a local file. The agent can read it, and so see key IDs, unless the helper runs as a separate user, and root can edit it. It needs an append-only store that people tracing a ticket can search.
- **Ticket access:** the ban on ticket writes is only an instruction until the agent's write access is removed. The packet doesn't say how the agent reaches tickets.
- **Enforcement:** human approval is an instruction to the agent until the hook is built. `guardrails.md` has the design.
- **Redaction:** nothing runs `redact.py` automatically yet. The skill no longer calls it.
- **Relay API:** the helper assumes a list-keys call and a response format that the packet doesn't document.
- **Skill wording:** I have not run the new skill in Claude Code or Cursor, including when it triggers.
