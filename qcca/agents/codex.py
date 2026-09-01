import json
import subprocess
from typing import Optional
from pathlib import Path

from .runtime import agent_qcca

VALID_SANDBOXES = {"read-only", "workspace-write", "danger-full-access"}

@agent_qcca
def codex_control(
    context: str,
    workspace: str,
    native_session: Optional[str] = None,
    sandbox: str = "read-only",
):
    if not context or not context.strip():
        raise ValueError("context 不能为空")

    if not workspace:
        raise ValueError("workspace 不能为空")

    sandbox = sandbox if sandbox in VALID_SANDBOXES else "read-only"

    if not Path(workspace).is_dir():
        raise ValueError(f"workspace 不存在或不是目录: {workspace}")

    cmd_list = [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "-C",
        workspace,
        "--sandbox",
        sandbox,
    ]

    cmd_list.append(context)
    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError("未找到 codex 命令，请确认已安装并已加入 PATH") from e
    except subprocess.TimeoutExpired as e:
        raise TimeoutError("Codex 执行超时，超过 300 秒") from e
    except OSError as e:
        raise RuntimeError(f"Codex 启动失败: {e}") from e

    if result.returncode != 0:
        error_message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"Codex 执行失败，退出码: {result.returncode}"
            + (f"\n{error_message}" if error_message else "")
        )

    stdout_list = result.stdout
    out_list = []
    error_list = []

    for line in stdout_list.splitlines():
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
