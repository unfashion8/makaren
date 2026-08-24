# -*- coding: utf-8 -*-
"""Supabase-backed review workflow and artwork generation helpers.

The service-role key is used only from the Flask server. Browser clients receive
short-lived signed Storage URLs and never receive Supabase credentials.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

import profile_generator as pg
from art_direction import build_studio_prompt


WORKFLOW_TABLES = {
    "makaren_readings",
    "makaren_workflows",
    "makaren_feedback",
    "makaren_workflow_versions",
    "makaren_deliveries",
    "makaren_workflow_events",
}


class WorkflowStoreError(RuntimeError):
    """Raised when the Supabase REST or Storage API rejects a request."""


def workflow_config_error() -> str | None:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url and not key:
        return "SUPABASE_URL と SUPABASE_SERVICE_ROLE_KEY が未設定です"
    if not url:
        return "SUPABASE_URL が未設定です"
    if not key:
        return "SUPABASE_SERVICE_ROLE_KEY が未設定です"
    return None


def workflow_enabled() -> bool:
    return workflow_config_error() is None


def generate_review_token() -> str:
    return secrets.token_urlsafe(32)


def hash_review_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _quoted_storage_path(path: str) -> str:
    return "/".join(quote(part, safe="") for part in path.strip("/").split("/"))


@dataclass
class SupabaseWorkflowStore:
    url: str
    service_key: str
    bucket: str = "makaren-deliverables"
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "SupabaseWorkflowStore":
        error = workflow_config_error()
        if error:
            raise WorkflowStoreError(error)
        return cls(
            url=os.environ["SUPABASE_URL"].strip().rstrip("/"),
            service_key=os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip(),
            bucket=(
                os.getenv("KOKOROE_STORAGE_BUCKET", "").strip()
                or os.getenv("MAKAREN_STORAGE_BUCKET", "").strip()
                or "makaren-deliverables"
            ),
            timeout_seconds=float(os.getenv("SUPABASE_TIMEOUT_SECONDS", "30")),
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str | int] | None = None,
        json_body: Any | None = None,
        raw_body: bytes | None = None,
        headers: dict[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        target = f"{self.url}{path}"
        if query:
            target = f"{target}?{urlencode(query)}"
        request_headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Accept": "application/json",
        }
        request_headers.update(headers or {})
        body = raw_body
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        req = Request(target, data=body, headers=request_headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout_seconds) as response:
                payload = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1200]
            raise WorkflowStoreError(
                f"Supabase API error {exc.code} ({method} {path}): {detail}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise WorkflowStoreError(f"Supabase API connection error ({method} {path}): {exc}") from exc
        if not expect_json:
            return payload
        if not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkflowStoreError(f"Supabase API returned invalid JSON ({method} {path})") from exc

    def select(
        self,
        table: str,
        *,
        filters: dict[str, str] | None = None,
        columns: str = "*",
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        if table not in WORKFLOW_TABLES:
            raise ValueError(f"Unsupported table: {table}")
        query: dict[str, str | int] = {"select": columns}
        query.update(filters or {})
        if order:
            query["order"] = order
        if limit is not None:
            query["limit"] = max(1, min(int(limit), 1000))
        result = self._request("GET", f"/rest/v1/{table}", query=query)
        return result if isinstance(result, list) else []

    def select_one(
        self,
        table: str,
        *,
        filters: dict[str, str],
        columns: str = "*",
    ) -> dict | None:
        rows = self.select(table, filters=filters, columns=columns, limit=1)
        return rows[0] if rows else None

    def insert(self, table: str, row: dict) -> dict:
        if table not in WORKFLOW_TABLES:
            raise ValueError(f"Unsupported table: {table}")
        result = self._request(
            "POST",
            f"/rest/v1/{table}",
            json_body=row,
            headers={"Prefer": "return=representation"},
        )
        if not isinstance(result, list) or not result:
            raise WorkflowStoreError(f"Supabase insert returned no row: {table}")
        return result[0]

    def update(self, table: str, values: dict, *, filters: dict[str, str]) -> list[dict]:
        if table not in WORKFLOW_TABLES:
            raise ValueError(f"Unsupported table: {table}")
        result = self._request(
            "PATCH",
            f"/rest/v1/{table}",
            query=filters,
            json_body=values,
            headers={"Prefer": "return=representation"},
        )
        return result if isinstance(result, list) else []

    def upload(self, path: str, content: bytes, mime_type: str) -> str:
        quoted_path = _quoted_storage_path(path)
        self._request(
            "POST",
            f"/storage/v1/object/{quote(self.bucket, safe='')}/{quoted_path}",
            raw_body=content,
            headers={"Content-Type": mime_type, "x-upsert": "false"},
            expect_json=True,
        )
        return path

    def download(self, path: str) -> bytes:
        quoted_path = _quoted_storage_path(path)
        return self._request(
            "GET",
            f"/storage/v1/object/authenticated/{quote(self.bucket, safe='')}/{quoted_path}",
            expect_json=False,
        )

    def signed_url(self, path: str, expires_in: int = 600) -> str:
        quoted_path = _quoted_storage_path(path)
        result = self._request(
            "POST",
            f"/storage/v1/object/sign/{quote(self.bucket, safe='')}/{quoted_path}",
            json_body={"expiresIn": max(60, min(int(expires_in), 3600))},
        )
        signed = (result or {}).get("signedURL") or (result or {}).get("signedUrl")
        if not signed:
            raise WorkflowStoreError("Supabase Storage did not return a signed URL")
        if str(signed).startswith("http"):
            return str(signed)
        return urljoin(f"{self.url}/storage/v1/", str(signed).lstrip("/"))


def get_workflow_store() -> SupabaseWorkflowStore:
    return SupabaseWorkflowStore.from_env()


def build_art_prompt(
    profile_text: str,
    numbers: dict,
    *,
    previous_prompt: str | None = None,
    revision_instruction: str | None = None,
) -> str:
    """Create a deterministic studio prompt while keeping calculations private."""
    return build_studio_prompt(
        profile_text,
        numbers,
        previous_prompt=previous_prompt,
        revision_instruction=revision_instruction,
    )


def generate_artwork(
    profile_text: str,
    numbers: dict,
    *,
    previous_prompt: str | None = None,
    revision_instruction: str | None = None,
) -> tuple[bytes, str, str, str]:
    """Generate a PNG artwork and return bytes, prompt, MIME type and model."""
    prompt = build_art_prompt(
        profile_text,
        numbers,
        previous_prompt=previous_prompt,
        revision_instruction=revision_instruction,
    )
    model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2").strip() or "gpt-image-2"
    size = os.getenv("KOKOROE_REVIEW_IMAGE_SIZE", "1536x2304").strip() or "1536x2304"
    quality = os.getenv("KOKOROE_REVIEW_IMAGE_QUALITY", "high").strip() or "high"
    result = pg.get_client().images.generate(
        model=model,
        prompt=prompt,
        size=size,
        quality=quality,
        output_format="png",
        response_format="b64_json",
    )
    encoded = result.data[0].b64_json if result.data else None
    if not encoded:
        raise RuntimeError("OpenAI Images API returned no image data")
    return base64.b64decode(encoded), prompt, "image/png", model


def generate_print_master(approved_art_bytes: bytes) -> tuple[bytes, str, str]:
    """Enhance an approved composition into a high-resolution print master."""
    if not approved_art_bytes:
        raise ValueError("Approved artwork is empty")

    model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2").strip() or "gpt-image-2"
    size = os.getenv("KOKOROE_PRINT_IMAGE_SIZE", "2304x3456").strip() or "2304x3456"
    quality = os.getenv("KOKOROE_PRINT_IMAGE_QUALITY", "high").strip() or "high"
    source = io.BytesIO(approved_art_bytes)
    source.name = "approved-art.png"
    prompt = """Create a museum-grade print master from this approved vertical abstract painting.

