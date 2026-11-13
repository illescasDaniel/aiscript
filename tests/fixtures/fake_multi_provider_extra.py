"""Controllable ACP subprocess for protocol boundary regression tests."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def send(message: dict[str, Any]) -> None:
    print(json.dumps(message), flush=True)


def main() -> None:
    mode = os.environ["FAKE_EXTRA_MODE"]
    pid_path = os.environ.get("FAKE_EXTRA_PID_PATH")
    if pid_path:
        Path(pid_path).write_text(str(os.getpid()), encoding="utf-8")
    for line in sys.stdin:
        message = json.loads(line)
        method, request_id = message.get("method"), message.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": 1}})
        elif method == "session/new":
            send({"jsonrpc": "2.0", "id": request_id, "result": {"sessionId": "session"}})
        elif method == "session/prompt":
            if mode == "eof":
                return
            if mode == "ratelimit":
                send({"jsonrpc": "2.0", "id": request_id, "error": {"code": 429, "message": "x"}})
                return
            if mode == "auth":
                send(
                    {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": "x"}}
                )
                return
            if mode == "grandchild":
                child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
                Path(os.environ["FAKE_EXTRA_CHILD_PID_PATH"]).write_text(str(child.pid))
            if mode == "hang":
                time.sleep(30)
                return
            if mode == "callback":
                send({"jsonrpc": "2.0", "id": 44, "method": "fs/read_text_file", "params": {}})
                reply = json.loads(sys.stdin.readline())
                if "error" not in reply:
                    sys.exit(2)
            count = 3 if mode == "aggregate" else 1
            for _ in range(count):
                text = "x" * 500 if mode == "aggregate" else "ok"
                send(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": "session",
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": text},
                            },
                        },
                    }
                )
            send({"jsonrpc": "2.0", "id": request_id, "result": {"stopReason": "end_turn"}})


if __name__ == "__main__":
    main()
