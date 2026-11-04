# Decision log
1:35pm: Set up repo with files as is
1:44pm: Read incident package for challenges
- Plan to treat as a fact or assumption:
    - Skill calls helper
    - Leak closed at 14:26 regardless of notifications for the sake of mock
1:58pm: Use Claude Code to generate extensive tests against `original/redact.py` to see which tests it fails
- I believe that AI is very good at creating extensive tests and certainly more than I can think of in a few minutes, so I rely on this output
- I will review the full list of test cases
2:25pm: Reviewed generated test codes
- Added two test: URL encoding, base64 encoding
2:31pm: Begin writing improved redact
- Use Claude Code to get started