PRESERVE EXACTLY
- Preserve the approved composition, crop, 2:3 proportions, palette, tonal structure, negative space, gesture placement, and every distinctive mark.
- This is a faithful high-resolution refinement of the same artwork, not a reinterpretation and not a new variation.

REFINE ONLY
- Increase pigment microtexture, shallow relief, edge fidelity, subtle cast shadows within the paint surface, translucent-layer separation, matte-versus-gloss variation, and fine tonal transitions.
- Make the surface rewarding at close viewing while the composition remains strong from two to three metres away.
- Maintain printable separation in dark passages and saturated colours. Keep a quiet five-percent crop-safe perimeter without adding a border.

DO NOT ADD
- No new forms, symbols, objects, text, numerals, signature, logo, frame, mat, wall, room, border, mockup, digital glow, CGI depth, or photographic environment.
- Do not smooth away physical irregularity. The result must remain a straight-on, full-bleed documentation of the same materially convincing painting."""
    result = pg.get_client().images.edit(
        model=model,
        image=source,
        prompt=prompt,
        size=size,
        quality=quality,
        output_format="png",
        response_format="b64_json",
    )
    encoded = result.data[0].b64_json if result.data else None
    if not encoded:
        raise RuntimeError("OpenAI Images API returned no print-master data")
    return base64.b64decode(encoded), "image/png", model
