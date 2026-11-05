# Rollout plan: relay-rotate-key v0.4

**Status:** a proposal. None of it has been run. The team sizes and rotation counts are my estimates, because the packet doesn't say how often keys are rotated.

## Now, before any rollout

- Pull v0.3 from wherever the skill is shared.
- Engineers rotate keys by hand, using a short written procedure: never retry after a timeout, and never put a key in a ticket.
- Finish the incident: check `billing-sync` for an orphaned key, and ask Security to review the customer exposure.

## Before the pilot starts

Every gap listed in `memo.md` must be closed, and every check in `guardrails.md` ("Checks before the pilot") must pass when run as the agent on a pilot machine.

## Who gets it, in order

| Stage | Who | What | Move on when |
|---|---|---|---|
| 1. Dry run | 2 Relay on-call engineers | A test service with a key nobody depends on, including a forced timeout | Every outcome behaves as `skill/SKILL.md` describes |
| 2. Pilot | The same 2, plus 3 more from the Relay team | Real, low-risk services, one at a time, with a second person watching | 10 real rotations with no stop condition |
| 3. Wider | The teams that rotate keys most often | Their own services | 30 more rotations with no stop condition |
| 4. Everyone | All engineers | Hand rotation is retired as the default | |

The Relay team goes first because they run Relay and can recover from a bad rotation themselves. `billing-sync` and other billing services wait until stage 3.

The pilot is Claude Code only. Cursor users keep rotating by hand until its gaps are closed: `guardrails.md` found no way to clean output before the model sees it, and could not check its sandbox.

## How I'd know it's working

- No key-shaped strings in ticket comments, transcripts or tool output, based on running `redact.py` over all three.
- Every new key in Relay's key list matches an `AUDIT:` line and a key in the secret store.
- Every rotation has a recorded human approval.
- Every `UNKNOWN STATE` or `ROTATED NOT STORED` led to a page, not a retry.
- The rotated service works on the new key.

## What I'd watch for

- Agents trying to read the store, call Relay directly or get around the hook.
- Audit comments that are public, or that contain anything beyond the `AUDIT:` line.
- Engineers going back to raw `curl`, which suggests the skill is getting in the way.
- The skill firing on discussions of past leaks, or not firing when asked.
- Approvals given within seconds, which suggests people have stopped reading them.
- Outages after a rotation, even when no secret was exposed.

## Stop conditions and rollback

Any one of these stops the rollout at once:

- A key appears anywhere it shouldn't.
- A rotation happens without approval.
- A new key has no matching audit line.
- A control from `guardrails.md` is found switched off.

To roll back:

1. Remove the sudoers rule. This disables the helper even if someone still has a copy of the skill.
2. Remove the skill from the shared location.
3. Return to rotating by hand. **Never roll back to v0.3.**
4. Treat any exposed key as leaked: rotate it by hand and check the key list for orphans.
5. Rollback doesn't undo finished rotations. Those keys stay in the store and stay valid.

Restart from stage 1 once the cause is found and has a test.
