"""Breaks skill/relay_rotate.py one way at a time and checks tests/test_relay_rotate.py notices. Run from the repo root."""
import shutil, subprocess, sys, pathlib, tempfile, re, os
root = pathlib.Path.cwd()
src = (root/"skill/relay_rotate.py").read_text()
muts = {
 "outcome write failure still reports success": ("        succeeded = False\n", "        pass\n"),
 "no intent record": ('    write_audit(outcome="INTENT", **audit)\n', ""),
 "argparse echoes bad args": ("parser = QuietParser(", "parser = argparse.ArgumentParser("),
 "output carries a key id": ('{"success": "succeeded" if succeeded else "failed", **extra}', '{"success": "succeeded" if succeeded else "failed", "id": "kid-old", **extra}'),
 "ticket not validated": ('if args.command == "rotate" and not TICKET_RE.fullmatch(args.ticket):', "if False:"),
 "plan shows key ids": ("stop(True, confirm_token=confirm_token(credential, service, list_keys(credential, service)))", "stop(True, confirm_token=confirm_token(credential, service, list_keys(credential, service)) + str(list_keys(credential, service)))"),
 "log world-readable": ("0o600", "0o644"),
 "unknown state logged as not rotated": ("            unknown_state(credential, audit, reason)\n", "            pass\n"),
 "ticket dropped from log": ('audit = {"ticket": ticket, "service"', 'audit = {"service"'),
}
for name,(a,b) in muts.items():
    assert src.count(a)==1, name
    d = pathlib.Path(tempfile.mkdtemp())
    (d/"skill").mkdir(); (d/"tests").mkdir()
    (d/"skill/relay_rotate.py").write_text(src.replace(a,b))
    shutil.copy(root/"tests/test_relay_rotate.py", d/"tests/")
    r = subprocess.run([sys.executable,"-I","tests/test_relay_rotate.py"],cwd=d,capture_output=True,text=True)
    m = re.search(r"FAILED \((.*)\)", r.stderr)
    print(("CAUGHT " if r.returncode else "MISSED ")+name+("  ["+m.group(1)+"]" if m else ""))
