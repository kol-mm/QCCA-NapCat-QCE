import sys
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


if __name__ == "__main__":
    unittest.main()
