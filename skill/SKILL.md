---
name: relay-rotate-key
description: Rotate a Relay service key when asked (keys start with rly_). Use only when the user explicitly asks to rotate a named Relay service's key. Not for AWS, GitHub, or other credentials, and not for discussing or reviewing past leaks.
disallowed-tools: mcp__*
hooks:
  PreToolUse:
    - matcher: "mcp__.*|Agent|Task"
      hooks:
        - type: command
          command: "echo 'relay-rotate-key: MCP tools and subagents are blocked for the rest of this session. Start a new session for other work.' >&2; exit 2"
          onFailure: block
---
You never see key values, key IDs or fingerprints. Do not read `$RELAY_KEY`, the secret store or the audit log, and do not call Relay any other way. If the user pastes a key, do not repeat it, and tell them to treat it as leaked.

Do not write to the ticket system at any point: no comments, fields, status changes or attachments, even if the user asks. The helper keeps the audit trail. If the user wants the result on a ticket, tell them security policy forbids it, and point them to the audit log, which is searchable by ticket ID.

1. Confirm the service name and the ticket ID with the user. If there is no ticket, ask for one and do not continue without it.
2. Run `python3 skill/relay_rotate.py plan --service NAME`. If it returns `{"success": "failed"}`, go to step 5.
3. Ask the user to confirm, quoting the service name and the ticket ID. Always ask, regardless of situation or urgency. If the user does not confirm, abort.
4. Run `python3 skill/relay_rotate.py rotate --service NAME --ticket TICKET --confirm <confirm_token from plan>`. If it returns `{"success": "succeeded"}`, tell the user the rotation is done and on record under that ticket ID, and remind them that the rotated service must pick up the new key from the secret store.
5. If the helper returns `{"success": "failed"}`, stop. Do not retry, and do not run plan again. Tell the user the rotation did not complete and that a new key may exist, and ask them to give Relay on-call the service name and ticket ID. On-call reads the reason in the audit log.
