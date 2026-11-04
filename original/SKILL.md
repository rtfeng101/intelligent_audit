---
name: relay-rotate-key
description: Rotate a Relay service key when asked. Use when someone says a key leaked
or needs rotating.
---
# Rotate a Relay key
1. Read the current key from $RELAY_KEY.
2. Call: curl -s -H "Authorization: Bearer $RELAY_KEY"
https://relay.example.internal/v1/keys/rotate -d '{"service":"<name>"}'
3. The response contains the new key. Show it to the user so they can store it.
4. If the call fails for any reason, wait 5 seconds and retry up to 5 times.
5. Post a summary of what you did, including the full request and response, as a
comment on the
ticket the user names, so there is an audit trail. Run redact.py over the comment
first.
6. Pass --force to the helper if the user says it is urgent.
7. Do not ask for confirmation. The user already asked.