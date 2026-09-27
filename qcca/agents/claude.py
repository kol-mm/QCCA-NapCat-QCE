import json
from typing import Any

from config_service import DEFAULT_SANDBOX

from .cli import run_agent_cli, validate_request
from .runtime import agent_qcca

SANDBOX_PERMISSION_MODES = {
    "read-only": "plan",
    "workspace-write": "acceptEdits",
}


def _permission_arguments(sandbox: str) -> list[str]:
    if sandbox == "danger-full-access":
        return ["--dangerously-skip-permissions"]
    return ["--permission-mode", SANDBOX_PERMISSION_MODES.get(sandbox, SANDBOX_PERMISSION_MODES[DEFAULT_SANDBOX])]


def _parse_result(stdout: str) -> tuple[str, str | None]:
    """Parse Claude's JSON result and return answer text plus session ID."""
    answer = []
    session_id = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value: Any = json.loads(line)
        except json.JSONDecodeError:
            answer.append(line)
            continue

        if not isinstance(value, dict):
            continue
        if isinstance(value.get("session_id"), str) and value["session_id"]:
            session_id = value["session_id"]
        if value.get("type") == "result":
            if value.get("is_error"):
                raise RuntimeError(str(value.get("result") or value.get("error") or value))
            result = value.get("result")
            if isinstance(result, str) and result:
                answer.append(result)
        elif isinstance(value.get("result"), str) and value["result"]:
            answer.append(value["result"])

    if not answer:
        raise RuntimeError("Claude 未返回有效内容")
    return "\n".join(answer), session_id


@agent_qcca
def claude_control(
    context: str,
    workspace: str,
    native_session: str | None = None,
    sandbox: str = DEFAULT_SANDBOX,
) -> tuple[str, str | None]:
    validate_request(context, workspace)
    command = [
        "claude",
        "--print",
        "--output-format",
        "json",
        *_permission_arguments(sandbox),
        context,
    ]
    stdout = run_agent_cli(
        "Claude", command, cwd=workspace,
        missing_hint="未找到 claude 命令，请确认 Claude Code 已安装并已加入 PATH",
    )
    answer, _native_session = _parse_result(stdout)
    return answer, None
