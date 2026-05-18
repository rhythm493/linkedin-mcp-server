"""Tests for export tools: export_to_db, run_sql, list_tables."""

import os
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.tools import FunctionTool
from typing import cast

from linkedin_mcp_server.tools.export import (
    ExportResult,
    SqlResult,
    ListTablesResult,
    _resolve_db_path,
    _params_hash,
    _check_cache,
    _update_cache,
    _normalize_saved_jobs,
    _normalize_recommendations,
    _normalize_search_jobs,
    _normalize_sections,
    _normalize_company_people,
    _normalize_pending_invitations,
    register_export_tools,
)


def _make_mock_locator() -> MagicMock:
    """Create a fully mockable Playwright locator."""
    loc = MagicMock()
    loc.count = AsyncMock(return_value=0)
    loc.inner_text = AsyncMock(return_value="")
    loc.is_visible = AsyncMock(return_value=True)
    loc.first = loc
    loc.nth = MagicMock(return_value=loc)
    return loc


def _setup_mock_extractor(result: dict) -> MagicMock:
    """Create a mock extractor with async methods returning the given result."""
    mock = MagicMock()
    mock.scrape_person = AsyncMock(return_value=result)
    mock.search_jobs = AsyncMock(return_value=result)
    mock.scrape_job = AsyncMock(return_value=result)
    mock.get_my_profile = AsyncMock(return_value=result)
    mock.scrape_company = AsyncMock(return_value=result)
    mock.extract_feed = AsyncMock(return_value=result)
    mock.get_inbox = AsyncMock(return_value=result)
    mock.get_conversation = AsyncMock(return_value=result)
    mock.search_companies = AsyncMock(return_value=result)
    mock.get_company_employees = AsyncMock(return_value=result)
    mock.page = MagicMock()
    mock.page.goto = AsyncMock()
    mock.page.url = "https://www.linkedin.com/"
    mock.page.locator = MagicMock(side_effect=lambda selector: _make_mock_locator())
    return mock


async def _get_tool_fn(mcp: FastMCP, name: str):
    """Extract tool function from FastMCP by name."""
    tool = await mcp.get_tool(name)
    if tool is None:
        raise ValueError(f"Tool '{name}' not found")
    return cast(FunctionTool, tool).fn


class TestResolveDbPath:
    def test_resolves_relative_to_cwd(self):
        result = _resolve_db_path("my.db")
        assert result == os.path.join(os.getcwd(), "my.db")

    def test_resolves_nested_path(self):
        result = _resolve_db_path("data/linkedin.db")
        expected = os.path.normpath(os.path.join(os.getcwd(), "data/linkedin.db"))
        assert result == expected

    def test_accepts_absolute_path(self, monkeypatch):
        monkeypatch.setattr("os.getcwd", lambda: "/home/user/project")
        result = _resolve_db_path("/tmp/other.db")
        assert result == "/tmp/other.db"


class TestParamsHash:
    def test_deterministic(self):
        a = _params_hash({"a": 1, "b": 2})
        b = _params_hash({"b": 2, "a": 1})
        assert a == b

    def test_different_values(self):
        a = _params_hash({"a": 1})
        b = _params_hash({"a": 2})
        assert a != b


class TestCacheHelpers:
    def test_cache_roundtrip(self, tmp_path):
        db = tmp_path / "test.db"
        with sqlite3.connect(str(db)) as conn:
            # Create target table so cache is considered valid
            conn.execute("CREATE TABLE saved_jobs (title TEXT)")
            conn.commit()
            _update_cache(conn, "get_saved_jobs", {}, "saved_jobs", 10)
            cached = _check_cache(conn, "get_saved_jobs", {}, "saved_jobs")
            assert cached is not None
            assert cached["row_count"] == 10
            assert cached["fetched_at"] is not None

    def test_cache_miss(self, tmp_path):
        db = tmp_path / "test.db"
        with sqlite3.connect(str(db)) as conn:
            result = _check_cache(conn, "get_saved_jobs", {}, "saved_jobs")
            assert result is None

    def test_cache_returns_none_if_table_deleted(self, tmp_path):
        db = tmp_path / "test.db"
        with sqlite3.connect(str(db)) as conn:
            # Create the target table so cache entry is valid
            conn.execute("CREATE TABLE saved_jobs (title TEXT)")
            conn.commit()
            _update_cache(conn, "get_saved_jobs", {}, "saved_jobs", 5)

        with sqlite3.connect(str(db)) as conn:
            conn.execute("DROP TABLE saved_jobs")
            conn.commit()
            cached = _check_cache(conn, "get_saved_jobs", {}, "saved_jobs")
            assert cached is None


