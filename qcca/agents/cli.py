import subprocess
from pathlib import Path

AGENT_TIMEOUT_SECONDS = 300


def validate_request(context: str, workspace: str) -> None:
    if not context or not context.strip():
        raise ValueError("context 不能为空")
    if not workspace:
        raise ValueError("workspace 不能为空")
    if not Path(workspace).is_dir():
        raise ValueError(f"workspace 不存在或不是目录: {workspace}")


def run_agent_cli(display_name: str, command: list[str], cwd: str | None = None,
                  missing_hint: str | None = None) -> str:
    """Run an Agent CLI and return stdout, mapping failures to readable errors."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=AGENT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            missing_hint or f"未找到 {command[0]} 命令，请确认已安装并已加入 PATH"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"{display_name} 执行超时，超过 {AGENT_TIMEOUT_SECONDS} 秒"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"{display_name} 启动失败: {exc}") from exc

    if result.returncode != 0:
        error_message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"{display_name} 执行失败，退出码: {result.returncode}"
            + (f"\n{error_message}" if error_message else "")
        )
    return result.stdout
