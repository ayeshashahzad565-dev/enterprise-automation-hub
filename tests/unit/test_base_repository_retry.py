"""Unit tests for ``BaseRepository._execute``'s transient-transport retry.

No existing test in this suite exercises ``BaseRepository._execute``
directly (every repository test uses a hand-written ``FakeXRepository``
that bypasses it entirely, per the TSD's Repository Layer testing
strategy) — this file adds narrow, direct coverage for the one new
behavior: a dropped HTTP/2 connection (``httpx.RemoteProtocolError``/
``ReadError``/etc.) mid-request is retried a bounded number of times
before falling back to the existing ``RepositoryError`` translation,
rather than failing on the first transient hiccup. Real network I/O is
never involved; ``.execute()`` is a controllable fake.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.database.exceptions import RepositoryError
from app.database.repositories.base_repository import BaseRepository

pytestmark = pytest.mark.unit


class _FakeBuilder:
    """A fake PostgREST query builder whose ``.execute()`` is scripted to
    raise a sequence of exceptions before (optionally) succeeding."""

    def __init__(self, effects: list[Exception | str]) -> None:
        self._effects = list(effects)
        self.call_count = 0

    def execute(self) -> str:
        self.call_count += 1
        effect = self._effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class _FakeRepository(BaseRepository[str]):
    table_name = "fake_table"


@pytest.fixture
def repository() -> _FakeRepository:
    # _execute never touches .table(), so a bare object() satisfies the
    # DatabaseClient protocol well enough for these tests.
    return _FakeRepository(client=object(), always_use_injected_client=True)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("app.utils.retry.time.sleep"):
        yield


class TestExecuteRetriesTransientTransportFailures:
    def test_succeeds_after_a_dropped_connection_is_retried(self, repository: _FakeRepository):
        builder = _FakeBuilder(
            [httpx.RemoteProtocolError("connection terminated"), "ok"]
        )

        result = repository._execute(builder, operation="paginate")

        assert result == "ok"
        assert builder.call_count == 2

    def test_retries_a_read_error_too(self, repository: _FakeRepository):
        builder = _FakeBuilder([httpx.ReadError("WinError 10035"), "ok"])

        result = repository._execute(builder, operation="paginate")

        assert result == "ok"
        assert builder.call_count == 2

    def test_raises_repository_error_once_retries_are_exhausted(self, repository: _FakeRepository):
        builder = _FakeBuilder(
            [
                httpx.RemoteProtocolError("connection terminated"),
                httpx.RemoteProtocolError("connection terminated"),
                httpx.RemoteProtocolError("connection terminated"),
            ]
        )

        with pytest.raises(RepositoryError):
            repository._execute(builder, operation="paginate")

        assert builder.call_count == 3

    def test_a_non_transient_exception_is_never_retried(self, repository: _FakeRepository):
        builder = _FakeBuilder([RuntimeError("not a transport error")])

        with pytest.raises(RepositoryError):
            repository._execute(builder, operation="paginate")

        assert builder.call_count == 1
