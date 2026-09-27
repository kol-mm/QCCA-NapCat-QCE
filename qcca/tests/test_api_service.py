import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fastapi.testclient import TestClient

    import api_service
    import config_service
except ImportError:  # pragma: no cover - API dependencies are optional here
    api_service = None


@unittest.skipIf(api_service is None, "FastAPI test dependencies are not installed")
class ApiServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        expanduser = patch.object(
            config_service.os.path, "expanduser", return_value=self.temporary.name
        )
        expanduser.start()
        self.addCleanup(expanduser.stop)
        api_service._invalidate_status_cache()
        self.addCleanup(api_service._invalidate_status_cache)
        self.client = TestClient(api_service.app)

    def test_records_endpoint_returns_total_and_bounded_tail(self):
        for index in range(api_service.MAX_RECORDS_RESPONSE + 5):
            config_service.MemoryLine("user", str(index), "session-a")

        response = self.client.get("/qcca/records/session-a")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], api_service.MAX_RECORDS_RESPONSE + 5)
        self.assertEqual(len(body["records"]), api_service.MAX_RECORDS_RESPONSE)
        self.assertEqual(body["records"][0]["content"], "5")
        self.assertEqual(self.client.get("/qcca/records/bad..%5Cid").status_code, 400)

    def test_records_endpoint_revalidates_with_etag(self):
        config_service.MemoryLine("user", "hello", "session-b")
        first = self.client.get("/qcca/records/session-b")
        etag = first.headers["etag"]

        unchanged = self.client.get("/qcca/records/session-b", headers={"If-None-Match": etag})
        self.assertEqual(unchanged.status_code, 304)
        self.assertEqual(unchanged.content, b"")

        config_service.MemoryLine("assistant", "world", "session-b")
        changed = self.client.get("/qcca/records/session-b", headers={"If-None-Match": etag})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["total"], 2)
        self.assertNotEqual(changed.headers["etag"], etag)

        missing = self.client.get("/qcca/records/none", headers={"If-None-Match": etag})
        self.assertEqual(missing.json(), {"session_id": "none", "total": 0, "records": []})

    def test_system_status_queries_login_once(self):
        with patch.object(api_service, "_get_current_login_qq", return_value=None) as login, \
                patch.object(api_service, "_port_is_open", return_value=False):
            response = self.client.get("/qcca/system-status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(login.call_count, 1)
        self.assertEqual(response.json()["overall"], "error")

    def test_system_status_is_briefly_cached_and_invalidated_by_writes(self):
        with patch.object(api_service, "_get_current_login_qq", return_value=None) as login, \
                patch.object(api_service, "_port_is_open", return_value=False):
            self.client.get("/qcca/system-status")
            self.client.get("/qcca/system-status")
            self.assertEqual(login.call_count, 1)
            self.client.put("/qcca/smtp-config", json={"sender_qq": "12345", "auth_code": "code"})
            calls_after_write = login.call_count
            self.client.get("/qcca/system-status")

        self.assertEqual(login.call_count, calls_after_write + 1)

    def test_audio_standby_and_disabled_are_not_warnings(self):
        for status, summary in (("standby", "按需加载"), ("disabled", "已按设置关闭")):
            api_service._invalidate_status_cache()
            with patch.object(api_service, "_get_current_login_qq", return_value=None), \
                    patch.object(api_service, "_port_is_open", return_value=False), \
                    patch.object(config_service, "get_audio_model_status",
                                 return_value={"status": status, "message": ""}):
                services = self.client.get("/qcca/system-status").json()["services"]
            audio = next(item for item in services if item["id"] == "audio")
            self.assertEqual((audio["status"], audio["summary"]), ("ready", summary))

    def test_config_update_round_trip_keeps_session_ids(self):
        config_path = config_service.config_dir_file()
        users = {"100": config_service.get_dict_user("ws", "chat")}
        config_service.write_user_config(config_path, users)
        session_id = users["100"]["workspaces"]["ws"]["sessions"]["chat"]["id"]

        payload = {
            "workspaces": {"ws": {"sandbox": "workspace-write", "sessions": {
                "chat": {"id": session_id, "agent": "Claude"},
            }}},
            "recent_workspace_and_session": {"ws": "chat"},
        }
        self.assertEqual(self.client.put("/qcca/config/update/100", json=payload).status_code, 200)
        stored = self.client.get("/qcca/config/100").json()

        self.assertEqual(stored["workspaces"]["ws"]["sandbox"], "workspace-write")
        self.assertEqual(stored["workspaces"]["ws"]["sessions"]["chat"],
                         {"id": session_id, "agent": "claude"})

        payload["workspaces"]["ws"]["sessions"]["chat"]["id"] = "other"
        self.assertEqual(self.client.put("/qcca/config/update/100", json=payload).status_code, 400)


if __name__ == "__main__":
    unittest.main()
