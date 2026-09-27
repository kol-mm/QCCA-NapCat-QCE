import gc
import json
import sys
import tempfile
import threading
import time
import types
import unittest
import weakref
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("pysilk", types.ModuleType("pysilk"))

try:
    import qq_cloud_control_agent as watcher
except ImportError:  # pragma: no cover - watchdog/requests are optional here
    watcher = None


class FakeModel:
    def generate(self, input):
        return [{"text": "识别结果"}]


@unittest.skipIf(watcher is None, "Agent watcher dependencies are not installed")
class AudioModelManagerTests(unittest.TestCase):
    def setUp(self):
        # Safety net: anything that escapes the status patch below still
        # writes into a temporary folder, never the real QCCA data folder.
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = patch.object(watcher.config_service.os.path, "expanduser", return_value=temporary.name)
        home.start()
        self.addCleanup(home.stop)
        self.published = []
        publisher = patch.object(
            watcher.config_service, "update_audio_model_status",
            side_effect=lambda status, message="": self.published.append(status),
        )
        publisher.start()
        self.addCleanup(publisher.stop)
        self.loads = 0
        self.models = []

    def loader(self):
        self.loads += 1
        model = FakeModel()
        self.models.append(weakref.ref(model))
        return model

    def test_off_never_loads(self):
        manager = watcher.AudioModelManager("off", 600, self.loader)
        manager.start()
        with self.assertRaises(watcher.AudioModelDisabled):
            manager.transcribe([0.0])
        self.assertEqual(self.loads, 0)
        self.assertEqual(self.published, ["disabled"])

    def test_lazy_loads_on_first_use_only(self):
        manager = watcher.AudioModelManager("lazy", 600, self.loader)
        manager.start()
        self.assertFalse(manager.loaded)
        self.assertEqual(manager.transcribe([0.0]), [{"text": "识别结果"}])
        manager.transcribe([0.0])
        self.assertEqual(self.loads, 1)
        self.assertEqual(self.published, ["standby", "loading", "ready"])

    def test_eager_loads_in_background(self):
        manager = watcher.AudioModelManager("eager", 600, self.loader)
        manager.start()
        deadline = time.monotonic() + 5
        while self.published[-1:] != ["ready"] and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(manager.loaded)
        self.assertEqual(self.loads, 1)

    def test_idle_model_is_released_and_reloaded(self):
        manager = watcher.AudioModelManager("lazy", 0.05, self.loader)
        manager.transcribe([0.0])
        self.assertFalse(manager.release_if_idle())  # just used
        time.sleep(0.1)
        self.assertTrue(manager.release_if_idle())
        gc.collect()
        self.assertIsNone(self.models[0]())  # nothing else keeps the weights alive
        self.assertEqual(self.published[-1], "standby")
        manager.transcribe([0.0])
        self.assertEqual(self.loads, 2)

    def test_zero_idle_keeps_model(self):
        manager = watcher.AudioModelManager("lazy", 0, self.loader)
        manager.transcribe([0.0])
        time.sleep(0.02)
        self.assertFalse(manager.release_if_idle())
        self.assertTrue(manager.loaded)

    def test_release_waits_for_running_transcription(self):
        started, finish = threading.Event(), threading.Event()

        class SlowModel:
            def generate(self, input):
                started.set()
                finish.wait(5)
                return []

        manager = watcher.AudioModelManager("lazy", 0.01, lambda: SlowModel())
        worker = threading.Thread(target=manager.transcribe, args=([0.0],))
        worker.start()
        self.assertTrue(started.wait(5))
        time.sleep(0.05)
        self.assertFalse(manager.release_if_idle())
        finish.set()
        worker.join(5)

    def test_failed_load_is_reported_and_retried(self):
        attempts = []

        def flaky_loader():
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError("download failed")
            return FakeModel()

        manager = watcher.AudioModelManager("lazy", 600, flaky_loader)
        with self.assertRaises(OSError):
            manager.transcribe([0.0])
        self.assertEqual(self.published[-1], "failed")
        self.assertEqual(manager.transcribe([0.0]), [{"text": "识别结果"}])
        self.assertEqual(len(attempts), 2)

    def test_busy_when_loading_takes_too_long(self):
        release = threading.Event()

        def slow_loader():
            release.wait(5)
            return FakeModel()

        manager = watcher.AudioModelManager("eager", 600, slow_loader)
        manager.start()
        time.sleep(0.05)
        with patch.object(watcher, "AUDIO_MODEL_WAIT_SECONDS", 0.1):
            with self.assertRaises(watcher.AudioModelBusy):
                manager.transcribe([0.0])
        release.set()
        # Let the background load finish while the status patch is active.
        deadline = time.monotonic() + 5
        while self.published[-1:] != ["ready"] and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(manager.loaded)

    def test_heartbeat_republishes_current_status(self):
        manager = watcher.AudioModelManager("lazy", 600, self.loader)
        manager.heartbeat()
        self.assertEqual(self.published, [])  # nothing reported before start
        manager.start()
        manager.heartbeat()
        self.assertEqual(self.published, ["standby", "standby"])

    def test_settings_from_environment(self):
        with patch.dict(watcher.os.environ, {"QCCA_AUDIO_MODEL": " OFF ", "QCCA_AUDIO_IDLE_MINUTES": "2.5"}):
            self.assertEqual(watcher.audio_model_mode(), "off")
            self.assertEqual(watcher.audio_idle_seconds(), 150)
        with patch.dict(watcher.os.environ, {"QCCA_AUDIO_MODEL": "bogus", "QCCA_AUDIO_IDLE_MINUTES": "x"}):
            self.assertEqual(watcher.audio_model_mode(), "eager")
            self.assertEqual(watcher.audio_idle_seconds(), watcher.DEFAULT_AUDIO_IDLE_MINUTES * 60)
        with patch.dict(watcher.os.environ, {"QCCA_AUDIO_IDLE_MINUTES": "-5"}):
            self.assertEqual(watcher.audio_idle_seconds(), 0)

    def test_voice_message_when_off_replies_without_decoding(self):
        with tempfile.TemporaryDirectory() as temporary:
            voice = Path(temporary) / "voice.silk"
            voice.write_bytes(b"#!SILK_V3 data")
            capture = Path(temporary) / "capture.jsonl"
            capture.write_text(json.dumps({
                "message": {"sender": {"uin": 555}, "content": {"elements": [{"type": "audio"}]}},
                "media": [{"localPath": str(voice)}],
            }), encoding="utf-8")
            handler = watcher.myFileSystemEventHandler()
            manager = watcher.AudioModelManager("off", 600, self.loader)
            with patch.object(watcher, "audio_models", manager), \
                    patch.object(watcher, "get_login_uid", return_value="10001"), \
                    patch.object(watcher, "send_email") as send_email, \
                    patch.object(watcher, "silk_to_pcm") as decode, \
                    patch.object(watcher, "sleep"):
                handler.process_file(str(capture))

        decode.assert_not_called()
        send_email.assert_called_once()
        self.assertIn("语音识别已关闭", send_email.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
