# Video Recording:
https://www.loom.com/share/24e0fbf660fd441da6cccef728885b2a

# The Rotation Skill: take-home submission

**Decision:** block `relay-rotate-key` v0.3, and ship v0.4 to a pilot only once the hook and helper are in place. The reasoning is in [memo.md](memo.md). v0.4 is not ready to run on a real service yet; the memo lists what must close first.

## Where each deliverable is

| # | Deliverable | Location |
|---|---|---|
| 1 | Decision memo | [memo.md](memo.md) |
| 1 | Requirement change note (no rotation data on tickets) | [change-note.md](change-note.md) |
| 2 | Corrected skill and replacement helper | [skill/SKILL.md](skill/SKILL.md), [skill/relay_rotate.py](skill/relay_rotate.py) |
| 2 | Improved redactor | [redact.py](redact.py) |
| 3 | Evidence: test file | [tests/test_redact.py](tests/test_redact.py) (helper tests: [tests/test_relay_rotate.py](tests/test_relay_rotate.py)) |
| 3 | Evidence: inputs | [tests/inputs/](tests/inputs/) |
| 3 | Evidence: results | [evidence/original-results.txt](evidence/original-results.txt), [evidence/improved-results.txt](evidence/improved-results.txt) |
| 3 | Evidence: the six review items | [evidence/review-items.md](evidence/review-items.md) |
| 4 | Guardrail design | [guardrails.md](guardrails.md) |
| 5 | Rollout plan | [rollout.md](rollout.md) |
| 6 | Unverified list | [unverified.md](unverified.md) |
| 7 | AI-use note and transcript links | [ai-use/NOTE.md](ai-use/NOTE.md) |
| 8 | Decision log | [decision-log.md](decision-log.md) |
| 9 | Screen recording | TODO: add link before submitting |

**What I'd do next with more time:** the first check is at the top of [unverified.md](unverified.md), and the gaps to close before a pilot are at the end of [memo.md](memo.md).

Also in the repo: [original/](original/) holds the packet's skill and `redact.py` as received, [personal-notes.md](personal-notes.md) holds my working notes, and the PDF is the packet itself.

## Run the tests

These need Python 3 and nothing else. Run them from the repo root.

**Against the original `redact.py` (the default):**

```bash
python3 -m unittest discover -s tests
```

**Against the improved `redact.py`:**

```bash
REDACT_PATH=redact.py python3 -m unittest discover -s tests
```

Add `-v` to either command to see each test by name.

### Expected results

Both commands run 109 tests and exit non-zero, because both have failures:

| Target | Redactor tests (68) | Helper tests (41) |
|---|---|---|
| `original/redact.py` | 50 fail | all pass |
| `redact.py` | 2 fail | all pass |

- **The 50 failures on the original:** 45 of the 50 leak inputs, all 4 `over_redacted` inputs, and the safe input `words_ending_in_rly`.
- **The 2 failures on the improved version:** `test_leak_base64_encoded` and `test_leak_url_encoded`. I left these unfixed on purpose and kept the tests so the gap stays visible. See [ai-use/NOTE.md](ai-use/NOTE.md).
- **`over_redacted`:** these tests pin harmless text the improved redactor removes. It is a trade-off I accepted over leaking a key, and the original fails them because it does not redact that text.

`REDACT_PATH` only affects the redactor tests. The helper tests run against a fake local Relay server, so no network access or credentials are needed.

### Test your own inputs

Each file in `tests/inputs/` becomes its own test, so you can drop in a file and rerun the commands above:

| Folder | The test passes when |
|---|---|
| `tests/inputs/leak/` | No fragment of the key (4 or more characters) survives. The file must contain a recognisable `rly_` key, or the test fails. |
| `tests/inputs/safe/` | The output is byte-for-byte the same as the input. |
| `tests/inputs/over_redacted/` | The output contains `[REDACTED]`. |

To run the redactor on a single file and see its output:

```bash
python3 -c 'import sys; from redact import redact; sys.stdout.write(redact(sys.stdin.read()))' < tests/inputs/leak/wrap_mid_key_lf.txt
```

For the original, use `from original.redact import redact`.

### Regenerate the saved results

The saved results cover the 68 redactor tests only, because they were captured before the helper tests existed. These commands overwrite them:

```bash
python3 -m unittest discover -s tests -p 'test_redact.py' -v > evidence/original-results.txt 2>&1
REDACT_PATH=redact.py python3 -m unittest discover -s tests -p 'test_redact.py' -v > evidence/improved-results.txt 2>&1
```

## Run the helper

The helper is not usable end to end outside its tests. It targets the packet's `relay.example.internal`, which is a fixed address, and the secret store is a stub. **Don't run `rotate` against a real Relay:** the new key can't be saved, so a successful rotation would lose it.

```bash
python3 skill/relay_rotate.py plan --service NAME
python3 skill/relay_rotate.py rotate --service NAME --ticket TICKET --confirm TOKEN
```

With `RELAY_KEY` unset, both stop safely before any network call and print `{"success": "failed"}`.

| Output | Exit code | Meaning |
|---|---|---|
| `{"success": "succeeded"}` | 0 | Done, and on record. `plan` also returns `confirm_token` |
| `{"success": "failed"}` | 1 | Not done. Do not retry, because a key may exist. The reason is in the audit log |

The helper never writes to a ticket. It appends to `/var/log/relay-rotate/audit.log`, a placeholder path it won't create. If it can't write there, `rotate` stops before calling Relay. To trace a ticket:

```bash
grep 'ticket=SUP-5521 ' /var/log/relay-rotate/audit.log
```

An `INTENT` record with no outcome after it means a key may exist, so check Relay. The outcomes are `ROTATED`, `NOT_ROTATED`, `UNKNOWN_STATE` and `ROTATED_NOT_STORED`.
