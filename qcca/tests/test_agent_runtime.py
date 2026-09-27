import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config_service  # noqa: E402  (flat import, as the Agent process uses)
from agents.runtime import agent_qcca  # noqa: E402


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        expanduser = patch.object(
            config_service.os.path, "expanduser", return_value=self.temporary.name
        )
        expanduser.start()
        self.addCleanup(expanduser.stop)
        self.workspace = Path(self.temporary.name) / "ws"
        self.workspace.mkdir()

    def test_concurrent_sender_update_is_not_overwritten(self):
        config_path = config_service.config_dir_file()

        @agent_qcca
        def slow_agent(context, workspace, native_session=None, sandbox="read-only"):
            # Another sender's call finishes while this one is still running.
            other = {"200": config_service.get_dict_user("other-ws", "chat")}
            config_service.write_user_config(config_path, other)
            return "answer", None

        result = slow_agent("100", "hello", str(self.workspace), "s1", agent="codex")
        stored = {
            uid: config_service.dict_user_exist(uid) for uid in ("100", "200")
        }

        self.assertIn("创建新用户成功", result)
        self.assertIsNotNone(stored["100"])
        self.assertIsNotNone(stored["200"])
        self.assertIn(str(self.workspace), stored["100"]["workspaces"])

    def test_file_lock_is_reentrant_and_excludes_other_threads(self):
        config_path = config_service.config_dir_file()
        entered = threading.Event()

        def other_thread():
            with config_service.user_config_file_lock():
                entered.set()

        with config_service.user_config_file_lock():
            # Nested acquisition by the same thread must not deadlock.
            config_service.write_user_config(config_path, {})
            thread = threading.Thread(target=other_thread)
            thread.start()
            self.assertFalse(entered.wait(0.2))
        self.assertTrue(entered.wait(5))
        thread.join(5)


if __name__ == "__main__":
    unittest.main()
