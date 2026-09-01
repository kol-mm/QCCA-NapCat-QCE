import json
import subprocess
from pathlib import Path
from typing import Any

from .runtime import agent_qcca

SANDBOX_PERMISSION_MODES = {
    "read-only": "plan",
    "workspace-write": "acceptEdits",
}


def _permission_arguments(sandbox: str) -> list[str]:
    if sandbox == "danger-full-access":
        return ["--dangerously-skip-permissions"]
    return ["--permission-mode", SANDBOX_PERMISSION_MODES.get(sandbox, "plan")]


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
    sandbox: str = "read-only",
) -> tuple[str, str | None]:
    if not context or not context.strip():
        raise ValueError("context 不能为空")
    if not workspace:
        raise ValueError("workspace 不能为空")
    if not Path(workspace).is_dir():
        raise ValueError(f"workspace 不存在或不是目录: {workspace}")

    command = [
        "claude",
        "--print",
        "--output-format",
        "json",
        *_permission_arguments(sandbox),
    ]
    command.append(context)

    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 claude 命令，请确认 Claude Code 已安装并已加入 PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Claude 执行超时，超过 300 秒") from exc
    except OSError as exc:
        raise RuntimeError(f"Claude 启动失败: {exc}") from exc

    if result.returncode != 0:
        error_message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"Claude 执行失败，退出码: {result.returncode}"
            + (f"\n{error_message}" if error_message else "")
        )

    answer, _native_session = _parse_result(result.stdout)
    return answer, None