class TestNormalizers:
    def test_normalize_saved_jobs(self):
        result = {
            "jobs": [
                {"title": "SWE", "company": "Google", "location": "Remote"},
                {"title": "MLE", "company": "Meta", "location": "NYC"},
            ],
            "sections": {},
            "url": "https://example.com",
        }
        rows = _normalize_saved_jobs(result)
        assert len(rows) == 2
        assert rows[0]["title"] == "SWE"
        assert rows[0]["company"] == "Google"
        assert "_exported_at" in rows[0]

    def test_normalize_saved_jobs_empty(self):
        result = {"jobs": [], "sections": {}, "url": "https://example.com"}
        rows = _normalize_saved_jobs(result)
        assert rows == []

    def test_normalize_recommendations(self):
        result = {
            "jobs": [
                {"title": "Dev", "company": "Acme", "job_url": "https://example.com/1"},
            ],
            "sections": {},
            "url": "https://example.com",
        }
        rows = _normalize_recommendations(result)
        assert len(rows) == 1
        assert rows[0]["title"] == "Dev"

    def test_normalize_search_jobs(self):
        result = {
            "job_ids": ["123", "456"],
            "sections": {},
            "url": "https://example.com",
        }
        rows = _normalize_search_jobs(result)
        assert len(rows) == 2
        assert rows[0]["job_id"] == "123"

    def test_normalize_sections(self):
        result = {
            "sections": {"about": "text1", "experience": "text2"},
            "url": "https://example.com",
        }
        rows = _normalize_sections(result, "get_person_profile")
        assert len(rows) == 2
        assert rows[0]["section_name"] == "about"
        assert rows[0]["tool"] == "get_person_profile"

    def test_normalize_company_people(self):
        result = {
            "people": [
                {"name": "Alice", "headline": "Eng", "location": "NYC"},
            ],
            "sections": {},
            "url": "https://example.com",
        }
        rows = _normalize_company_people(result)
        assert len(rows) == 1
        assert rows[0]["name"] == "Alice"

    def test_normalize_pending_invitations(self):
        result = {
            "invitations": [
                {
                    "name": "Bob",
                    "headline": "CEO",
                    "profile_url": "https://example.com/bob",
                },
            ],
            "sections": {},
            "url": "https://example.com",
        }
        rows = _normalize_pending_invitations(result)
        assert len(rows) == 1
        assert rows[0]["from_name"] == "Bob"


class TestExportToolRegistration:
    def test_export_tools_registered(self):
        mcp = FastMCP("test")
        register_export_tools(mcp)
        # Tools are registered, verify they exist
        assert mcp is not None

    async def test_all_export_tools_exist(self):
        mcp = FastMCP("test")
        register_export_tools(mcp)
        expected = ["export_to_db", "run_sql", "list_tables"]
        for name in expected:
            tool = await mcp.get_tool(name)
            assert tool is not None, f"Tool '{name}' not registered"


