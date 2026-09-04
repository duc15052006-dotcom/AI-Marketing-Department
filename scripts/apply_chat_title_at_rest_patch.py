from __future__ import annotations

from pathlib import Path

EXPECTED_BLOB = "004bd93c7ddb9652714761d863d593f8f7df561c"
PATH = Path("chat/repository.py")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"guard failed: expected one occurrence, found {count}: {old[:80]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    import subprocess

    actual_blob = subprocess.check_output(["git", "hash-object", str(PATH)], text=True).strip()
    print(f"repository_blob={actual_blob}")
    if actual_blob != EXPECTED_BLOB:
        print("repository already moved; refusing to re-apply")
        raise SystemExit(3)

    text = PATH.read_text(encoding="utf-8")

    migration = '''    def _migrate_plaintext_session_titles(self, conn: sqlite3.Connection) -> None:
        """Atomically protect session titles left plaintext by at_rest_v1."""
        marker = conn.execute(
            "SELECT 1 FROM chat_payload_migrations WHERE migration_key = ?",
            ("title_at_rest_v1",),
        ).fetchone()
        if marker:
            return

        conn.execute("BEGIN IMMEDIATE")
        try:
            for row in conn.execute(
                "SELECT chat_id, title FROM chat_sessions"
            ).fetchall():
                conn.execute(
                    "UPDATE chat_sessions SET title = ? WHERE chat_id = ?",
                    (self._protect_text(row["title"]), row["chat_id"]),
                )

            conn.execute(
                "INSERT INTO chat_payload_migrations (migration_key, applied_at) VALUES (?, ?)",
                ("title_at_rest_v1", datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

'''

    text = replace_once(
        text,
        "    @contextmanager\n    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:\n",
        migration + "    @contextmanager\n    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:\n",
    )
    text = replace_once(
        text,
        "            self._migrate_v1_plaintext_payloads(conn)\n",
        "            self._migrate_v1_plaintext_payloads(conn)\n            self._migrate_plaintext_session_titles(conn)\n",
    )
    text = replace_once(text, "                    session.title,\n", "                    self._protect_text(session.title),\n")
    text = replace_once(text, "            params.append(title)\n", "            params.append(self._protect_text(title))\n")
    text = replace_once(text, "            title=row[\"title\"],\n", "            title=self._unprotect_text(row[\"title\"]) or \"\",\n")

    PATH.write_text(text, encoding="utf-8")
    subprocess.run(["git", "diff", "--check"], check=True)


if __name__ == "__main__":
    main()
