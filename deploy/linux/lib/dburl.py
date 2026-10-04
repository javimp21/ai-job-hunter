#!/usr/bin/env python3
"""Turn DATABASE_URL from the app's .env into libpq settings or provisioning SQL.

Never prints the password to a terminal by itself: `env` output is meant to be
eval'd by a script (PGPASSWORD stays out of argv), and `sql` output is meant to
be piped straight into `psql` on stdin. Stdlib only, so it runs under the
system python3 before Python 3.13 exists.
"""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def read_database_url(env_file: Path) -> str:
    for raw in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit(f"DATABASE_URL not found in {env_file}")


def parse(url: str) -> dict[str, str]:
    parts = urlsplit(url)
    if not parts.scheme.startswith("postgresql"):
        raise SystemExit("DATABASE_URL must be a postgresql:// URL")
    host = parts.hostname or "localhost"
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("DATABASE_URL must point at localhost: the server uses a native local PostgreSQL")
    user = unquote(parts.username or "")
    database = unquote(parts.path.lstrip("/"))
    if not IDENT.match(user) or not IDENT.match(database):
        raise SystemExit("DATABASE_URL user and database must match [A-Za-z_][A-Za-z0-9_]*")
    return {
        "host": host,
        "port": str(parts.port or 5432),
        "user": user,
        "password": unquote(parts.password or ""),
        "database": database,
    }


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in {"env", "sql", "names"}:
        print("usage: dburl.py {env|sql|names} /path/to/.env", file=sys.stderr)
        return 2
    cfg = parse(read_database_url(Path(argv[2])))
    if argv[1] == "env":
        for key, value in (
            ("PGHOST", cfg["host"]),
            ("PGPORT", cfg["port"]),
            ("PGUSER", cfg["user"]),
            ("PGPASSWORD", cfg["password"]),
            ("PGDATABASE", cfg["database"]),
        ):
            print(f"export {key}={shlex.quote(value)}")
    elif argv[1] == "names":
        print(cfg["user"], cfg["database"])
    else:
        user, database, password = cfg["user"], cfg["database"], cfg["password"]
        if not password:
            raise SystemExit("DATABASE_URL has no password; set one in .env")
        # Role and database are created if missing; the password is always synced.
        print(f"SELECT 'CREATE ROLE \"{user}\" LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = {literal(user)}) \\gexec")
        print(f"ALTER ROLE \"{user}\" WITH LOGIN PASSWORD {literal(password)};")
        print(f"SELECT 'CREATE DATABASE \"{database}\" OWNER \"{user}\"' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = {literal(database)}) \\gexec")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