class TestRunSqlTool:
    async def test_select_query(self, tmp_path):
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            db = "test.db"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE people (name TEXT, age INTEGER)")
                conn.execute("INSERT INTO people VALUES ('Alice', 30)")
                conn.commit()

            mcp = FastMCP("test")
            register_export_tools(mcp)
            tool_fn = await _get_tool_fn(mcp, "run_sql")
            result = await tool_fn(db_path=db, sql="SELECT * FROM people")

            assert isinstance(result, SqlResult)
            assert result.row_count == 1
            assert result.rows[0]["name"] == "Alice"
            assert result.columns == ["name", "age"]
        finally:
            os.chdir(orig_cwd)

    async def test_insert_query(self, tmp_path):
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            db = "test.db"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE people (name TEXT, age INTEGER)")
                conn.commit()

            mcp = FastMCP("test")
            register_export_tools(mcp)
            tool_fn = await _get_tool_fn(mcp, "run_sql")
            result = await tool_fn(
                db_path=db,
                sql="INSERT INTO people VALUES (?, ?)",
                params=["Bob", 25],
            )

            assert isinstance(result, SqlResult)
            assert result.rows == []
            assert result.affected_rows == 1
        finally:
            os.chdir(orig_cwd)

    async def test_parameterized_query(self, tmp_path):
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            db = "test.db"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE jobs (id TEXT, title TEXT)")
                conn.execute("INSERT INTO jobs VALUES ('1', 'SWE')")
                conn.commit()

            mcp = FastMCP("test")
            register_export_tools(mcp)
            tool_fn = await _get_tool_fn(mcp, "run_sql")
            result = await tool_fn(
                db_path=db,
                sql="SELECT title FROM jobs WHERE id = ?",
                params=["1"],
            )

            assert result.row_count == 1
            assert result.rows[0]["title"] == "SWE"
        finally:
            os.chdir(orig_cwd)

    async def test_attach_query(self, tmp_path):
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            db1 = "db1.db"
            db2 = "db2.db"
            with sqlite3.connect(db1) as conn:
                conn.execute("CREATE TABLE a (x INTEGER)")
                conn.execute("INSERT INTO a VALUES (1)")
                conn.commit()
            with sqlite3.connect(db2) as conn:
                conn.execute("CREATE TABLE b (y INTEGER)")
                conn.execute("INSERT INTO b VALUES (2)")
                conn.commit()

            mcp = FastMCP("test")
            register_export_tools(mcp)
            tool_fn = await _get_tool_fn(mcp, "run_sql")
            result = await tool_fn(
                db_path=db1,
                sql=f"ATTACH '{db2}' AS other; SELECT x, y FROM a, other.b",
            )

            assert result.row_count == 1
            assert result.rows[0]["x"] == 1
            assert result.rows[0]["y"] == 2
        finally:
            os.chdir(orig_cwd)


class TestListTablesTool:
    async def test_list_tables(self, tmp_path):
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            db = "test.db"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
                conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT)")
                conn.commit()

            mcp = FastMCP("test")
            register_export_tools(mcp)
            tool_fn = await _get_tool_fn(mcp, "list_tables")
            result = await tool_fn(db_path=db)

            assert isinstance(result, ListTablesResult)
            names = [t.name for t in result.tables]
            assert "users" in names
            assert "jobs" in names
            assert "_cache" not in names
        finally:
            os.chdir(orig_cwd)

    async def test_list_tables_with_columns(self, tmp_path):
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            db = "test.db"
            with sqlite3.connect(db) as conn:
                conn.execute(
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
                )
                conn.commit()

            mcp = FastMCP("test")
            register_export_tools(mcp)
            tool_fn = await _get_tool_fn(mcp, "list_tables")
            result = await tool_fn(db_path=db)

            users_table = [t for t in result.tables if t.name == "users"][0]
            assert len(users_table.columns) == 2
            assert users_table.columns[0].name == "id"
            assert users_table.columns[0].pk == 1
            assert users_table.columns[1].name == "name"
            assert users_table.columns[1].notnull == 1
        finally:
            os.chdir(orig_cwd)


class TestExportToDbToolCacheHit:
    async def test_cache_hit_returns_without_scraping(self, tmp_path):
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            db = "test.db"

            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE saved_jobs (title TEXT, company TEXT)")
                conn.execute("INSERT INTO saved_jobs VALUES ('SWE', 'Google')")
                conn.commit()
                _update_cache(conn, "get_saved_jobs", {}, "saved_jobs", 1)

            mcp = FastMCP("test")
            register_export_tools(mcp)
            tool_fn = await _get_tool_fn(mcp, "export_to_db")

            result = await tool_fn(
                tool_name="get_saved_jobs",
                db_path=db,
                table_name="saved_jobs",
                tool_params={},
                refresh=False,
            )

            assert isinstance(result, ExportResult)
            assert result.source == "cache"
            assert result.rows_saved == 1
            assert result.table == "saved_jobs"
        finally:
            os.chdir(orig_cwd)


