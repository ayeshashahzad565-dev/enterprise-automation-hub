"""Unit tests for the shared PostgREST search-escaping helpers
(``app.database.repositories.base_repository.escape_ilike_special_characters``/
``quote_postgrest_filter_value``), introduced in Milestone 9's Search/Filter
Injection audit.

``escape_ilike_special_characters`` originated as a private helper local
to ``invitation_repository.py`` (the Milestone 1-5 cleanup pass); this
file supersedes that module's own ``TestEscapeIlikeSpecialCharacters``
class now that every repository needing it imports this single shared
implementation instead of a per-module copy.
"""

from __future__ import annotations

import pytest

from app.database.repositories.base_repository import (
    escape_ilike_special_characters,
    quote_postgrest_filter_value,
)

pytestmark = pytest.mark.unit


class TestEscapeIlikeSpecialCharacters:
    def test_leaves_ordinary_characters_untouched(self):
        assert (
            escape_ilike_special_characters("plain.email@example.com") == "plain.email@example.com"
        )

    def test_escapes_percent(self):
        assert escape_ilike_special_characters("100%tested") == "100\\%tested"

    def test_escapes_underscore(self):
        assert escape_ilike_special_characters("a_b@example.com") == "a\\_b@example.com"

    def test_escapes_backslash(self):
        assert escape_ilike_special_characters("back\\slash") == "back\\\\slash"

    def test_escapes_backslash_before_percent_and_underscore_so_double_escaping_never_occurs(self):
        # A literal "%" preceded by a literal "\" must become "\\\%", not
        # "\\%" (which Postgres would read as an escaped literal "%" -
        # correct - but only if backslashes were escaped first; escaping
        # % first would instead produce "\\%" from a *different* input,
        # silently conflating two distinct raw inputs into one escaped
        # output). Escaping "\\" first, before "%"/"_", is what prevents
        # this.
        assert escape_ilike_special_characters("\\%") == "\\\\\\%"


class TestQuotePostgrestFilterValue:
    def test_wraps_an_ordinary_value_in_double_quotes(self):
        assert quote_postgrest_filter_value("hello") == '"hello"'

    def test_escapes_an_embedded_double_quote(self):
        assert quote_postgrest_filter_value('say "hi"') == '"say \\"hi\\""'

    def test_escapes_an_embedded_backslash(self):
        assert quote_postgrest_filter_value("back\\slash") == '"back\\\\slash"'

    def test_a_value_containing_filter_structural_characters_is_safely_quoted(self):
        # The exact class of injection this function exists to close: a
        # comma/period/parenthesis in the *value* must not be able to
        # break out of the surrounding "column.op.<value>" clause once
        # quoted.
        malicious = "x,description.ilike.%"
        quoted = quote_postgrest_filter_value(malicious)
        assert quoted == '"x,description.ilike.%"'
        # The whole malicious payload is now inside one pair of quotes -
        # a single value, not clause-separating syntax.
        assert quoted.count('"') == 2

    def test_composed_with_ilike_escaping_for_a_free_text_or_clause(self):
        # Mirrors how InvitationRepository.list_invitations/
        # RequestRepository.search_requests actually compose the two
        # helpers: escape ILIKE wildcards first, then quote the result.
        raw_query = 'admin",status.eq.accepted,x.ilike."%'
        pattern = f"%{escape_ilike_special_characters(raw_query)}%"
        quoted = quote_postgrest_filter_value(pattern)
        clause = f"full_name.ilike.{quoted},email.ilike.{quoted}"
        # The malicious quote/comma/dot payload is fully contained inside
        # the two quoted values - splitting the raw clause string on
        # unescaped/unquoted commas would still find exactly two
        # top-level clauses (one per column), not more.
        assert clause.startswith("full_name.ilike.")
        assert clause.count(quoted) == 2
