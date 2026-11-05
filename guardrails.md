# Guardrail design: relay-rotate-key (draft)

**Status:** Only the helper's own limits (`tests/test_relay_rotate.py`) and the skill's tool block (`evidence/tool-gate/results.md`) are built and tested. Everything else here is a design that has not been run.

## The design in brief

The agent should be unable to reach a Relay key, not merely told not to. If a key is in the agent's context, it can end up in transcripts, logs and tickets, and redaction has to catch every form it takes. That is how SUP-5521 happened.

The skill therefore holds the workflow and contains no secrets. The helper holds the keys and runs under an identity the agent does not have. Hooks and prompts sit on top as a second layer, because they match command text and can be worked around.

- **Target:** the helper runs in a small internal service. Credentials never reach the laptop, and that service enforces who may rotate which key.
- **Interim for the pilot:** the helper runs locally as a separate `relay-rotator` OS user.

## What the agent must never hold

- The credential used to call Relay
- The new key, or any other value in the secret store
- Raw Relay requests and responses
- Key IDs, fingerprints and the audit log (changed 11/5, see `change-note.md`: the agent was allowed to see the first two)

The agent may see service names, ticket IDs, the confirm token and `succeeded` or `failed`.

## Enforced outside the skill

| The agent cannot... | Enforced by | Status |
|---|---|---|
| Read the credential from its environment | `RELAY_KEY` is never set in agent shells, and the helper reads only from the store. `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` is a backstop. | Not built. `fetch_secret()` is a stub, and the `RELAY_KEY` fallback must be removed before rollout. |
| Read the secret store | The store is off the host, or owned by `relay-rotator` with mode 600. | Not built. `store_secret()` is a stub. |
| Change the helper | The deployed copy is owned by root and not writable by the agent. | Not built |
| Run anything else as the rotator | A sudoers rule allows only the helper's exact path, and `sudo` resets the environment. Set `timestamp_timeout=0`, or a cached `sudo` session gives the agent root. | Not built |
| Call Relay directly | The sandbox has no network route to Relay. Ideally Relay also accepts rotation only from the rotator identity. | Not built. Relay support is unknown. |
| See a key, key ID or fingerprint in helper output | The helper prints only fixed JSON and never echoes its arguments, including on errors. | **Built and tested** |
| Rotate without an audit trail | The helper records an intent before the Relay call and stops if it can't. If the outcome can't be recorded, it returns `failed`. | **Built and tested** |
| Read or edit the audit log | Pilot: the log is owned by `relay-rotator` with mode 600. Target: an append-only store off the host. | Not built. The helper creates the file with mode 600, which stops nobody until it runs as a separate user. |
| Force a rotation or retry an ambiguous failure | There is no `--force`. The helper makes one attempt, and retries only when the connection is refused. | **Built and tested** |
| Rotate from a stale plan | The confirm token is tied to the service and its current keys. | **Built and tested** |
| Rotate without a human approving | Pilot: an `ask` rule and a `PreToolUse` hook on `rotate`. Target: the service requires approval outside the agent session. | Not built |
| Write to the ticket system | Target: the agent has no ticket credential. Now: the skill's `disallowed-tools` removes MCP tools on the turn it is invoked, and its `PreToolUse` hook blocks MCP tools and subagents for the rest of the session. The helper has no ticket code. This replaces my earlier design, where the helper or the agent posted an `AUDIT:` line, which the 11/5 rule forbids. | **Partly built and tested** on Claude Code against a fake server. Bash, resumed sessions and Cursor get past it. The credential is not removed, because the packet doesn't say how the agent reaches tickets. |
| Turn these controls off | Managed settings, which user and project settings cannot override. | Not built |

**Sketch of Claude Code managed settings (not run):**

```json
{
  "allowManagedHooksOnly": true,
  "allowManagedPermissionRulesOnly": true,
  "permissions": {
    "disableBypassPermissionsMode": "disable",
    "ask": ["Bash(sudo -n -u relay-rotator /usr/bin/python3 /opt/relay/relay_rotate.py rotate *)"]
  },
  "env": { "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1" },
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "excludedCommands": ["sudo -n -u relay-rotator /usr/bin/python3 /opt/relay/relay_rotate.py *"]
  }
}
```

**Why the OS layer is required:**

- Claude Code's Read deny rules do not cover "a Python or Node script that opens files itself".
- Its Bash rules are not "a security boundary around the program": `sh -c 'curl ...'` gets past `Bash(curl *)`.
- Its sandbox is off by default, covers shell commands only, allows most reads by default, and inherits secrets in the environment. It helps, but only with the settings above and with no key in the environment.
- Cursor's `.cursorignore` "cannot block" terminal access.

### Claude Code and Cursor

The OS and service controls work the same in both. Only the top layer differs:

| Need | Claude Code | Cursor |
|---|---|---|
| Block or prompt before a command | `PreToolUse`, with `permissionDecision` | `beforeShellExecution` and `beforeReadFile`, with `permission` |
| Block a tool for one skill | `disallowed-tools` clears on the next message, so it needs a skill `hooks` entry too (tested) | No tool field on skills. `beforeMCPExecution` can deny MCP calls, but not per skill (not run) |
| Block if the hook fails | `"onFailure": "block"` | `failClosed: true` |
| Central enforcement | `managed-settings.json` | Enterprise `hooks.json`. The docs do not state outright that users cannot override it. |
| Clean output before the model sees it | `PostToolUse` with `updatedToolOutput` | None found: `afterShellExecution` is described only for auditing |
| OS-level sandbox | Yes, as limited above | Exists, but its details could not be checked because the page returned 404 |

