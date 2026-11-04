import re
PATTERNS = [
    re.compile(r"rly_[A-Za-z0-9]{24}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
]

def redact(text):
    for p in PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text