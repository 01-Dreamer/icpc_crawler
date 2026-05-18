import base64
import binascii
import json
import sqlite3
import threading
from datetime import datetime, timezone

from .config import DATABASE_FILE


_DB_LOCK = threading.RLock()


def _connect():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database():
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _DB_LOCK, _connect() as conn:
        _create_schema(conn)
        _migrate_contest_results_schema(conn)
        _prune_orphaned_rows(conn)


def _create_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            codeforces TEXT NOT NULL DEFAULT '',
            atcoder TEXT NOT NULL DEFAULT '',
            nowcoder TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ratings (
            user_id TEXT PRIMARY KEY,
            codeforces INTEGER NOT NULL DEFAULT 0,
            atcoder INTEGER NOT NULL DEFAULT 0,
            nowcoder INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS pending (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            codeforces TEXT NOT NULL DEFAULT '',
            atcoder TEXT NOT NULL DEFAULT '',
            nowcoder TEXT NOT NULL DEFAULT '',
            time TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS contests (
            id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            contest_id TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            time TEXT NOT NULL DEFAULT '',
            link TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL,
            extra TEXT NOT NULL DEFAULT '{}',
            UNIQUE(platform, contest_id)
        );

        CREATE TABLE IF NOT EXISTS contest_results (
            contest_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            ac_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (contest_id, user_id),
            FOREIGN KEY (contest_id) REFERENCES contests(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_contest_results_user_id
            ON contest_results(user_id);

        CREATE TABLE IF NOT EXISTS upcoming (
            id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            contest_id TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            time TEXT NOT NULL DEFAULT '',
            link TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL,
            extra TEXT NOT NULL DEFAULT '{}'
        );
        """
    )


def _migrate_contest_results_schema(conn):
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(contest_results)").fetchall()
    }
    if "participated" not in columns or "ac_count" in columns:
        return

    conn.executescript(
        """
        ALTER TABLE contest_results RENAME TO contest_results_old;

        CREATE TABLE contest_results (
            contest_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            ac_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (contest_id, user_id),
            FOREIGN KEY (contest_id) REFERENCES contests(id) ON DELETE CASCADE
        );

        INSERT INTO contest_results (contest_id, user_id, ac_count)
        SELECT contest_id, user_id, CASE WHEN participated THEN 1 ELSE 0 END
        FROM contest_results_old;

        DROP TABLE contest_results_old;

        CREATE INDEX IF NOT EXISTS idx_contest_results_user_id
            ON contest_results(user_id);
        """
    )


def _prune_orphaned_rows(conn):
    conn.executescript(
        """
        DELETE FROM ratings
        WHERE user_id NOT IN (SELECT id FROM users);

        DELETE FROM contest_results
        WHERE user_id NOT IN (SELECT id FROM users);

        DELETE FROM contest_results
        WHERE contest_id NOT IN (SELECT id FROM contests);
        """
    )


def _extra_payload(item, known_keys):
    return json.dumps(
        {k: v for k, v in item.items() if k not in known_keys},
        ensure_ascii=False,
    )


def _load_extra(row):
    try:
        extra = json.loads(row["extra"] or "{}")
        return extra if isinstance(extra, dict) else {}
    except Exception:
        return {}


def list_users():
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, codeforces, atcoder, nowcoder
            FROM users
            ORDER BY sort_order, rowid
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_user(user_id):
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT id, name, codeforces, atcoder, nowcoder
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def add_user(user):
    users = list_users()
    users.append(user)
    save_users(users)


def update_user(user_id, data):
    with _DB_LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return False

        conn.execute(
            """
            UPDATE users
            SET name = ?, codeforces = ?, atcoder = ?, nowcoder = ?
            WHERE id = ?
            """,
            (
                data.get("name", row["name"]),
                data.get("codeforces", row["codeforces"]) or "",
                data.get("atcoder", row["atcoder"]) or "",
                data.get("nowcoder", row["nowcoder"]) or "",
                user_id,
            ),
        )
    return True


def delete_user(user_id):
    with _DB_LOCK, _connect() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM ratings WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM contest_results WHERE user_id = ?", (user_id,))


def move_user(user_id, direction):
    users = list_users()
    idx = next((i for i, user in enumerate(users) if user.get("id") == user_id), -1)
    if idx == -1:
        return False

    if direction == "up" and idx > 0:
        users[idx], users[idx - 1] = users[idx - 1], users[idx]
    elif direction == "down" and idx < len(users) - 1:
        users[idx], users[idx + 1] = users[idx + 1], users[idx]

    save_users(users)
    return True


def save_users(users):
    with _DB_LOCK, _connect() as conn:
        _replace_users(conn, users)


def _replace_users(conn, users):
    conn.execute("DELETE FROM users")
    for order, user in enumerate(users):
        conn.execute(
            """
            INSERT OR REPLACE INTO users
            (id, name, codeforces, atcoder, nowcoder, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user.get("id"),
                user.get("name", ""),
                user.get("codeforces", "") or "",
                user.get("atcoder", "") or "",
                user.get("nowcoder", "") or "",
                order,
            ),
        )


def list_ratings():
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT user_id, codeforces, atcoder, nowcoder FROM ratings"
        ).fetchall()
    return {
        row["user_id"]: {
            "codeforces": row["codeforces"],
            "atcoder": row["atcoder"],
            "nowcoder": row["nowcoder"],
        }
        for row in rows
    }


def get_user_rating(user_id):
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT codeforces, atcoder, nowcoder
            FROM ratings
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    if not row:
        return {"codeforces": 0, "atcoder": 0, "nowcoder": 0}
    return dict(row)


def save_ratings(ratings):
    with _DB_LOCK, _connect() as conn:
        _replace_ratings(conn, ratings)


def save_user_rating(user_id, rating):
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO ratings
            (user_id, codeforces, atcoder, nowcoder)
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                int(rating.get("codeforces", 0) or 0),
                int(rating.get("atcoder", 0) or 0),
                int(rating.get("nowcoder", 0) or 0),
            ),
        )


