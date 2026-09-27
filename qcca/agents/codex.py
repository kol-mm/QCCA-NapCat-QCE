import json
from collections import deque
from typing import Optional

from config_service import DEFAULT_SANDBOX, VALID_SANDBOXES

from .cli import stream_agent_cli, validate_request
from .runtime import agent_qcca

MAX_REPORTED_ERRORS = 20


@agent_qcca
def codex_control(
    context: str,
    workspace: str,
    native_session: Optional[str] = None,
    sandbox: str = DEFAULT_SANDBOX,
):
    validate_request(context, workspace)
    sandbox = sandbox if sandbox in VALID_SANDBOXES else DEFAULT_SANDBOX

    out_list = []
    # Only the latest few errors are reported; a long run must not grow this.
    error_list: deque[str] = deque(maxlen=MAX_REPORTED_ERRORS)

    def handle_line(line: str) -> None:
        line = line.strip()
        if not line:
            return

        try:
            line_json = json.loads(line)
        except json.JSONDecodeError:
            error_list.append(f"无法解析 JSON: {line[:200]}")
            return

        if not isinstance(line_json, dict):
            return

        if line_json.get("type") == "thread.started":
            # Native Codex session IDs are intentionally not persisted;
            # QCCA uses its own shared JSONL session memory.
            return

        elif line_json.get("type") in {"error", "thread.error"}:
            error_list.append(
                str(line_json.get("message") or line_json.get("error") or line_json)[:2000]
            )

        elif line_json.get("type") == "item.completed":
            item = line_json.get("item")
            if not isinstance(item, dict):
                return

            if item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str) and text:
                    out_list.append(text)
                    print(text)

    # Events are parsed as they stream in; command output inside them is
    # dropped immediately instead of buffering the whole run in memory.
    stream_agent_cli("Codex", [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "-C",
        workspace,
        "--sandbox",
        sandbox,
        context,
    ], handle_line)

    if error_list and not out_list:
        raise RuntimeError("\n".join(error_list))

    return "\n".join(out_list), None
