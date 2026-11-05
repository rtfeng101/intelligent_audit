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
2:55pm: Decided against using a randomness checker
- Changed mind on trying to create a perfect redactor since time constraints
- Accept that over-redaction is better than leaking a key
- Also I don't want to use something like entropy calculation for a mock
3:14pm: Added space into the pattern and added split line detection
- Now the redaction can redact across paragraphs if an 'rly' is detected. 
    - Still trading off over redaction over leaking key
- Improved `redact.py` looks a bit messy but good enough spot to move on
3:21pm: Write 6 review items for deliverable
3:41pm: Write the correct skill and helper
- Use Claude to help create an example
4:01pm: Use Claude to draft a relay_rotate.py helper for the SKILL to use
- Running low on time so use it as a demo
4:31pm: Decision memo
4:42pm: Use Claude to generate a rollout plan according to the memo as well as unverified list based on the decision log. 
- Time constraints, using AI to help speed up the process
4:48pm: Review deliverables and plan screen recording