---
name: relay-rotate-key
description: Rotate a Relay service key when asked (keys start with rly_). Use only when the user explicitly asks to rotate a named Relay service's key. Not for AWS, GitHub, or other credentials, and not for discussing or reviewing past leaks.
---
You never see key values. Do not read `$RELAY_KEY` or the secret store, and do not call Relay any other way. If the user pastes a key, do not repeat it, and tell them to treat it as leaked.

1. Confirm the service name with the user. Run `python3 skill/relay_rotate.py plan --service NAME` and show its output (current key IDs, when each was created, and the confirm token) to the user. If it reports NOT ROTATED, report the reason and stop.
2. Ask the user to confirm, quoting the service name and the current key IDs. Always ask, regardless of situation or urgency. If the user does not confirm, abort.
3. Run `python3 skill/relay_rotate.py rotate --service NAME --confirm <token from plan>`. The helper stores the new key in a secret store; you will only see its ID and a short fingerprint. If it reports ROTATED, give the user both.
4. If the helper reports anything else:
   - UNKNOWN STATE: stop. Do not retry. Tell the user a key may have been created. Page Relay on-call if any key shows `new_since_call=yes` or the output says CURRENT KEYS UNAVAILABLE.
   - NOT ROTATED with `reason=confirm_token_invalid`: the keys changed or the token was wrong. Go back to step 1 and ask the user to confirm again.
   - NOT ROTATED with any other reason: report the reason and stop.
   - ROTATED NOT STORED: tell the user the new key was not saved, and escalate to Relay on-call now.
5. If the helper prints an `AUDIT:` line and the user names a ticket, post only that line, unchanged, as an internal comment. Never add the request, the response, or your own summary. If you cannot confirm the comment will be internal, do not post it, and give the line to the user instead.
6. After ROTATED, remind the user that the rotated service must pick up the new key from the secret store.