def _replace_ratings(conn, ratings):
    conn.execute("DELETE FROM ratings")
    for user_id, rating in ratings.items():
        conn.execute(
            """
            INSERT OR REPLACE INTO ratings
            (user_id, codeforces, atcoder, nowcoder)
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                int(rating.get("codeforces", 0) or 0),
                int(rating.get("atcoder", 0) or 0),
                int(rating.get("nowcoder", 0) or 0),
            ),
        )


def list_pending():
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, codeforces, atcoder, nowcoder, time
            FROM pending
            ORDER BY sort_order, rowid
            """
        ).fetchall()
    return [dict(row) for row in rows]


def add_pending(item):
    pending = list_pending()
    pending.append(item)
    save_pending(pending)


def get_pending(req_id):
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT id, name, codeforces, atcoder, nowcoder, time
            FROM pending
            WHERE id = ?
            """,
            (req_id,),
        ).fetchone()
    return dict(row) if row else None


def delete_pending(req_id):
    with _DB_LOCK, _connect() as conn:
        conn.execute("DELETE FROM pending WHERE id = ?", (req_id,))


def save_pending(pending):
    with _DB_LOCK, _connect() as conn:
        _replace_pending(conn, pending)


def _replace_pending(conn, pending):
    conn.execute("DELETE FROM pending")
    for order, item in enumerate(pending):
        conn.execute(
            """
            INSERT OR REPLACE INTO pending
            (id, name, codeforces, atcoder, nowcoder, time, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("id"),
                item.get("name", ""),
                item.get("codeforces", "") or "",
                item.get("atcoder", "") or "",
                item.get("nowcoder", "") or "",
                item.get("time", "") or "",
                order,
            ),
        )


def list_contest_keys():
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT platform, contest_id
            FROM contests
            ORDER BY sort_order, rowid
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _contest_time_value(time_str):
    if not time_str:
        return None

    normalized = str(time_str).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(normalized, fmt)
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            pass
    return None


def _contest_sort_key(row):
    time_value = _contest_time_value(row["time"])
    time_bucket = 0 if time_value is not None else 1
    sort_time = -time_value if time_value is not None else 0
    return (
        time_bucket,
        sort_time,
        int(row["sort_order"]),
        int(row["db_rowid"]),
    )


