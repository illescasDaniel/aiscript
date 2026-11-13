"""Small ACP child used to exercise real JSON-RPC pipes, never a live agent."""

import json
import os
import sys
import time
from typing import Any


def send(message: dict[str, Any]) -> None:
    print(json.dumps(message), flush=True)


MODELS = {"opencode_default": "opencode/iceman-free", "opencode_go": "opencode-go/glm-5.3-flash"}


def main() -> None:
    scenario = os.environ.get("FAKE_ACP_SCENARIO", "success")
    log = os.environ.get("FAKE_ACP_LOG")
    for line in sys.stdin:
        request = json.loads(line)
        method = request.get("method")
        if log:
            with open(log, "a", encoding="utf-8") as handle:
                handle.write(f"{method}\n")
        request_id = request.get("id")
        if method == "initialize":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"protocolVersion": 1, "agentCapabilities": {}},
                }
            )
        elif method == "session/new":
            result: dict[str, Any] = {"sessionId": "fixture-session"}
            if scenario in MODELS:
                result["configOptions"] = [
                    {
                        "id": "model",
                        "category": "model",
                        "type": "select",
                        "currentValue": MODELS[scenario],
                        "options": [{"value": MODELS[scenario], "name": "model"}],
                    }
                ]
            send({"jsonrpc": "2.0", "id": request_id, "result": result})
        elif method == "session/prompt":
            if scenario == "hang":
                time.sleep(30)
            elif scenario == "malformed":
                print("{invalid", flush=True)
                return
            elif scenario == "permission":
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": 901,
                        "method": "session/request_permission",
                        "params": {
                            "sessionId": "fixture-session",
                            "toolCall": {"toolCallId": "tool-1", "title": "fixture action"},
                            "options": [
                                {"optionId": "allow", "name": "Allow", "kind": "allow_once"},
                                {"optionId": "reject", "name": "Reject", "kind": "reject_once"},
                            ],
                        },
                    }
                )
                answer = json.loads(sys.stdin.readline())
                selected = answer.get("result", {}).get("outcome", {})
                if selected.get("optionId") == "allow":
                    send(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": "permission was granted"},
                        }
                    )
                    return
            if scenario == "large":
                content = "x" * 2048
            else:
                content = os.environ.get("FAKE_ACP_TEXT", "fixture answer")
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "fixture-session",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": content},
                        },
                    },
                }
            )
            send({"jsonrpc": "2.0", "id": request_id, "result": {"stopReason": "end_turn"}})


if __name__ == "__main__":
    main()
