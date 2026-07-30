"""Unit tests for ``BaseRepository``'s per-request tenant-scoped client
resolution — the mechanism behind the tenant-isolation architecture (see
docs/tenant_isolation.md).

Covers, in order:
1. The ``always_use_injected_client`` branch (always ignores any bound
   tenant client).
2. The opposite branch's fallback-when-unset and use-when-set behavior.
3. The actual FastAPI concurrency reasoning this whole mechanism depends
   on: a value set on the request's own event-loop task, before a
   sync/threadpooled dispatch, is visible inside that dispatch — proven
   against the real ``anyio.to_thread.run_sync`` Starlette uses, not
   assumed.
"""

from __future__ import annotations

import asyncio

import anyio
import pytest

from app.database.client import DatabaseClient
from app.database.repositories.base_repository import (
    BaseRepository,
    _current_tenant_client,
    bind_current_tenant_client,
    reset_current_tenant_client,
)

pytestmark = pytest.mark.unit


class _StubClient:
    """A minimal, distinguishable stand-in satisfying enough of
    ``DatabaseClient`` for identity comparison in these tests."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"_StubClient({self.name!r})"


class _FakeRepository(BaseRepository[str]):
    table_name = "fake_table"


@pytest.fixture(autouse=True)
def _clean_contextvar():
    """Guarantee no test leaks a bound client into another, regardless of
    how it exits."""
    assert _current_tenant_client.get() is None
    yield
    _current_tenant_client.set(None)


class TestAlwaysUseInjectedClient:
    def test_ignores_a_bound_tenant_client(self) -> None:
        default = _StubClient("default")
        tenant = _StubClient("tenant")
        repo = _FakeRepository(client=default, always_use_injected_client=True)  # type: ignore[arg-type]
        token = bind_current_tenant_client(tenant)  # type: ignore[arg-type]
        try:
            assert repo._client is default
        finally:
            reset_current_tenant_client(token)

    def test_uses_the_injected_client_when_nothing_is_bound(self) -> None:
        default = _StubClient("default")
        repo = _FakeRepository(client=default, always_use_injected_client=True)  # type: ignore[arg-type]
        assert repo._client is default


class TestTenantScopedResolution:
    def test_falls_back_to_the_default_client_when_nothing_is_bound(self) -> None:
        default = _StubClient("default")
        repo = _FakeRepository(client=default, always_use_injected_client=False)  # type: ignore[arg-type]
        assert repo._client is default

    def test_uses_the_bound_tenant_client_when_one_is_set(self) -> None:
        default = _StubClient("default")
        tenant = _StubClient("tenant")
        repo = _FakeRepository(client=default, always_use_injected_client=False)  # type: ignore[arg-type]
        token = bind_current_tenant_client(tenant)  # type: ignore[arg-type]
        try:
            assert repo._client is tenant
        finally:
            reset_current_tenant_client(token)

    def test_reverts_to_the_default_client_after_reset(self) -> None:
        default = _StubClient("default")
        tenant = _StubClient("tenant")
        repo = _FakeRepository(client=default, always_use_injected_client=False)  # type: ignore[arg-type]
        token = bind_current_tenant_client(tenant)  # type: ignore[arg-type]
        reset_current_tenant_client(token)
        assert repo._client is default

    def test_two_repository_instances_see_the_same_bound_client(self) -> None:
        """The ContextVar is global, not per-instance — every repository
        constructed with always_use_injected_client=False shares whatever
        client the current request bound, exactly as every one of them
        will in a real request."""
        tenant = _StubClient("tenant")
        repo_a = _FakeRepository(client=_StubClient("a"), always_use_injected_client=False)  # type: ignore[arg-type]
        repo_b = _FakeRepository(client=_StubClient("b"), always_use_injected_client=False)  # type: ignore[arg-type]
        token = bind_current_tenant_client(tenant)  # type: ignore[arg-type]
        try:
            assert repo_a._client is tenant
            assert repo_b._client is tenant
        finally:
            reset_current_tenant_client(token)


class TestConcurrencyAcrossThreadpoolDispatch:
    """Proves the reasoning behind why ``bind_tenant_database_client``
    (``app.api.dependencies``) must be an async generator dependency, not
    a sync one — using the real ``anyio.to_thread.run_sync`` FastAPI/
    Starlette dispatches sync dependencies and sync endpoint functions
    through, not a hand-rolled simulation of it.
    """

    def test_a_value_set_before_a_threadpool_dispatch_is_visible_inside_it(self) -> None:
        tenant = _StubClient("tenant")

        async def scenario() -> DatabaseClient | None:
            token = bind_current_tenant_client(tenant)  # type: ignore[arg-type]
            try:
                # This is exactly the mechanism Starlette's run_in_threadpool
                # uses to dispatch a sync `def` dependency/endpoint: the
                # current context is copied and the target runs inside that
                # copy in a worker thread.
                return await anyio.to_thread.run_sync(_current_tenant_client.get)
            finally:
                reset_current_tenant_client(token)

        result = asyncio.run(scenario())
        assert result is tenant

    def test_a_set_made_inside_a_threadpool_dispatch_does_not_escape_it(self) -> None:
        """The other half of the reasoning: had the bind happened *inside*
        a threadpooled call instead of before it, the set would be
        invisible once control returns to the main task — this is
        precisely why ``bind_tenant_database_client`` cannot be a plain
        sync `def` dependency."""
        tenant = _StubClient("tenant")

        def _bind_inside_thread() -> None:
            bind_current_tenant_client(tenant)  # type: ignore[arg-type]

        async def scenario() -> DatabaseClient | None:
            await anyio.to_thread.run_sync(_bind_inside_thread)
            return _current_tenant_client.get()

        result = asyncio.run(scenario())
        assert result is None
