# Personal Notes
## Packet Truths/Incident Review
- "Our redaction filter ran, so we believed the comment was clean"
    - Running a filter is not proof it worked
- Review item 4: "Jira comments are access controlled"
    - "Customers with portal access can see public comments on it. The comment was public."
    - Contradiction in the incident notice 
- Review item 5: "--force is documented in the helper's help text"
    - Packet's helper is `redact.py` and has no `--force`
    - Skill never calls a helper either and step 2 uses a raw curl, so claim can't be checked
- "Deleted at 14:26" implies the leak is closed
    - Doesn't recall notification emails, etc.
- "Rotated again at 14:31" implies we're clean
    - unknown whether timed-out first call created a key
    - if so, then the key may still be live and nobody has it
- Step 1 sends $RELAY_KEY as the Bearer token for the rotate call
    - Key being rotated is also what authorizes rotation
    - Flag as design decision