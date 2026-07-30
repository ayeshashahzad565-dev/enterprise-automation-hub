"""Tests for the ``/api/v1/requests/{id}/attachments`` and
``/api/v1/attachments/{id}*`` routes.

See ``test_api_requests.py``'s module docstring — same real-service,
fake-repository wiring via the ``env`` fixture.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.routers.attachments import _UPLOAD_READ_CHUNK_BYTES, _read_upload_bounded
from app.auth.authentication import AuthenticatedIdentity
from app.auth.exceptions import InvalidTokenError
from app.bootstrap import ApplicationResources
from app.config.security import MAX_ATTACHMENT_SIZE_BYTES
from app.services.exceptions import ValidationError
from tests.conftest import Env
from tests.fixtures.factories import specific_user_stage

pytestmark = pytest.mark.unit

_TOKEN = "test-token"


class _FakeTokenVerifier:
    def __init__(self, identity: AuthenticatedIdentity) -> None:
        self._identity = identity

    def resolve_claims(self, token: str) -> Mapping[str, Any]:
        if token != _TOKEN:
            raise InvalidTokenError("Unknown test token.")
        return {
            "sub": str(self._identity.user_id),
            "email": self._identity.email,
            "role": self._identity.role.value,
            "company_id": str(self._identity.company_id),
            "is_platform_admin": self._identity.is_platform_admin,
        }


def _build_client(env: Env, identity: AuthenticatedIdentity) -> TestClient:
    def _factory() -> ApplicationResources:
        return MagicMock(
            spec=ApplicationResources,
            request_service=env.request_service,
            comment_service=env.comment_service,
            attachment_service=env.attachment_service,
            token_verifier=_FakeTokenVerifier(identity),
            scheduler_stats=None,
        )

    app: FastAPI = create_app(resources_factory=_factory)
    client = TestClient(app)
    client.__enter__()  # runs the lifespan startup, so app.state.resources is populated
    client.headers.update({"Authorization": f"Bearer {_TOKEN}"})
    return client


def _create_request(env: Env, employee_identity, approver_id, admin_identity) -> dict[str, Any]:
    created = env.workflow_definition_service.create_definition(
        admin_identity,
        request_type="expense_reimbursement",
        definition={"stages": [specific_user_stage(1, "Manager Review", user_id=approver_id)]},
    )
    env.workflow_definition_service.activate_version(admin_identity, created.id)
    client = _build_client(env, employee_identity)
    return client.post(
        "/api/v1/requests", json={"request_type": "expense_reimbursement", "title": "Team lunch"}
    ).json()["data"]


class TestUploadListDownloadRemove:
    def test_upload_then_list_then_download_then_remove(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        request = _create_request(env, employee_identity, approver_profile.id, admin_identity)
        client = _build_client(env, employee_identity)

        upload_response = client.post(
            f"/api/v1/requests/{request['id']}/attachments",
            files={"file": ("receipt.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert upload_response.status_code == 201
        attachment = upload_response.json()["data"]
        assert attachment["file_name"] == "receipt.pdf"
        assert attachment["version"] == 1

        list_response = client.get(f"/api/v1/requests/{request['id']}/attachments")
        assert list_response.status_code == 200
        assert len(list_response.json()["data"]) == 1

        download_response = client.get(f"/api/v1/attachments/{attachment['id']}/download")
        assert download_response.status_code == 200
        assert "url" in download_response.json()["data"]

        remove_response = client.delete(f"/api/v1/attachments/{attachment['id']}")
        assert remove_response.status_code == 204

    def test_replace_attachment_increments_version(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        request = _create_request(env, employee_identity, approver_profile.id, admin_identity)
        client = _build_client(env, employee_identity)
        original = client.post(
            f"/api/v1/requests/{request['id']}/attachments",
            files={"file": ("receipt.pdf", b"%PDF-1.4 fake", "application/pdf")},
        ).json()["data"]

        response = client.put(
            f"/api/v1/attachments/{original['id']}",
            files={"file": ("receipt-v2.pdf", b"%PDF-1.4 fake v2", "application/pdf")},
        )

        assert response.status_code == 200
        replacement = response.json()["data"]
        assert replacement["version"] == 2
        assert replacement["replaces_attachment_id"] == original["id"]

    def test_disallowed_content_type_returns_invalid_file_type(
        self, env, employee, approver, admin
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        request = _create_request(env, employee_identity, approver_profile.id, admin_identity)
        client = _build_client(env, employee_identity)

        response = client.post(
            f"/api/v1/requests/{request['id']}/attachments",
            files={"file": ("virus.exe", b"MZfake", "application/x-msdownload")},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_FILE_TYPE"

    def test_empty_file_returns_empty_file_code(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        request = _create_request(env, employee_identity, approver_profile.id, admin_identity)
        client = _build_client(env, employee_identity)

        response = client.post(
            f"/api/v1/requests/{request['id']}/attachments",
            files={"file": ("empty.txt", b"", "text/plain")},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "EMPTY_FILE"

    def test_oversized_file_returns_file_too_large(self, env, employee, approver, admin):
        _, employee_identity = employee
        approver_profile, _ = approver
        _, admin_identity = admin
        request = _create_request(env, employee_identity, approver_profile.id, admin_identity)
        client = _build_client(env, employee_identity)
        oversized_content = bytes(MAX_ATTACHMENT_SIZE_BYTES + 1)

        response = client.post(
            f"/api/v1/requests/{request['id']}/attachments",
            files={"file": ("big.txt", oversized_content, "text/plain")},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


class _ChunkedStream:
    """A minimal ``UploadFile``-like stream serving fixed-size chunks.

    Counts how many chunks were actually consumed, so a test can prove
    ``_read_upload_bounded`` aborts as soon as the running total exceeds
    the limit, rather than reading the entire (here, effectively
    unbounded) stream first.
    """

    def __init__(self, *, chunk_size: int, chunk_count: int) -> None:
        self._chunk = b"a" * chunk_size
        self._remaining = chunk_count
        self.reads = 0

    async def read(self, size: int) -> bytes:
        self.reads += 1
        if self._remaining <= 0:
            return b""
        self._remaining -= 1
        return self._chunk


class TestReadUploadBounded:
    def test_aborts_before_consuming_the_entire_stream(self):
        # 10 chunks of `_UPLOAD_READ_CHUNK_BYTES` each — well beyond
        # MAX_ATTACHMENT_SIZE_BYTES after just a couple of reads, proving
        # the abort happens early rather than after buffering everything.
        stream = _ChunkedStream(chunk_size=_UPLOAD_READ_CHUNK_BYTES, chunk_count=10)

        with pytest.raises(ValidationError, match="exceeds the maximum"):
            asyncio.run(
                _read_upload_bounded(stream, max_size_bytes=_UPLOAD_READ_CHUNK_BYTES)  # type: ignore[arg-type]
            )

        assert stream.reads < 10

    def test_returns_full_content_when_within_the_limit(self):
        stream = _ChunkedStream(chunk_size=_UPLOAD_READ_CHUNK_BYTES, chunk_count=2)

        content = asyncio.run(
            _read_upload_bounded(stream, max_size_bytes=_UPLOAD_READ_CHUNK_BYTES * 3)  # type: ignore[arg-type]
        )

        assert len(content) == _UPLOAD_READ_CHUNK_BYTES * 2
