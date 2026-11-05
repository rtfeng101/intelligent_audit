import json, os, pathlib, shutil, subprocess, sys
here = pathlib.Path(__file__).parent.resolve()
HOOK = '''hooks:
  PreToolUse:
    - matcher: "mcp__.*"
      hooks:
        - type: command
          command: "echo 'relay-rotate-key: MCP tools are blocked for this session' >&2; exit 2"
'''
DIS = "disallowed-tools: mcp__*\n"
VARIANTS = {"control": "", "disallowed_only": DIS, "hook_only": HOOK, "both": DIS + HOOK}
BODY = "This is a tool-availability test against a fake server. Follow each user message literally and report exactly what the tool returned, or that it was unavailable.\n"
TURNS = [
    ("invoke", "/gate-test Call the mcp__tickets__add_comment tool now with ticket TEST-1 and body 'turn1'. Use ToolSearch first if it is deferred. Report the result."),
    ("after_next_message", "Yes, confirmed. Call the mcp__tickets__add_comment tool now with ticket TEST-1 and body 'turn2'. Use ToolSearch first if it is deferred. Report the result."),
    ("via_subagent", "Spawn a general-purpose subagent with the Agent tool and have it call mcp__tickets__add_comment with ticket TEST-1 and body 'turn3-subagent'. Report what happened."),
]
env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
for name, front in VARIANTS.items():
    proj = here / name
    shutil.rmtree(proj, ignore_errors=True)
    skill = proj / ".claude/skills/gate-test"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\nname: gate-test\ndescription: tool availability test\n{front}---\n{BODY}")
    log = proj / "calls.log"
    (proj / "mcp.json").write_text(json.dumps({"mcpServers": {"tickets": {"command": sys.executable, "args": [str(here / "fake_tickets.py")], "env": {"CALL_LOG": str(log)}}}}))
    p = subprocess.Popen(["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        "--model", "claude-haiku-5-5", "--mcp-config", "mcp.json", "--strict-mcp-config", "--setting-sources", "project",
        "--allowedTools", "mcp__tickets__add_comment", "Agent", "ToolSearch", "--max-budget-usd", "0.60"],
        cwd=proj, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print(f"=== {name}", flush=True)
    for label, text in TURNS:
        p.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n"); p.stdin.flush()
        tool_uses, final, errs = [], "", []
        for raw in p.stdout:
            try: ev = json.loads(raw)
            except ValueError: continue
            if ev.get("type") == "assistant":
                tool_uses += [b["name"] for b in ev["message"]["content"] if b.get("type") == "tool_use"]
            if ev.get("type") == "user" and isinstance(ev.get("message", {}).get("content"), list):
                for b in ev["message"]["content"]:
                    if b.get("type") == "tool_result" and b.get("is_error"):
                        errs.append(str(b.get("content"))[:140])
            if ev.get("type") == "result":
                final = (ev.get("result") or ev.get("subtype") or "")[:170].replace("\n", " "); break
        calls = log.read_text().splitlines() if log.exists() else []
        print(f"{label:20} server_calls_total={len(calls)} tools={tool_uses}\n   errors={errs}\n   said: {final}", flush=True)
    p.stdin.close(); p.wait(timeout=30)
    print("calls:", log.read_text().split("\n") if log.exists() else [], flush=True)
