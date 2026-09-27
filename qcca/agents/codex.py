import json
from typing import Optional

from config_service import DEFAULT_SANDBOX, VALID_SANDBOXES

from .cli import run_agent_cli, validate_request
from .runtime import agent_qcca


@agent_qcca
def codex_control(
    context: str,
    workspace: str,
    native_session: Optional[str] = None,
    sandbox: str = DEFAULT_SANDBOX,
):
    validate_request(context, workspace)
    sandbox = sandbox if sandbox in VALID_SANDBOXES else DEFAULT_SANDBOX

    stdout = run_agent_cli("Codex", [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "-C",
        workspace,
        "--sandbox",
        sandbox,
        context,
    ])

    out_list = []
    error_list = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            line_json = json.loads(line)
        except json.JSONDecodeError:
            error_list.append(f"无法解析 JSON: {line[:200]}")
            continue

        if not isinstance(line_json, dict):
            continue

        if line_json.get("type") == "thread.started":
            # Native Codex session IDs are intentionally not persisted;
            # QCCA uses its own shared JSONL session memory.
            continue

        elif line_json.get("type") in {"error", "thread.error"}:
            error_list.append(
                str(line_json.get("message") or line_json.get("error") or line_json)
            )

        elif line_json.get("type") == "item.completed":
            item = line_json.get("item")
            if not isinstance(item, dict):
                continue

            if item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str) and text:
                    out_list.append(text)
                    print(text)

    if error_list and not out_list:
        raise RuntimeError("\n".join(error_list))

    return "\n".join(out_list), None
