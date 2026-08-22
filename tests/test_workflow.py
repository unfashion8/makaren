import os
import unittest
from unittest.mock import patch

import app as app_module
from makaren_workflow import (
    SupabaseWorkflowStore,
    build_art_prompt,
    generate_review_token,
    hash_review_token,
)


class NoopThread:
    def __init__(self, *args, **kwargs):
        self.target = kwargs.get("target")
        self.args = kwargs.get("args", ())

    def start(self):
        return None


class FakeStore:
    def __init__(self, token="review-token"):
        token_hash = hash_review_token(token)
        self.rows = {
            "makaren_workflows": [
                {
                    "id": "wf-1",
                    "customer_name": "KIMURA KENJI",
                    "email": "test@example.com",
                    "birth_date": "1980/01/02",
                    "product": "profile_only",
                    "consultation": "",
                    "numbers_full": {"numbers": {"核数": "7"}, "nine_year_cycle": []},
                    "others": [],
                    "status": "awaiting_review",
                    "review_token_hash": token_hash,
                    "current_version": 1,
                    "revision_count": 0,
                    "max_revisions": 3,
                    "expires_at": "2099-01-01T00:00:00+00:00",
                }
            ],
            "makaren_workflow_versions": [
                {
                    "id": "version-1",
                    "workflow_id": "wf-1",
                    "version_no": 1,
                    "profile_text": "現在の鑑定書",
                    "relationship_text": None,
                    "art_storage_path": "workflows/wf-1/v1/art.png",
                    "pdf_storage_path": "workflows/wf-1/v1/report.pdf",
                    "status": "ready",
                }
            ],
            "makaren_deliveries": [],
            "makaren_feedback": [],
            "makaren_workflow_events": [],
            "makaren_readings": [],
        }
        self.sequence = 1

    @staticmethod
    def _matches(row, filters):
        for key, expression in (filters or {}).items():
            expected = str(expression).removeprefix("eq.")
            if str(row.get(key)) != expected:
                return False
        return True

    def select_one(self, table, *, filters, columns="*"):
        return next(
            (dict(row) for row in self.rows[table] if self._matches(row, filters)),
            None,
        )

    def select(self, table, **kwargs):
        return [dict(row) for row in self.rows[table]]

    def update(self, table, values, *, filters):
        updated = []
        for row in self.rows[table]:
            if self._matches(row, filters):
                row.update(values)
                updated.append(dict(row))
        return updated

    def insert(self, table, row):
        self.sequence += 1
        saved = dict(row)
        saved.setdefault("id", f"fake-{self.sequence}")
        self.rows[table].append(saved)
        return dict(saved)

    def signed_url(self, path, expires_in=600):
        return f"https://example.supabase.co/signed/{path}"

    def download(self, path):
        return b"%PDF-1.4 fake"


class WorkflowHelpersTest(unittest.TestCase):
    def test_review_token_is_random_and_only_hash_is_stable(self):
        first = generate_review_token()
        second = generate_review_token()
        self.assertNotEqual(first, second)
        self.assertEqual(len(hash_review_token(first)), 64)
        self.assertEqual(hash_review_token(first), hash_review_token(first))

    def test_art_prompt_contains_numbers_and_safety_constraints(self):
        prompt = build_art_prompt("静けさと前進の両立", {"核数": 7, "魂数": 4, "使命数": 8})
        self.assertIn("Core number: 7", prompt)
        self.assertIn("No text", prompt)
        self.assertIn("vertical 2:3", prompt)

    def test_signed_storage_path_uses_storage_api_base(self):
        store = SupabaseWorkflowStore("https://example.supabase.co", "secret")
        with patch.object(
            store,
            "_request",
            return_value={"signedURL": "/object/sign/private/report.pdf?token=abc"},
        ):
            signed = store.signed_url("private/report.pdf")
        self.assertEqual(
            signed,
            "https://example.supabase.co/storage/v1/object/sign/private/report.pdf?token=abc",
        )


class WorkflowRoutesTest(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.env = patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "server-secret",
            },
        )
        self.env.start()
        self.store_patch = patch.object(app_module, "get_workflow_store", return_value=self.store)
        self.store_patch.start()
        self.thread_patch = patch.object(app_module, "Thread", NoopThread)
        self.thread_patch.start()
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.thread_patch.stop()
        self.store_patch.stop()
        self.env.stop()

    def test_review_page_is_private_and_not_cached(self):
        response = self.client.get("/review/review-token")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertNotIn(b"server-secret", response.data)

    def test_feedback_reserves_current_version_and_blocks_duplicate(self):
        payload = {
            "target": "profile",
            "instruction": "仕事の説明を現在の実感に合わせてください",
            "base_version": 1,
        }
        first = self.client.post("/api/review/review-token/feedback", json=payload)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(self.store.rows["makaren_workflows"][0]["status"], "revision_requested")
        self.assertEqual(len(self.store.rows["makaren_feedback"]), 1)

        duplicate = self.client.post("/api/review/review-token/feedback", json=payload)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(len(self.store.rows["makaren_feedback"]), 1)

    def test_approval_is_idempotent_and_creates_one_delivery(self):
        first = self.client.post("/api/review/review-token/approve", json={"version": 1})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.store.rows["makaren_workflows"][0]["status"], "approved")
        self.assertEqual(len(self.store.rows["makaren_deliveries"]), 1)

        second = self.client.post("/api/review/review-token/approve", json={"version": 1})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(self.store.rows["makaren_deliveries"]), 1)

    def test_delivery_worker_claim_prevents_duplicate_email(self):
        workflow = self.store.rows["makaren_workflows"][0]
        workflow["status"] = "approved"
        self.store.insert(
            "makaren_deliveries",
            {
                "workflow_id": workflow["id"],
                "version_id": "version-1",
                "fulfillment_type": "digital",
                "status": "data_ready",
            },
        )
        with patch.object(app_module, "_send_profile_email", return_value=(True, None)) as send:
            app_module._deliver_approved_workflow(workflow["id"])
            app_module._deliver_approved_workflow(workflow["id"])
        self.assertEqual(send.call_count, 1)
        self.assertEqual(workflow["status"], "delivered")

    def test_framing_waits_until_digital_delivery(self):
        response = self.client.post(
            "/api/review/review-token/framing",
            json={"size": "A3", "frame_style": "木製"},
        )
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
