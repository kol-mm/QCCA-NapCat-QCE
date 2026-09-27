import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# The voice decoder is a Windows runtime dependency; the watcher logic under
# test here never touches it.
sys.modules.setdefault("pysilk", types.ModuleType("pysilk"))

try:
    import qq_cloud_control_agent as watcher
except ImportError:  # pragma: no cover - watchdog/requests are optional here
    watcher = None


@unittest.skipIf(watcher is None, "Agent watcher dependencies are not installed")
class AgentWatcherTests(unittest.TestCase):
    def test_non_message_events_skip_login_lookup(self):
        handler = watcher.myFileSystemEventHandler()
        events = [
            types.SimpleNamespace(is_directory=True, src_path="capture/day"),
            types.SimpleNamespace(is_directory=False, src_path="capture/voice.amr"),
            types.SimpleNamespace(is_directory=False, src_path="capture/voice.wav"),
        ]
        with patch.object(watcher, "get_login_uid") as login:
            for event in events:
                handler.on_created(event)
        login.assert_not_called()

    def test_vanished_jsonl_does_not_raise(self):
        handler = watcher.myFileSystemEventHandler()
        event = types.SimpleNamespace(is_directory=False, src_path="missing/capture.jsonl")
        with patch.object(watcher, "get_login_uid", return_value="10001"), \
                patch.object(watcher, "sleep"):
            handler.on_created(event)

    def test_wait_for_stable_size(self):
        with patch.object(watcher, "sleep"), \
                patch.object(watcher.os.path, "getsize", side_effect=[0, 0, 4, 4]):
            self.assertTrue(watcher.wait_for_stable_size("x", 5, require_content=False))
        with patch.object(watcher, "sleep"), \
                patch.object(watcher.os.path, "getsize", side_effect=[0, 0, 4, 4]):
            self.assertTrue(watcher.wait_for_stable_size("x", 5, require_content=True))
        with patch.object(watcher, "sleep"), \
                patch.object(watcher.os.path, "getsize", side_effect=OSError):
            self.assertFalse(watcher.wait_for_stable_size("x", 3, require_content=True))

    def test_read_sender_uid_uses_last_valid_message(self):
        lines = [
            "not json",
            json.dumps(["not", "an", "object"]),
            json.dumps({"message": {"sender": {"uin": 111}, "content": {"elements": [{}]}}}),
            json.dumps({"message": {"sender": {"uin": 222}, "content": {"elements": []}}}),
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as file:
            file.write("\n".join(lines))
        self.addCleanup(Path(file.name).unlink)
        self.assertEqual(watcher.read_sender_uid(file.name), "111")

    def test_on_created_dispatches_by_sender(self):
        message = {"message": {"sender": {"uin": 333}, "content": {"elements": [{}]}}}
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as file:
            file.write(json.dumps(message))
        self.addCleanup(Path(file.name).unlink)
        dispatched = []
        dispatcher = types.SimpleNamespace(
            submit=lambda key, func, *args: dispatched.append((key, func, args))
        )
        handler = watcher.myFileSystemEventHandler(dispatcher)
        with patch.object(watcher, "sleep"):
            handler.on_created(types.SimpleNamespace(is_directory=False, src_path=file.name))
        self.assertEqual(dispatched, [("333", handler.process_file, (file.name,))])

    def test_dispatcher_orders_per_sender_and_runs_senders_in_parallel(self):
        dispatcher = watcher.PerSenderDispatcher(max_workers=2)
        self.addCleanup(dispatcher.shutdown)
        release_a = threading.Event()
        b_done = threading.Event()
        order = []
        lock = threading.Lock()

        def record(name, wait=None, done=None):
            if wait is not None:
                self.assertTrue(wait.wait(5))
            with lock:
                order.append(name)
            if done is not None:
                done.set()

        a_done = threading.Event()
        dispatcher.submit("a", record, "a1", release_a)
        dispatcher.submit("a", record, "a2", None, a_done)
        dispatcher.submit("b", record, "b1", None, b_done)
        # b finishes while a's first message is still blocked.
        self.assertTrue(b_done.wait(5))
        release_a.set()
        self.assertTrue(a_done.wait(5))
        self.assertEqual(order, ["b1", "a1", "a2"])

    def test_dispatcher_survives_task_errors(self):
        dispatcher = watcher.PerSenderDispatcher(max_workers=1)
        self.addCleanup(dispatcher.shutdown)
        done = threading.Event()

        def fail():
            raise RuntimeError("boom")

        dispatcher.submit("a", fail)
        dispatcher.submit("a", done.set)
        self.assertTrue(done.wait(5))

    def test_status_stays_running_while_another_sender_is_busy(self):
        published = []
        with patch.object(watcher, "publish_agent_status",
                          side_effect=lambda status, **context: published.append((status, context))):
            watcher.begin_agent_run("1", agent="codex")
            watcher.begin_agent_run("2", agent="claude")
            watcher.end_agent_run("2", "idle", agent="claude")
            watcher.end_agent_run("1", "failed", agent="codex", message="x")

        self.assertEqual([status for status, _ in published],
                         ["running", "running", "running", "failed"])
        self.assertEqual(published[2][1]["uid"], "1")
        self.assertEqual(published[3][1], {"uid": "1", "agent": "codex", "message": "x"})

    def test_max_parallel_senders_reads_environment(self):
        with patch.dict(watcher.os.environ, {"QCCA_MAX_PARALLEL_SENDERS": "5"}):
            self.assertEqual(watcher.max_parallel_senders(), 5)
        with patch.dict(watcher.os.environ, {"QCCA_MAX_PARALLEL_SENDERS": "bad"}):
            self.assertEqual(watcher.max_parallel_senders(), watcher.DEFAULT_MAX_PARALLEL_SENDERS)
        with patch.dict(watcher.os.environ, {"QCCA_MAX_PARALLEL_SENDERS": "0"}):
            self.assertEqual(watcher.max_parallel_senders(), 1)


if __name__ == "__main__":
    unittest.main()
