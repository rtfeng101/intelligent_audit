"""Run: python3 -m unittest discover -s tests -v

Tests original/redact.py by default. Set REDACT_PATH to test another file.
Every file in tests/inputs/leak and tests/inputs/safe becomes its own test.
"""
import importlib.util
import os
import re
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
target = os.environ.get("REDACT_PATH", TESTS.parent / "original" / "redact.py")
spec = importlib.util.spec_from_file_location("redact_under_test", target)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
redact = module.redact

NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
SEP = NON_ALNUM.pattern.replace("+", "*")
# Finds the key in an input file. Looser than a redactor should be: any noise may
# split any character. Only ever applied to leak inputs, never to redact()'s output.
KEY = re.compile(rf"(?<![A-Za-z0-9])r{SEP}l{SEP}y{SEP}((?:[A-Za-z0-9]{SEP}){{24}})", re.I)
# Shortest hyphen group a key is split into, so a surviving group counts as a leak.
FRAGMENT = 4


def read(path):
    # Bytes, because text mode would hide CRLF changes from the safe tests.
    return path.read_bytes().decode("utf-8")


def inputs(kind):
    return sorted((TESTS / "inputs" / kind).glob("[!.]*"))


class RedactTests(unittest.TestCase):
    def test_inputs_present(self):
        # Without this, an empty or moved folder would generate no tests and pass.
        self.assertTrue(inputs("leak"))
        self.assertTrue(inputs("safe"))


def leak_test(path):
    def test(self):
        text = read(path)
        keys = [NON_ALNUM.sub("", m.group(1)) for m in KEY.finditer(text)]
        self.assertTrue(keys, "input contains no recognisable key, so it proves nothing")
        output = redact(text)
        squashed = NON_ALNUM.sub("", output)
        survived = [
            key[i:i + FRAGMENT]
            for key in keys
            for i in range(len(key) - FRAGMENT + 1)
            if key[i:i + FRAGMENT] in squashed
        ]
        self.assertFalse(survived, f"key fragments survived in output:\n{output}")
    return test


def safe_test(path):
    def test(self):
        text = read(path)
        self.assertEqual(redact(text), text)
    return test


for path in inputs("leak"):
    setattr(RedactTests, f"test_leak_{path.stem}", leak_test(path))
for path in inputs("safe"):
    setattr(RedactTests, f"test_safe_{path.stem}", safe_test(path))

if __name__ == "__main__":
    unittest.main()
