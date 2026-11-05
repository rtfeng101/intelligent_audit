import json, os, sys
LOG = os.environ["CALL_LOG"]
TOOL = {"name": "add_comment", "description": "Add a comment to a ticket", "inputSchema": {"type": "object", "properties": {"ticket": {"type": "string"}, "body": {"type": "string"}}, "required": ["ticket", "body"]}}
for line in sys.stdin:
    msg = json.loads(line)
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        continue
    if method == "initialize":
        result = {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "tickets", "version": "0"}}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        with open(LOG, "a") as f:
            f.write(json.dumps(msg["params"]["arguments"]) + "\n")
        result = {"content": [{"type": "text", "text": "comment added"}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}), flush=True)
