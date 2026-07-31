"""Guards the D1 schema against drifting from the report contract (#3).

The D1 store lives in ``worker/`` and is exercised by ``npm test`` over there,
which needs Node. These checks are the subset that must hold no matter what,
so they run in the Python suite — the required CI check — with no new
dependencies. They read the generated migration SQL as text, because the SQL
is what actually reaches the database.

Each assertion here mirrors a decision recorded in CLAUDE.md or on #3. If you
are changing the schema and one of these fails, the decision is what needs
revisiting first, not the test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "worker" / "migrations"


def _migration_sql() -> str:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        pytest.skip("no D1 migrations generated yet")
    return "\n".join(f.read_text() for f in files)


def test_migrations_exist() -> None:
    """A committed migration is the whole point — schema.ts alone changes nothing."""
    assert sorted(MIGRATIONS_DIR.glob("*.sql")), "run `npm run db:generate` in worker/"


def test_document_text_is_never_stored() -> None:
    """FlattenedDoc.text is 30-80 KB/doc; bulk text is R2's job (docs/data-storage.md).

    D1 keeps the sha256 and the length — that pair *is* the seam.
    """
    sql = _migration_sql()
    submissions = re.search(r"CREATE TABLE `submissions`.*?\n\);", sql, re.S)
    assert submissions, "submissions table missing from migrations"
    body = submissions.group(0)
    assert "`text_sha256`" in body
    assert "`text_length`" in body
    assert not re.search(r"^\s*`text`", body, re.M), (
        "submissions must not carry a `text` column — see schema.ts rule 3"
    )


def test_derived_counts_are_never_columns() -> None:
    """#3: tallies are derived from the ledger, never stored (models.py counts()).

    A view or a query can't drift from the ledger; a column can.
    """
    sql = _migration_sql()
    for name in ("passed", "failed", "scores", "errored"):
        assert not re.search(rf"^\s*`{name}`", sql, re.M), (
            f"`{name}` looks like a stored count column — counts are derived (#3)"
        )


def test_check_is_not_used_as_a_bare_column_name() -> None:
    """`check` is a SQL reserved word; the column is `check_name`."""
    sql = _migration_sql()
    assert not re.search(r"^\s*`check`\s", sql, re.M)
    assert "`check_name`" in sql


def test_result_kind_accompanies_every_result_column() -> None:
    """The bool-vs-number distinction is load-bearing and must be enforced by the DB.

    SQLite collapses booleans to 1/0, so a bare `result REAL` would let a score
    of 1.0 read back as a passing ``True`` — which ``EvidenceReport.counts()``
    and the renderer's lanes would both believe.
    """
    sql = _migration_sql()
    for table in ("finding_checks", "ledger_rows"):
        body = re.search(rf"CREATE TABLE `{table}`.*?\n\);", sql, re.S)
        assert body, f"{table} missing from migrations"
        assert "`result_kind`" in body.group(0)
        assert "`result_num`" in body.group(0)
        assert "IN ('bool','number')" in body.group(0), (
            f"{table}.result_kind must be constrained to the two known kinds"
        )


def test_status_vocabulary_matches_models_py() -> None:
    """CheckStatus = Literal["ok", "skipped", "errored"] — a gap is first-class."""
    from slopchecker.models import CheckStatus  # imported here to keep the guard self-contained

    sql = _migration_sql()
    for status in ("ok", "skipped", "errored"):
        assert f"'{status}'" in sql
    assert set(CheckStatus.__args__) == {"ok", "skipped", "errored"}, (
        "models.py CheckStatus changed — update the D1 CHECK constraints in "
        "worker/src/db/schema.ts and regenerate the migration"
    )


def test_verdict_vocabulary_matches_models_py() -> None:
    """Verdict is a closed enum; D1 must accept exactly the same members."""
    from slopchecker.models import Verdict

    sql = _migration_sql()
    for member in Verdict:
        assert f"'{member.value}'" in sql, (
            f"verdict '{member.value}' missing from the D1 CHECK constraint — "
            "regenerate worker/migrations after updating schema.ts"
        )


def test_no_case_expressions_in_migration_sql() -> None:
    """wrangler's migration splitter mis-parses `SUM(CASE ... END)`.

    It opens a compound-statement guard on CASE and only closes it on
    /\\sEND[;\\s]$/, which `END)` does not match — so the terminating semicolon
    is swallowed and the rest of the file merges into one statement. SQLite
    comparisons already yield 0/1, so SUM(<predicate>) does the same job.
    """
    assert not re.search(r"\bCASE\b", _migration_sql(), re.I), (
        "avoid CASE in migration SQL — see worker/src/routes/runs.ts countsFor()"
    )
