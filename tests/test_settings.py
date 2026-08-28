"""Tests for Settings' ALLOWED_TELEGRAM_IDS / ADMIN_TELEGRAM_IDS parsing.

Regression coverage for a real bug: pydantic-settings JSON-decodes a
bare-numeric env var (a single ID with no comma, e.g. "123456789") into an
int before the field validator runs, while a comma-separated value survives
as a str - the validator must handle both, not just str/list.
"""

from __future__ import annotations

from app.config.settings import Settings


def test_database_url_normalizes_bare_postgres_scheme_to_asyncpg(monkeypatch):
    """Regression: Railway's own Postgres plugin hands out a plain
    postgres:// DATABASE_URL. Wiring that straight through (the simplest,
    least error-prone setup) used to leave SQLAlchemy falling back to the
    sync psycopg2 dialect inside our async engine - confusing failure, only
    caught by actually deploying. The scheme must be normalized regardless
    of which of the two common bare prefixes a provider uses.
    """
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@host.railway.internal:5432/railway")
    settings = Settings()
    assert settings.database_url == "postgresql+asyncpg://user:pass@host.railway.internal:5432/railway"


def test_database_url_normalizes_plain_postgresql_scheme_to_asyncpg(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/db")
    settings = Settings()
    assert settings.database_url == "postgresql+asyncpg://user:pass@host:5432/db"


def test_database_url_already_using_asyncpg_is_left_unchanged(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@host:5432/db")
    settings = Settings()
    assert settings.database_url == "postgresql+asyncpg://user:pass@host:5432/db"


def test_single_id_env_var_parses_as_one_element_list(monkeypatch):
    monkeypatch.setenv("ALLOWED_TELEGRAM_IDS", "8458085494")
    settings = Settings()
    assert settings.allowed_telegram_ids == [8458085494]
    assert settings.is_allowed(8458085494) is True


def test_comma_separated_ids_env_var_parses_as_list(monkeypatch):
    monkeypatch.setenv("ALLOWED_TELEGRAM_IDS", "111111111,222222222")
    settings = Settings()
    assert settings.allowed_telegram_ids == [111111111, 222222222]


def test_empty_ids_env_var_parses_as_empty_list_and_fails_closed(monkeypatch):
    monkeypatch.setenv("ALLOWED_TELEGRAM_IDS", "")
    settings = Settings()
    assert settings.allowed_telegram_ids == []
    assert settings.is_allowed(8458085494) is False


def test_unset_ids_env_var_defaults_to_empty_list(monkeypatch):
    monkeypatch.delenv("ALLOWED_TELEGRAM_IDS", raising=False)
    # Bypass the project's real .env file (which has real IDs configured for
    # deployment) so this test exercises the true "nothing configured" case.
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.allowed_telegram_ids == []


def test_ids_list_passed_directly_is_accepted():
    settings = Settings(allowed_telegram_ids=[111, 222])
    assert settings.allowed_telegram_ids == [111, 222]


def test_admin_id_matching_allowed_id_grants_admin(monkeypatch):
    monkeypatch.setenv("ALLOWED_TELEGRAM_IDS", "8458085494")
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", "8458085494")
    settings = Settings()
    assert settings.is_admin(8458085494) is True
    assert settings.is_admin(999) is False