class TestExportToDbIntegration:
    async def test_full_export_flow(self, tmp_path, mock_context):
        """End-to-end: mock extractor → export_to_db → verify DB."""
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            db = "test.db"
            mock_extractor = _setup_mock_extractor(
                {
                    "sections": {
                        "about": "TestCorp builds things",
                        "jobs": "We are hiring",
                    },
                    "url": "https://www.linkedin.com/company/testcorp/",
                }
            )

            monkeypatch = pytest.MonkeyPatch()
            monkeypatch.setattr(
                "linkedin_mcp_server.dependencies.get_ready_extractor",
                AsyncMock(return_value=mock_extractor),
            )

            mcp = FastMCP("test")
            register_export_tools(mcp)
            tool_fn = await _get_tool_fn(mcp, "export_to_db")

            result = await tool_fn(
                tool_name="get_company_profile",
                tool_params={"company_slug": "testcorp"},
                db_path=db,
                table_name="company_profiles",
                refresh=True,
                ctx=mock_context,
            )

            assert isinstance(result, ExportResult)
            assert result.source == "linkedin"
            assert result.rows_saved == 2
            assert result.table == "company_profiles"

            with sqlite3.connect(db) as conn:
                rows = conn.execute("SELECT * FROM company_profiles").fetchall()
                assert len(rows) == 2

            monkeypatch.undo()
        finally:
            os.chdir(orig_cwd)

    async def test_export_saved_jobs(self, tmp_path, mock_context):
        """Test exporting structured job data with multi-page support."""
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            db = "test.db"

            mock_extractor = MagicMock()

            def saved_jobs_side_effect(limit: int, page: int):
                if page == 1:
                    return {
                        "jobs": [
                            {
                                "title": "SWE",
                                "company": "Google",
                                "location": "Remote",
                                "posting_date": "1d ago",
                                "job_id": "123",
                                "job_url": "https://www.linkedin.com/jobs/view/123/",
                            },
                            {
                                "title": "MLE",
                                "company": "Meta",
                                "location": "NYC",
                                "posting_date": "2d ago",
                                "job_id": "456",
                                "job_url": "https://www.linkedin.com/jobs/view/456/",
                            },
                        ],
                        "page": 1,
                        "has_next": False,
                        "next_cursor": None,
                        "partial": False,
                        "warnings": None,
                    }
                return {
                    "jobs": [],
                    "page": page,
                    "has_next": False,
                    "next_cursor": None,
                }

            mock_extractor.get_saved_jobs = AsyncMock(
                side_effect=saved_jobs_side_effect
            )
            mock_extractor.page = MagicMock()
            mock_extractor.page.goto = AsyncMock()

            monkeypatch = pytest.MonkeyPatch()
            monkeypatch.setattr(
                "linkedin_mcp_server.dependencies.get_ready_extractor",
                AsyncMock(return_value=mock_extractor),
            )

            mcp = FastMCP("test")
            register_export_tools(mcp)
            tool_fn = await _get_tool_fn(mcp, "export_to_db")

            result = await tool_fn(
                tool_name="get_saved_jobs",
                tool_params={},
                db_path=db,
                table_name="saved_jobs",
                refresh=True,
                ctx=mock_context,
            )

            assert result.source == "linkedin"
            assert result.rows_saved == 2
            assert "title" in result.columns
            assert "company" in result.columns

            with sqlite3.connect(db) as conn:
                rows = conn.execute("SELECT title, company FROM saved_jobs").fetchall()
                assert rows[0] == ("SWE", "Google")
                assert rows[1] == ("MLE", "Meta")

            monkeypatch.undo()
        finally:
            os.chdir(orig_cwd)

    async def test_export_saved_jobs_multipage(self, tmp_path, mock_context):
        """Test that multi-page saved jobs export accumulates all results."""
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            db = "test.db"

            mock_extractor = MagicMock()
            call_count = 0

            def saved_jobs_side_effect(limit: int, page: int):
                nonlocal call_count
                call_count += 1
                if page == 1:
                    return {
                        "jobs": [
                            {
                                "title": "Job1",
                                "company": "A",
                                "location": "X",
                                "job_id": "1",
                                "job_url": "https://www.linkedin.com/jobs/view/1/",
                            },
                        ],
                        "page": 1,
                        "has_next": True,
                        "next_cursor": "cursor2",
                    }
                if page == 2:
                    return {
                        "jobs": [
                            {
                                "title": "Job2",
                                "company": "B",
                                "location": "Y",
                                "job_id": "2",
                                "job_url": "https://www.linkedin.com/jobs/view/2/",
                            },
                        ],
                        "page": 2,
                        "has_next": True,
                        "next_cursor": "cursor3",
                    }
                return {
                    "jobs": [
                        {
                            "title": "Job3",
                            "company": "C",
                            "location": "Z",
                            "job_id": "3",
                            "job_url": "https://www.linkedin.com/jobs/view/3/",
                        },
                    ],
                    "page": 3,
                    "has_next": False,
                    "next_cursor": None,
                }

            mock_extractor.get_saved_jobs = AsyncMock(
                side_effect=saved_jobs_side_effect
            )
            mock_extractor.page = MagicMock()

            monkeypatch = pytest.MonkeyPatch()
            monkeypatch.setattr(
                "linkedin_mcp_server.dependencies.get_ready_extractor",
                AsyncMock(return_value=mock_extractor),
            )

            mcp = FastMCP("test")
            register_export_tools(mcp)
            tool_fn = await _get_tool_fn(mcp, "export_to_db")

            result = await tool_fn(
                tool_name="get_saved_jobs",
                tool_params={},
                db_path=db,
                table_name="all_saved_jobs",
                refresh=True,
                ctx=mock_context,
            )

            assert result.source == "linkedin"
            assert result.rows_saved == 3
            assert call_count == 3

            with sqlite3.connect(db) as conn:
                rows = conn.execute(
                    "SELECT title, company FROM all_saved_jobs"
                ).fetchall()
                assert len(rows) == 3

            monkeypatch.undo()
        finally:
            os.chdir(orig_cwd)

    async def test_export_search_jobs(self, tmp_path, mock_context):
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            db = "test.db"
            mock_extractor = _setup_mock_extractor(
                {
                    "job_ids": ["123", "456", "789"],
                    "sections": {"search_results": "Job 1\nJob 2\nJob 3"},
                    "url": "https://www.linkedin.com/jobs/search/",
                }
            )

            monkeypatch = pytest.MonkeyPatch()
            monkeypatch.setattr(
                "linkedin_mcp_server.dependencies.get_ready_extractor",
                AsyncMock(return_value=mock_extractor),
            )

            mcp = FastMCP("test")
            register_export_tools(mcp)
            tool_fn = await _get_tool_fn(mcp, "export_to_db")

            result = await tool_fn(
                tool_name="search_jobs",
                tool_params={"keywords": "python"},
                db_path=db,
                table_name="search_results",
                refresh=True,
                ctx=mock_context,
            )

            assert result.source == "linkedin"
            assert result.rows_saved == 3
            assert "job_id" in result.columns

            monkeypatch.undo()
        finally:
            os.chdir(orig_cwd)

    async def test_invalid_tool_name_raises(self):
        mcp = FastMCP("test")
        register_export_tools(mcp)
        tool_fn = await _get_tool_fn(mcp, "export_to_db")

        with pytest.raises(ValueError, match="Unknown tool_name"):
            await tool_fn(
                tool_name="nonexistent_tool",
                tool_params={},
                db_path="test.db",
                table_name="test",
                refresh=True,
            )


class TestExportToolsInServer:
    async def test_export_tools_registered_in_full_server(self):
        from linkedin_mcp_server.server import create_mcp_server

        mcp = create_mcp_server()
        for name in ["export_to_db", "run_sql", "list_tables"]:
            tool = await mcp.get_tool(name)
            assert tool is not None, f"Tool '{name}' not registered in server"
