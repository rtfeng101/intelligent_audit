# Change note: no rotation data on tickets

**Decision:** unchanged. Block v0.3, and pilot v0.4 only once the gaps in `memo.md` close. The audit design changed: the safest way to keep rotation data off tickets is for the agent never to have it.

**What changed:** the helper now writes the audit trail to its own log, found by ticket ID, and the agent only learns `succeeded` or `failed`. The helper records an intent before calling Relay and an outcome after. I chose this over rollback because Relay has no documented undo. No intent means no rotation. If the outcome can't be written, the result is `failed`, and the intent shows on-call that a key may exist. The skill also blocks MCP tools and subagents, on top of its written ban on ticket writes.

**What no longer holds:**

- The internal-only audit comment, and my target of the helper posting it.
- The agent seeing key IDs and fingerprints, and approvals quoting key IDs.
- `UNKNOWN STATE`, `ROTATED NOT STORED` and exit codes 3 and 4 as agent outputs. They survive only as log outcomes.
- `redact.py` as a guard on audit comments, as there are none now. Its results still stand as evidence against v0.3.

**What I gave up:**

- **Ticket visibility:** tracing a ticket now needs log access, and the helper can't verify ticket IDs.
- **Triage:** the agent can't tell a stale token from an orphaned key, so every failure goes to on-call.
- **Informed approval:** approvers no longer see which keys are affected.
- **Flexibility:** a ticket ID is required even when urgent, and a session that runs this skill loses MCP tools and subagents until it ends.
- **Independent proof:** the helper reports on itself. Only comparing the log with Relay's key list reveals a rotation made outside it.
