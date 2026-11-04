import re

# ASCII hyphen and underscore, Unicode lookalikes (soft hyphen, U+2010-2015 dashes, minus
# sign, small/fullwidth forms), then zero-width characters. Escaped because most are invisible.
SEP = r"_\-\u00ad\u2010-\u2015\u2212\ufe58\ufe63\uff0d\uff3f\u200b-\u200d\u2060\ufeff"
# Tab, ASCII space and the Unicode spaces, including non-breaking.
SPACE = r" \t\u00a0\u2000-\u200a\u202f\u205f\u3000"
# A line break, real or JSON-escaped.
NEWLINE = r"(?:\r\n?|\n|\\r(?:\\n)?|\\n)"
# One line break with any indent or "> " quote marker around it.
BREAK = rf"[ \t]*{NEWLINE}[ \t>]*"
# What may sit between two key characters. Each input can match only one way, because
# ambiguity here (e.g. a second optional SEP run) backtracks exponentially on bad input.
# shortcut: blank lines aren't gaps, so a key split across one leaks. Upgrade if one turns up.
GAP = rf"[{SEP}]*(?:{BREAK}[{SEP}]*)?"
# GAP plus spaces on the same line. Same one-way-only rule.
SPACED_GAP = rf"[{SEP}{SPACE}]*(?:{NEWLINE}[{SEP}{SPACE}>]*)?"

PATTERNS = [
    # Count the 24 key characters rather than the match length. The lookbehind keeps words
    # like hourly_ out. Only those 24 may wrap: a tail that crossed lines would eat the next line.
    re.compile(
        rf"(?<![A-Za-z0-9])r{GAP}l{GAP}y(?:{BREAK})?[{SEP}]"
        rf"(?:{GAP}[A-Za-z0-9]){{24}}(?:[{SEP}]*[A-Za-z0-9])*"
    ),
    # Space-split keys. Runs after the pattern above so prose before an intact key survives, and
    # before Bearer, which would otherwise redact the first chunk and leave the rest exposed.
    # Accepted trade-off: prose after an rly_ name is redacted too, since it looks the same.
    # See tests/inputs/over_redacted.
    re.compile(
        rf"(?<![A-Za-z0-9])r{SPACED_GAP}l{SPACED_GAP}y(?:{BREAK}|[{SPACE}]*)[{SEP}]"
        rf"(?:{SPACED_GAP}[A-Za-z0-9]){{24}}(?:[{SEP}]*[A-Za-z0-9])*"
    ),
    # shortcut: same line only, because a gap here matches "Bearer scheme.\nAuthorization".
    # Wrapped rly_ keys are caught above. Upgrade if other token formats appear.
    re.compile(rf"Bearer\s+[A-Za-z0-9.{SEP}]{{20,}}"),
]
def redact(text):

    for p in PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text
