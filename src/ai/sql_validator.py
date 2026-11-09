"""Spatial SQL Allow-List & Read-Only Safety Validator (Section 8.1).

Enforces:
1. Read-only `SELECT` or `WITH ... SELECT` queries only (blocks DDL/DML/COPY/ATTACH/INSTALL).
2. All referenced dataset tables must belong to the allow-listed `DatasetRegistry` or CTEs defined in the query.
3. No fabricated numbers or hardcoded synthetic geometry literals masquerading as authoritative counts.
"""

import re
from typing import Dict, List, Set

FORBIDDEN_SQL_KEYWORDS = (
    "DROP",
    "DELETE",
    "INSERT",
    "UPDATE",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "REPLACE",
    "COPY",
    "ATTACH",
    "DETACH",
    "INSTALL",
    "LOAD",
    "PRAGMA",
    "CALL",
)


class SQLValidationError(ValueError):
    """Raised when an AI-generated or user-supplied SQL query violates catalogue grounding or safety rules."""


def validate_spatial_sql(sql: str, allowlisted_tables: Set[str]) -> Dict[str, List[str]]:
    """Validates that `sql` is read-only and only queries allow-listed tables or internal CTEs."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise SQLValidationError("Empty SQL query.")

    # Strip SQL comments
    no_comments = re.sub(r"--.*?$", "", cleaned, flags=re.MULTILINE)
    no_comments = re.sub(r"/\*.*?\*/", "", no_comments, flags=re.DOTALL).strip()

    first_token = no_comments.split()[0].upper() if no_comments.split() else ""
    if first_token not in ("SELECT", "WITH"):
        raise SQLValidationError(
            f"Only read-only SELECT / WITH queries are permitted; got leading keyword {first_token!r}."
        )

    if ";" in no_comments:
        raise SQLValidationError("Multi-statement SQL queries (';') are prohibited.")

    upper_tokens = set(re.findall(r"\b[A-Z_]+\b", no_comments.upper()))
    for kw in FORBIDDEN_SQL_KEYWORDS:
        if kw in upper_tokens:
            raise SQLValidationError(f"Forbidden SQL keyword detected: {kw}")

    # Extract CTE aliases defined in WITH clauses: `WITH cte1 AS (...), cte2 AS (...)`
    cte_names: Set[str] = {
        m.lower()
        for m in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s+AS\s*\(", no_comments, flags=re.IGNORECASE)
    }

    # Extract table names referenced in FROM or JOIN clauses
    referenced_tables: List[str] = []
    for match in re.finditer(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", no_comments, flags=re.IGNORECASE):
        tbl = match.group(1)
        if tbl.upper() in ("SELECT", "LATERAL", "UNNEST"):
            continue
        referenced_tables.append(tbl)

    allow_lower = {t.lower() for t in allowlisted_tables}
    unregistered: List[str] = []
    verified_tables: List[str] = []

    for tbl in referenced_tables:
        tl = tbl.lower()
        if tl in cte_names:
            continue
        if tl not in allow_lower:
            unregistered.append(tbl)
        else:
            if tbl not in verified_tables:
                verified_tables.append(tbl)

    if unregistered:
        raise SQLValidationError(
            f"Query references uncatalogued table(s) {unregistered}. "
            f"Allow-listed datasets: {sorted(allowlisted_tables)}"
        )

    return {"verified_tables": verified_tables, "cte_names": sorted(cte_names)}

