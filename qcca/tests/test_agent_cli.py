import json
import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import cli  # noqa: E402
import agents.codex as codex  # noqa: E402


def python_command(code: str) -> list[str]:
    return [sys.executable, "-c", code]


class AgentCliTests(unittest.TestCase):
    def test_run_agent_cli_returns_stdout(self):
        output = cli.run_agent_cli("Fake", python_command("print('a'); print('b')"))
        self.assertEqual(output.splitlines(), ["a", "b"])

    def test_large_output_is_streamed_not_buffered(self):
        # ~20 MB of output, like a long run full of command output events.
        code = "import sys\nline = 'x' * 1999 + '\\n'\nfor _ in range(10000): sys.stdout.write(line)"
        seen = []
        tracemalloc.start()
        try:
            cli.stream_agent_cli("Fake", python_command(code), lambda line: seen.append(len(line)))
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(len(seen), 10000)
        self.assertLess(peak, 5_000_000)

    def test_timeout_kills_the_process(self):
        with patch.object(cli, "AGENT_TIMEOUT_SECONDS", 0.5):
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                cli.stream_agent_cli("Fake", python_command("import time; time.sleep(30)"), lambda line: None)
        self.assertLess(time.monotonic() - started, 10)

    def test_failure_reports_bounded_stderr_tail(self):
        code = "import sys\nsys.stderr.write('e' * 100000 + '\\nlast error line\\n')\nsys.exit(3)"
        with self.assertRaises(RuntimeError) as caught:
            cli.stream_agent_cli("Fake", python_command(code), lambda line: None)
        message = str(caught.exception)
        self.assertIn("退出码: 3", message)
        self.assertIn("last error line", message)
        self.assertLess(len(message), cli.ERROR_TAIL_CHARS + 200)

    def test_missing_command_uses_hint(self):
        with self.assertRaises(RuntimeError) as caught:
            cli.stream_agent_cli("Fake", ["qcca-no-such-command"], lambda line: None,
                                 missing_hint="hint text")
        self.assertEqual(str(caught.exception), "hint text")


class CodexParsingTests(unittest.TestCase):
    def run_codex(self, events):
        def fake_stream(display_name, command, on_line, cwd=None, missing_hint=None):
            for event in events:
                on_line(event if isinstance(event, str) else json.dumps(event) + "\n")

        with tempfile.TemporaryDirectory() as workspace, \
                patch.object(codex, "stream_agent_cli", fake_stream):
            return codex.codex_control.__wrapped__("hello", workspace)

    def test_collects_agent_messages_and_ignores_command_output(self):
        answer, native = self.run_codex([
            {"type": "thread.started"},
            {"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": "x" * 1000}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "first"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "second"}},
        ])
        self.assertEqual(answer, "first\nsecond")
        self.assertIsNone(native)

    def test_errors_without_answer_raise_latest_errors_only(self):
        events = [{"type": "error", "message": f"error {index}"} for index in range(50)]
        with self.assertRaises(RuntimeError) as caught:
            self.run_codex(events + ["not json\n"])
        lines = str(caught.exception).splitlines()
        self.assertEqual(len(lines), codex.MAX_REPORTED_ERRORS)
        self.assertEqual(lines[-1], "无法解析 JSON: not json")


if __name__ == "__main__":
    unittest.main()
