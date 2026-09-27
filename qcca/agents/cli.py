import subprocess
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

AGENT_TIMEOUT_SECONDS = 300
# Only the end of the output is kept for error messages; a long Agent run can
# print tens of megabytes of command output that must not be held in memory.
ERROR_TAIL_CHARS = 4000


def validate_request(context: str, workspace: str) -> None:
    if not context or not context.strip():
        raise ValueError("context 不能为空")
    if not workspace:
        raise ValueError("workspace 不能为空")
    if not Path(workspace).is_dir():
        raise ValueError(f"workspace 不存在或不是目录: {workspace}")


class _TextTail:
    """Keep roughly the last ``limit`` characters of a stream of lines."""

    def __init__(self, limit: int = ERROR_TAIL_CHARS):
        self._limit = limit
        self._lines: deque[str] = deque()
        self._size = 0

    def add(self, line: str) -> None:
        self._lines.append(line)
        self._size += len(line)
        while self._size > self._limit and len(self._lines) > 1:
            self._size -= len(self._lines.popleft())

    def text(self) -> str:
        return "".join(self._lines).strip()[-self._limit:]


def stream_agent_cli(display_name: str, command: list[str], on_line: Callable[[str], None],
                     cwd: str | None = None, missing_hint: str | None = None) -> None:
    """Run an Agent CLI, passing each stdout line to ``on_line`` as it arrives.

    Output is never accumulated here, so memory stays flat however much the
    CLI prints. Failures are mapped to readable errors as before.
    """
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            missing_hint or f"未找到 {command[0]} 命令，请确认已安装并已加入 PATH"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"{display_name} 启动失败: {exc}") from exc

    stderr_tail = _TextTail()
    stdout_tail = _TextTail()
    timed_out = threading.Event()

    def drain_stderr() -> None:
        # Drain stderr concurrently so a chatty CLI cannot block on a full pipe.
        for line in process.stderr:
            stderr_tail.add(line)

    def kill_on_timeout() -> None:
        timed_out.set()
        process.kill()

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()
    timer = threading.Timer(AGENT_TIMEOUT_SECONDS, kill_on_timeout)
    timer.daemon = True
    timer.start()
    try:
        with process.stdout:
            for line in process.stdout:
                stdout_tail.add(line)
                on_line(line)
        returncode = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        timer.cancel()
        stderr_thread.join(timeout=5)
        process.stderr.close()

    if timed_out.is_set():
        raise TimeoutError(f"{display_name} 执行超时，超过 {AGENT_TIMEOUT_SECONDS} 秒")
    if returncode != 0:
        error_message = stderr_tail.text() or stdout_tail.text()
        raise RuntimeError(
            f"{display_name} 执行失败，退出码: {returncode}"
            + (f"\n{error_message}" if error_message else "")
        )


def run_agent_cli(display_name: str, command: list[str], cwd: str | None = None,
                  missing_hint: str | None = None) -> str:
    """Run an Agent CLI and return its full stdout (for CLIs with small output)."""
    lines: list[str] = []
    stream_agent_cli(display_name, command, lines.append, cwd=cwd, missing_hint=missing_hint)
    return "".join(lines)
