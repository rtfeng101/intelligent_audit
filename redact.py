import re

# ASCII hyphen and underscore, Unicode lookalikes (soft hyphen, U+2010-2015 dashes, minus
# sign, small/fullwidth forms), then zero-width characters. Escaped because most are invisible.
SEP = r"_\-\u00ad\u2010-\u2015\u2212\ufe58\ufe63\uff0d\uff3f\u200b-\u200d\u2060\ufeff"
# One line break, real or JSON-escaped, with any indent or "> " quote marker around it.
BREAK = r"[ \t]*(?:\r\n?|\n|\\r(?:\\n)?|\\n)[ \t>]*"
# What may sit between two key characters. Each input can match only one way, because
# ambiguity here (e.g. a second optional SEP run) backtracks exponentially on bad input.
# shortcut: spaces on one line and blank lines aren't gaps, because "rly_config is set in..."
# would match. Upgrade if keys turn up split that way.
GAP = rf"[{SEP}]*(?:{BREAK}[{SEP}]*)?"

PATTERNS = [
    # Count the 24 key characters rather than the match length. The lookbehind keeps words
    # like hourly_ out. Only those 24 may wrap: a tail that crossed lines would eat the next line.
    re.compile(
        rf"(?<![A-Za-z0-9])r{GAP}l{GAP}y(?:{BREAK})?[{SEP}]"
        rf"(?:{GAP}[A-Za-z0-9]){{24}}(?:[{SEP}]*[A-Za-z0-9])*"
    ),
    # shortcut: same line only, because a gap here matches "Bearer scheme.\nAuthorization".
    # Wrapped rly_ keys are caught above. Upgrade if other token formats appear.
    re.compile(rf"Bearer\s+[A-Za-z0-9.{SEP}]{{20,}}"),
]
def redact(text):

    for p in PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text
