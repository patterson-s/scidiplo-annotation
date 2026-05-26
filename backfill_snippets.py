"""
backfill_snippets.py
────────────────────
One-time script: populate source_snippets on all Neon instruments from the
local SciDiploOntology SearchLog cache.

How it works
────────────
1. Reads every search_log row from the local PostgreSQL (results_json is a list
   of Serper result dicts: {title, link, snippet, ...}).
2. Builds a reverse index:  url → {title, snippet}
3. For each instrument in Neon, tries to match each source_url to the index.
4. Updates Neon with the assembled source_snippets dict.

Run:
    python backfill_snippets.py

Requires:
    LOCAL_DATABASE_URL  — local SciDiploOntology postgres (in .env or env var)
    DATABASE_URL        — Neon (read from .streamlit/secrets.toml or env var)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# ── Load .env from current dir, then sibling SciDiploOntology dir ────────────
def _load_dotenv(path: Path) -> None:
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

_load_dotenv(Path(__file__).parent / ".env")
# Fallback: sibling SciDiploOntology project (has DATABASE_URL + SOURCE_DATABASE_URL)
_load_dotenv(Path(__file__).parent.parent / "SciDiploOntology" / ".env")

# ── Also try loading from .streamlit/secrets.toml ────────────────────────────
_SECRETS_FILE = Path(__file__).parent / ".streamlit" / "secrets.toml"
if _SECRETS_FILE.exists():
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # pip install tomli
        except ImportError:
            tomllib = None
    if tomllib:
        secrets = tomllib.loads(_SECRETS_FILE.read_text(encoding="utf-8"))
        for k, v in secrets.items():
            os.environ.setdefault(k, str(v))


def _build_engine(url: str):
    from sqlalchemy import create_engine
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    connect_args: dict = {}
    for key in ("sslmode", "channel_binding", "connect_timeout"):
        if key in params:
            connect_args[key] = params.pop(key)[0]
    clean_query = urlencode({k: v[0] for k, v in params.items()})
    clean_url = urlunparse(parsed._replace(query=clean_query))
    if clean_url.startswith("postgresql://"):
        clean_url = "postgresql+psycopg2://" + clean_url[len("postgresql://"):]
    return create_engine(clean_url, pool_pre_ping=True, connect_args=connect_args)


def load_url_index(local_db_url: str) -> dict[str, dict]:
    """
    Query local SearchLog and build url → {title, snippet} reverse index.
    """
    from sqlalchemy import text
    engine = _build_engine(local_db_url)
    url_index: dict[str, dict] = {}
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT results_json FROM search_log"))
        for (results_json,) in rows:
            if not results_json:
                continue
            # results_json may be a string (JSON) or already a list
            if isinstance(results_json, str):
                try:
                    items = json.loads(results_json)
                except Exception:
                    continue
            else:
                items = results_json
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                url = item.get("link") or item.get("url", "")
                if url and url not in url_index:
                    url_index[url] = {
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                    }
    print(f"  URL index built: {len(url_index):,} unique URLs from SearchLog", flush=True)
    return url_index


def backfill(neon_db_url: str, url_index: dict[str, dict]) -> None:
    """
    For each Neon instrument, build source_snippets from url_index and UPDATE.
    """
    from sqlalchemy import text
    engine = _build_engine(neon_db_url)

    with engine.connect() as conn:
        rows = list(conn.execute(text(
            "SELECT name, source_urls FROM instruments ORDER BY name"
        )))

    print(f"  Found {len(rows):,} instruments in Neon to process")

    updated = 0
    no_match = 0

    with engine.begin() as conn:
        for (name, source_urls) in rows:
            if not source_urls:
                continue
            # source_urls may be stored as JSON string or list
            if isinstance(source_urls, str):
                try:
                    source_urls = json.loads(source_urls)
                except Exception:
                    continue
            if not isinstance(source_urls, list):
                continue

            snippets: dict[str, dict] = {}
            for url in source_urls:
                if url in url_index:
                    snippets[url] = url_index[url]

            if not snippets:
                no_match += 1
                continue

            conn.execute(
                text("""
                    UPDATE instruments
                    SET source_snippets = CAST(:snips AS jsonb)
                    WHERE name = :name
                      AND (source_snippets IS NULL OR source_snippets = CAST('{}' AS jsonb))
                """),
                {"snips": json.dumps(snippets, ensure_ascii=False), "name": name},
            )
            updated += 1

    print(f"  Updated: {updated:,} instruments with snippet data")
    print(f"  Skipped (no URL match in SearchLog): {no_match:,}")


def main() -> None:
    local_url = os.environ.get("LOCAL_DATABASE_URL") or os.environ.get("SOURCE_DATABASE_URL")
    neon_url  = os.environ.get("DATABASE_URL")

    if not local_url:
        print("ERROR: LOCAL_DATABASE_URL (or SOURCE_DATABASE_URL) not set.")
        print("  Set it in .env or as an env var pointing to the local SciDiploOntology postgres.")
        sys.exit(1)
    if not neon_url:
        print("ERROR: DATABASE_URL not set.")
        print("  Set it in .streamlit/secrets.toml or as an env var pointing to Neon.")
        sys.exit(1)

    print("Step 1: Building URL->snippet index from local SearchLog...")
    url_index = load_url_index(local_url)

    print("Step 2: Updating Neon instruments with snippet evidence...")
    backfill(neon_url, url_index)

    print("Backfill complete.")


if __name__ == "__main__":
    main()
