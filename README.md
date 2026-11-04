# README.md

## Tests
Tests on the original can be run with

```python
python3 -m unittest discover -s tests -v # from repo root
python3 -m unittest discover -s tests -v > evidence/original-results.txt 2>&1
```

Tests on the improved can be run with
```python
REDACT_PATH=redact.py python3 -m unittest discover -s tests -v
REDACT_PATH=redact.py python3 -m unittest discover -s tests -v > evidence/improved-results.txt 2>&1
```