def _encode_contest_cursor(row):
    time_bucket, sort_time, sort_order, rowid = _contest_sort_key(row)
    payload = {
        "time_bucket": time_bucket,
        "sort_time": sort_time,
        "sort_order": sort_order,
        "rowid": rowid,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_contest_cursor(cursor):
    if not cursor:
        return None
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        return (
            int(payload["time_bucket"]),
            int(payload["sort_time"]),
            int(payload["sort_order"]),
            int(payload["rowid"]),
        )
    except (binascii.Error, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def list_contests():
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, platform, contest_id, name, time, link, extra
            FROM contests
            ORDER BY sort_order, rowid
            """
        ).fetchall()

        contest_ids = [row["id"] for row in rows]
        if contest_ids:
            placeholders = ",".join("?" for _ in contest_ids)
            result_rows = conn.execute(
                f"""
                SELECT contest_id, user_id, ac_count
                FROM contest_results
                WHERE contest_id IN ({placeholders})
                """,
                contest_ids,
            ).fetchall()
        else:
            result_rows = []

    results_by_contest = {}
    for result in result_rows:
        results_by_contest.setdefault(result["contest_id"], {})[result["user_id"]] = result[
            "ac_count"
        ]

    contests = []
    for row in rows:
        contest = {
            "id": row["id"],
            "platform": row["platform"],
            "contest_id": row["contest_id"],
            "name": row["name"],
            "time": row["time"],
            "link": row["link"],
            "results": results_by_contest.get(row["id"], {}),
        }
        contest.update(_load_extra(row))
        contests.append(contest)
    return contests


def list_contests_page(page_size=20, cursor=None):
    page_size = min(max(int(page_size or 20), 1), 100)
    cursor_data = _decode_contest_cursor(cursor)

    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT rowid AS db_rowid, id, platform, contest_id, name, time, link,
                   sort_order, extra
            FROM contests
            """,
        ).fetchall()

        sorted_rows = sorted(rows, key=_contest_sort_key)
        if cursor_data:
            sorted_rows = [
                row for row in sorted_rows
                if _contest_sort_key(row) > cursor_data
            ]

        page_rows = sorted_rows[:page_size]
        contest_ids = [row["id"] for row in page_rows]
        if contest_ids:
            placeholders = ",".join("?" for _ in contest_ids)
            result_rows = conn.execute(
                f"""
                SELECT contest_id, user_id, ac_count
                FROM contest_results
                WHERE contest_id IN ({placeholders})
                """,
                contest_ids,
            ).fetchall()
        else:
            result_rows = []

    results_by_contest = {}
    for result in result_rows:
        results_by_contest.setdefault(result["contest_id"], {})[result["user_id"]] = result[
            "ac_count"
        ]

    contests = []
    for row in page_rows:
        contest = {
            "id": row["id"],
            "platform": row["platform"],
            "contest_id": row["contest_id"],
            "name": row["name"],
            "time": row["time"],
            "link": row["link"],
            "results": results_by_contest.get(row["id"], {}),
        }
        contest.update(_load_extra(row))
        contests.append(contest)

    has_next = len(sorted_rows) > page_size
    next_cursor = _encode_contest_cursor(page_rows[-1]) if has_next and page_rows else ""
    return {
        "items": contests,
        "next_cursor": next_cursor,
        "has_next": has_next,
    }


def get_contest(contest_uuid):
    contests = list_contests()
    return next((contest for contest in contests if contest.get("id") == contest_uuid), None)


def contest_exists(platform, contest_id):
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM contests
            WHERE lower(platform) = lower(?) AND contest_id = ?
            """,
            (platform, str(contest_id)),
        ).fetchone()
    return row is not None


def add_contest(contest):
    contests = list_contests()
    contests.append(contest)
    save_contests(contests)


def delete_contest(contest_uuid):
    with _DB_LOCK, _connect() as conn:
        conn.execute("DELETE FROM contests WHERE id = ?", (contest_uuid,))


def save_contests(contests):
    with _DB_LOCK, _connect() as conn:
        _replace_contests(conn, contests)


def save_contest_results(contest_uuid, results):
    with _DB_LOCK, _connect() as conn:
        conn.execute("DELETE FROM contest_results WHERE contest_id = ?", (contest_uuid,))
        for user_id, ac_count in results.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO contest_results
                (contest_id, user_id, ac_count)
                VALUES (?, ?, ?)
                """,
                (contest_uuid, user_id, int(ac_count or 0)),
            )


def _replace_contests(conn, contests):
    conn.execute("DELETE FROM contest_results")
    conn.execute("DELETE FROM contests")
    known_keys = {"id", "platform", "contest_id", "name", "description", "time", "link", "results"}
    for order, contest in enumerate(contests):
        name = contest.get("name") or contest.get("description") or ""
        conn.execute(
            """
            INSERT OR REPLACE INTO contests
            (id, platform, contest_id, name, time, link, sort_order, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contest.get("id"),
                contest.get("platform", ""),
                str(contest.get("contest_id", "")),
                name,
                contest.get("time", "") or "",
                contest.get("link", "") or "",
                order,
                _extra_payload(contest, known_keys),
            ),
        )
        for user_id, ac_count in (contest.get("results") or {}).items():
            conn.execute(
                """
                INSERT OR REPLACE INTO contest_results
                (contest_id, user_id, ac_count)
                VALUES (?, ?, ?)
                """,
                (contest.get("id"), user_id, int(ac_count or 0)),
            )


def list_upcoming():
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, platform, contest_id, name, time, link, extra
            FROM upcoming
            ORDER BY sort_order, rowid
            """
        ).fetchall()

    upcoming = []
    for row in rows:
        item = {
            "id": row["id"],
            "platform": row["platform"],
            "contest_id": row["contest_id"],
            "name": row["name"],
            "time": row["time"],
            "link": row["link"],
        }
        item.update(_load_extra(row))
        upcoming.append(item)
    return upcoming


def save_upcoming(upcoming):
    with _DB_LOCK, _connect() as conn:
        _replace_upcoming(conn, upcoming)


def _replace_upcoming(conn, upcoming):
    conn.execute("DELETE FROM upcoming")
    known_keys = {"id", "platform", "contest_id", "name", "time", "link"}
    for order, item in enumerate(upcoming):
        conn.execute(
            """
            INSERT OR REPLACE INTO upcoming
            (id, platform, contest_id, name, time, link, sort_order, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("id"),
                item.get("platform", ""),
                str(item.get("contest_id", "")),
                item.get("name", "") or "",
                item.get("time", "") or "",
                item.get("link", "") or "",
                order,
                _extra_payload(item, known_keys),
            ),
        )
