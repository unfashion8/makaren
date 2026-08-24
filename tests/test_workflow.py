import base64
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app as app_module
from art_direction import build_private_art_direction
from makaren_workflow import (
    SupabaseWorkflowStore,
    WorkflowStoreError,
    build_art_prompt,
    generate_artwork,
    generate_print_master,
    generate_review_token,
    hash_review_token,
)
from profile_generator import hide_internal_calculation_values
from prompts import build_profile_user_prompt


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

    def upload(self, path, content, mime_type):
        return path


class WorkflowHelpersTest(unittest.TestCase):
    def test_review_token_is_random_and_only_hash_is_stable(self):
        first = generate_review_token()
        second = generate_review_token()
        self.assertNotEqual(first, second)
        self.assertEqual(len(hash_review_token(first)), 64)
        self.assertEqual(hash_review_token(first), hash_review_token(first))

    def test_art_prompt_keeps_numbers_private_and_requires_painterly_surface(self):
        prompt = build_art_prompt("静けさと前進の両立", {"核数": 7, "魂数": 4, "使命数": 8})
        self.assertNotIn("Core number", prompt)
        self.assertNotIn("核数", prompt)
        self.assertNotIn("Jackson Pollock", prompt)
        self.assertIn("No text", prompt)
        self.assertIn("vertical 2:3", prompt)
        self.assertIn("absorption", prompt)
        self.assertIn("No infographic", prompt)
        self.assertIn("conceptually flat", prompt)
        self.assertIn("shallow impasto ridges", prompt)
        self.assertIn("FRAME-READINESS", prompt)
        self.assertIn("two to three metres", prompt)
        self.assertNotIn("Takashi Murakami", prompt)

    def test_private_art_scores_are_deterministic_and_not_in_prompt(self):
        first = build_private_art_direction("静けさと前進", {"核数": 7})
        second = build_private_art_direction("静けさと前進", {"核数": 7})
        self.assertEqual(first, second)
        self.assertIn("private_scores", first)
        prompt = build_art_prompt("静けさと前進", {"核数": 7})
        for value in first["private_scores"].values():
            self.assertNotIn(f"{value} / 100", prompt)

    def test_profile_prompt_hides_cycle_number_from_public_context(self):
        prompt = build_profile_user_prompt(
            "KIMURA",
            "KENJI",
            "1980/01/02",
            "",
            {"核数": "7"},
            [{"year": 2026, "personal_year": "8", "meaning": "成果"}],
        )
        self.assertIn("2026年: 成果", prompt)
        self.assertNotIn("パーソナルイヤー 8", prompt)
        self.assertIn("内部計算情報", prompt)

    def test_customer_text_sanitizer_removes_internal_values_and_art_scores(self):
        raw = """0. 構成数の概要
核数: 7、魂数は4です。
2026年はパーソナルイヤー 8です。
抽象度 83 / 100　明度 61 / 100
1. 核となる自己"""
        safe = hide_internal_calculation_values(raw)
        self.assertIn("パーソナル構造の概要", safe)
        self.assertNotIn("核数", safe)
        self.assertNotIn("魂数", safe)
        self.assertNotIn("83 / 100", safe)
        self.assertNotIn("パーソナルイヤー 8", safe)

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

    def test_review_art_uses_high_resolution_review_defaults(self):
        generated = SimpleNamespace(
            data=[SimpleNamespace(b64_json=base64.b64encode(b"review-art").decode())]
        )
        client = SimpleNamespace(images=SimpleNamespace(generate=MagicMock(return_value=generated)))
        with patch("makaren_workflow.pg.get_client", return_value=client), patch.dict(
            os.environ,
            {},
            clear=False,
        ):
            for key in ("KOKOROE_REVIEW_IMAGE_SIZE", "KOKOROE_REVIEW_IMAGE_QUALITY"):
                os.environ.pop(key, None)
            art, _prompt, mime, _model = generate_artwork("静けさ", {"核数": 7})
        self.assertEqual(art, b"review-art")
        self.assertEqual(mime, "image/png")
        kwargs = client.images.generate.call_args.kwargs
        self.assertEqual(kwargs["size"], "1536x2304")
        self.assertEqual(kwargs["quality"], "high")

    def test_print_master_preserves_art_with_high_resolution_edit(self):
        edited = SimpleNamespace(
            data=[SimpleNamespace(b64_json=base64.b64encode(b"print-master").decode())]
        )
        client = SimpleNamespace(images=SimpleNamespace(edit=MagicMock(return_value=edited)))
        with patch("makaren_workflow.pg.get_client", return_value=client):
            art, mime, _model = generate_print_master(b"approved-art")
        self.assertEqual(art, b"print-master")
        self.assertEqual(mime, "image/png")
        kwargs = client.images.edit.call_args.kwargs
        self.assertEqual(kwargs["size"], "2304x3456")
        self.assertEqual(kwargs["quality"], "high")
        self.assertIn("Preserve the approved composition", kwargs["prompt"])


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
        self.store.rows["makaren_workflow_versions"][0]["profile_text"] = "核数: 7\n1. 核となる自己"
        response = self.client.get("/review/review-token")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertNotIn(b"server-secret", response.data)
        self.assertNotIn("核数".encode(), response.data)

    def test_review_pdf_is_rebuilt_without_using_legacy_preview(self):
        response = self.client.get("/review/review-token/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("no-store", response.headers["Cache-Control"])

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

    def test_print_master_failure_does_not_block_digital_delivery(self):
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
        original_download = self.store.download

        def download(path):
            if path.endswith("art-print.png"):
                raise WorkflowStoreError("missing")
            return original_download(path)

        self.store.download = download
        with patch.object(app_module, "generate_print_master", side_effect=RuntimeError("image error")), patch.object(
            app_module, "_send_profile_email", return_value=(True, None)
        ):
            app_module._deliver_approved_workflow(workflow["id"])
        self.assertEqual(workflow["status"], "delivered")
        event_types = [row["event_type"] for row in self.store.rows["makaren_workflow_events"]]
        self.assertIn("print_master_failed", event_types)
        self.assertIn("digital_delivery_sent", event_types)

    def test_framing_waits_until_digital_delivery(self):
        response = self.client.post(
            "/api/review/review-token/framing",
            json={"size": "A3", "frame_style": "木製"},
        )
        self.assertEqual(response.status_code, 409)

    def test_delivered_review_shows_print_master_preview(self):
        workflow = self.store.rows["makaren_workflows"][0]
        workflow["status"] = "delivered"
        self.store.insert(
            "makaren_deliveries",
            {
                "workflow_id": workflow["id"],
                "version_id": "version-1",
                "fulfillment_type": "digital",
                "status": "delivered",
                "print_spec": {"master_path": "workflows/wf-1/v1/art-print.png"},
            },
        )
        response = self.client.get("/review/review-token")
        self.assertEqual(response.status_code, 200)
        self.assertIn("額装用プリントマスター".encode(), response.data)
        self.assertIn(b"art-print.png", response.data)

    def test_framing_preserves_print_master_path(self):
        workflow = self.store.rows["makaren_workflows"][0]
        workflow["status"] = "delivered"
        delivery = self.store.insert(
            "makaren_deliveries",
            {
                "workflow_id": workflow["id"],
                "version_id": "version-1",
                "fulfillment_type": "digital",
                "status": "delivered",
                "print_spec": {"master_path": "workflows/wf-1/v1/art-print.png"},
            },
        )
        response = self.client.post(
            "/api/review/review-token/framing",
            json={"size": "A2", "paper": "ファインアート紙", "frame_style": "木製"},
        )
        self.assertEqual(response.status_code, 200)
        saved = next(row for row in self.store.rows["makaren_deliveries"] if row["id"] == delivery["id"])
        self.assertEqual(saved["print_spec"]["master_path"], "workflows/wf-1/v1/art-print.png")
        self.assertEqual(saved["print_spec"]["size"], "A2")


if __name__ == "__main__":
    unittest.main()
