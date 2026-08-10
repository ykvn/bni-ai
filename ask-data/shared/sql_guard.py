"""
Shared SQL sanitization and security guardrail helpers.

Consolidates the repeated SQL markdown-stripping and read-only
validation logic used by both the MCP server and CrewAI service.
"""
from __future__ import annotations

import re

# Destructive SQL keywords that must never reach the database
FORBIDDEN_KEYWORDS = [
    "insert", "update", "delete", "drop", "alter", "truncate",
    "create", "merge", "overwrite", "grant", "revoke",
]


def sanitize_sql(query: str) -> str:
    """
    Cleans a raw SQL string by stripping markdown code fences and
    leading 'sql' language tags.
    """
    query = re.sub(r"^```(?:sql)?\s*|^sql\s*", "", query.strip(), flags=re.IGNORECASE)
    query = re.sub(r"```$", "", query).strip()
    return query


def strip_sql_comments(query: str) -> str:
    """
    Removes SQL line comments (--) and block comments (/* */) from a query.
    """
    clean = re.sub(r"--.*$", "", query, flags=re.MULTILINE)
    clean = re.sub(r"/\*.*?\*/", "", clean, flags=re.DOTALL).strip()
    return clean.rstrip(";").strip()


def has_forbidden_keyword(query: str) -> bool:
    """Returns True if the query contains any destructive SQL keyword."""
    query_lower = query.lower()
    return any(re.search(rf"\b{kw}\b", query_lower) for kw in FORBIDDEN_KEYWORDS)


def is_read_only_query(query: str) -> bool:
    """
    Validates that a query is read-only (starts with SELECT or WITH)
    and contains no destructive keywords.
    """
    clean = strip_sql_comments(query)
    clean_lower = clean.lower()
    is_read_only_start = clean_lower.startswith("select") or clean_lower.startswith("with")
    return not has_forbidden_keyword(clean) and is_read_only_start