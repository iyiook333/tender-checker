import unittest

from fastapi.testclient import TestClient

import app.main as main
from app.main import app


class ApiTests(unittest.TestCase):
    def test_analyze_requires_explicit_model_configuration(self):
        client = TestClient(app)
        response = client.post(
            "/api/analyze",
            files={"file": ("notice.txt", b"qualification", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("模型名称", response.json()["detail"])

    def test_analyze_rejects_when_active_task_limit_is_reached(self):
        client = TestClient(app)
        original_limit = main.MAX_ACTIVE_TASKS
        original_tasks = main._tasks.copy()
        original_created = main._task_created_at.copy()
        try:
            main.MAX_ACTIVE_TASKS = 1
            main._tasks.clear()
            main._task_created_at.clear()
            main._tasks["active"] = main.TaskStatus(
                task_id="active", filename="a.txt", status="running", stage="抽取条款", progress=30
            )
            response = client.post(
                "/api/analyze",
                data={"model": "mock", "protocol": "openai", "base_url": "http://127.0.0.1:15721/v1"},
                files={"file": ("notice.txt", b"qualification", "text/plain")},
            )
            self.assertEqual(response.status_code, 429)
        finally:
            main.MAX_ACTIVE_TASKS = original_limit
            main._tasks.clear()
            main._tasks.update(original_tasks)
            main._task_created_at.clear()
            main._task_created_at.update(original_created)


if __name__ == "__main__":
    unittest.main()