Cursor's sandbox and allowlist are therefore not relied on here.

### Detection, not prevention

Run `redact.py` over tool output, the audit log and ticket comments, and treat any match as an incident. It cannot be a boundary: it still fails the URL-encoded and base64 tests (`evidence/improved-results.txt`), and a filter that ran is not proof that a comment is clean.

## Stays advisory, in the skill

These depend on judgement or are not worth enforcing:

- When to use the skill, and checking the service name with the user
- Always asking for confirmation. The instruction shapes the conversation, and the approval control above enforces it.
- The written ban on ticket writes. It tells the agent what to say when asked to post, and it covers ticket routes the tool block misses, such as Bash.
- Not repeating a key the user pastes
- Not retrying after `failed`, and sending the user to on-call with the ticket ID. The helper does not refuse a second rotation while an intent has no outcome.
- Reminding the user that the service must pick up the new key
- "Do not read `$RELAY_KEY`". This tells the agent what to expect, and should be unnecessary once the controls above exist.

## What this still cannot catch

1. **An administrator on the same machine.** Local admins can read a local store or edit managed settings, and an agent running with cached `sudo` can too. Only the service-based target closes this.
2. **A person approving the wrong thing.** Approval fatigue, "it's urgent" pressure, or instructions planted in a ticket can all lead to a real approval of a harmful rotation. Rotating a healthy service can still cause an outage, even with no secret exposed.
3. **Keys that are already outside the store.** A key pasted into chat is already in the transcript. Keys in `.env` files, shell history or a service's own config stay readable unless they are also denied.
4. **Key formats the filters don't recognise.** The helper withholds values that look like `rly_` keys, but a bare 24-character key returned in an ID field would still reach the audit log. Encoded forms get past `redact.py`.
5. **Orphaned keys.** A timed-out call may finish after the helper lists keys. If the key being rotated is also the credential, listing can fail with a 401. The helper records `UNKNOWN_STATE`, but it cannot prove what happened.
6. **Earlier leaks.** None of this recalls notification emails, or anything else already sent from SUP-5521.
7. **Tools outside the setup.** Other agents or a plain terminal skip the hooks and prompts. Only the OS and service controls still apply.
8. **A wrong ticket ID.** The helper checks the format but cannot read tickets, so a well-formed wrong ID files the record where nobody will look. The service name and time still find it.
9. **A gap in the audit trail.** The helper reports on itself, so a rotation made outside it leaves no record. If the outcome write fails, only the intent remains. Comparing the log with Relay's key list is the only independent check.
10. **People.** A user can still paste a result into a ticket by hand. This design only stops the agent.
11. **Ticket writes that skip the skill's block.** A ticket CLI or `curl` through Bash, a session resumed in a new process (tested: the write went through), a session where the skill was never invoked, a ticket tool that isn't MCP, or hooks being turned off. Only removing the ticket credential closes these.

## Checks before the pilot

Run these as the agent, on a pilot machine. None have been run yet. Every one must fail or prompt:

| Attempt | Expected result |
|---|---|
| `printenv RELAY_KEY` | Empty |
| `cat` the store, then the same through `python3 -c "open(...)"` | Permission denied |
| `sudo -n cat` the store, including straight after a human used `sudo` | Refused |
| `cat` the audit log, then edit it | Permission denied |
| Add a comment to a test ticket with the ticket tool, with `curl` or a ticket CLI, and after resuming the session | Refused |
| Edit the deployed helper | Permission denied |
| `curl` Relay directly | No route |
| Run `rotate` through `sh -c`, or with the helper's path written differently | Refused by sudoers, or prompts |
| Run `rotate` through the exact deployed command | Prompts a human |
| Start with `--dangerously-skip-permissions` | Rejected |

## Open questions

- **The skill's hook and `allowManagedHooksOnly`:** the sketch above sets this, and the docs say it blocks hooks other than managed ones and those from force-enabled plugins. I expect the skill's hook not to run under it, so the skill would need to ship in a force-enabled plugin. Not tested.
- **Sandbox and `sudo`:** `sudo` may not work inside the sandbox, so the sketch excludes the helper from it. The exclusion matches command text and needs testing. If it proves weak, go straight to the service.
- **A dedicated rotation credential:** the packet only shows the service's own key being used to rotate itself. A separate credential would fix item 5's 401 and stop a leaked key from rotating itself, if Relay supports one.
- **Skill path:** the skill calls `python3 skill/relay_rotate.py` for the mock. Before rollout it must call the deployed command, or the rules above will not match it.

## Sources

Claude Code and Cursor docs, read 2026-11-04 by an AI agent on my behalf. Check these before relying on them:

- `updatedToolOutput` came from a model-generated summary of a long page, not its verbatim text.
- `sandbox.enabled` was not confirmed in the pages read.
- Cursor's run-modes page returned 404.
- [Claude Code permissions](https://code.claude.com/docs/en/permissions), [hooks](https://code.claude.com/docs/en/hooks), [sandboxing](https://code.claude.com/docs/en/sandboxing), [managed settings](https://code.claude.com/docs/en/managed-settings), [environment variables](https://code.claude.com/docs/en/env-vars)
- [Cursor hooks](https://cursor.com/docs/agent/hooks), [terminal](https://cursor.com/docs/agent/terminal), [ignore files](https://cursor.com/docs/context/ignore-files)
- Read 2026-11-05: [Claude Code skills](https://code.claude.com/docs/en/skills), [settings reference](https://code.claude.com/docs/en/settings-reference), [Cursor skills](https://cursor.com/docs/context/skills)
