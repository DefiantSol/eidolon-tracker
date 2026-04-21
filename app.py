from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import traceback
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.parse import quote_plus
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
ROOT = APP_DIR
STATIC = RESOURCE_DIR / "static"
DATA_DIR = RESOURCE_DIR / "data"
SEED_PATH = DATA_DIR / "seed.json"
IMAGE_CACHE = STATIC / "img"
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or APP_DIR)
USER_DATA_DIR = LOCAL_APPDATA / "EidolonTracker"
DB_PATH = USER_DATA_DIR / "tracker.db"
LOG_PATH = USER_DATA_DIR / "eidolon-tracker.log"
SHEET_NAME = "Eidolon"
SEED_DATA_VERSION = "collections-stars-20260420"
AKDB_BASE = "https://www.aurakingdom-db.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EidolonTracker/1.0"
STARTER_EIDOLON_NAMES = ("Serif (Adam)", "Merrilee (Eve)", "Grimm (Zhulong)", "Alessa", "Ahri", "Sendama")
STARTER_EIDOLONS = set(STARTER_EIDOLON_NAMES)

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def safe_print(message: str = "") -> None:
    stream = getattr(sys, "stdout", None)
    if stream is None:
        return
    try:
        print(message)
    except (OSError, RuntimeError, AttributeError):
        return


def safe_log(message: str) -> None:
    try:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        return


def tracker_server_running(host: str, port: int) -> bool:
    url = f"http://{host}:{port}/api/state"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return isinstance(payload, dict) and "summary" in payload and "eidolons" in payload and "items" in payload
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return False


def is_address_in_use_error(exc: OSError) -> bool:
    err_no = getattr(exc, "errno", None)
    return err_no in {48, 98, 10048} or "address already in use" in str(exc).lower()


def legacy_db_candidates() -> list[Path]:
    candidates = []
    for candidate in [
        APP_DIR / "tracker.db",
        Path(__file__).resolve().parent / "tracker.db",
    ]:
        if candidate == DB_PATH:
            continue
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def prepare_runtime_storage() -> None:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        return
    for legacy_path in legacy_db_candidates():
        if not legacy_path.exists():
            continue
        try:
            shutil.copy2(legacy_path, DB_PATH)
            return
        except OSError:
            continue


def connect() -> sqlite3.Connection:
    prepare_runtime_storage()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS eidolons (
                id INTEGER PRIMARY KEY,
                profile_id INTEGER NOT NULL DEFAULT 1 REFERENCES profiles(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                source_row INTEGER NOT NULL,
                owned INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                star_rating INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL,
                image_url TEXT NOT NULL DEFAULT '',
                icon_url TEXT NOT NULL DEFAULT '',
                detail_url TEXT NOT NULL DEFAULT '',
                character_note TEXT NOT NULL DEFAULT '',
                client_partner_id INTEGER NOT NULL DEFAULT 0,
                client_name TEXT NOT NULL DEFAULT '',
                UNIQUE(profile_id, name)
            );

            CREATE TABLE IF NOT EXISTS wish_items (
                id INTEGER PRIMARY KEY,
                eidolon_id INTEGER NOT NULL REFERENCES eidolons(id) ON DELETE CASCADE,
                wish_group TEXT NOT NULL,
                item TEXT NOT NULL,
                item_quality_code TEXT NOT NULL DEFAULT '',
                quantity_text TEXT NOT NULL,
                quantity_value REAL,
                how_to_obtain TEXT NOT NULL,
                source_row INTEGER NOT NULL,
                sort_order INTEGER NOT NULL,
                image_url TEXT NOT NULL DEFAULT '',
                detail_url TEXT NOT NULL DEFAULT '',
                UNIQUE(eidolon_id, sort_order)
            );

            CREATE TABLE IF NOT EXISTS item_progress (
                item_id INTEGER PRIMARY KEY REFERENCES wish_items(id) ON DELETE CASCADE,
                completed INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        ensure_column(conn, "eidolons", "image_url", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "eidolons", "icon_url", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "eidolons", "detail_url", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "eidolons", "character_note", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "eidolons", "profile_id", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "eidolons", "star_rating", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "eidolons", "client_partner_id", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "eidolons", "client_name", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "wish_items", "item_quality_code", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "wish_items", "image_url", "TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "wish_items", "detail_url", "TEXT NOT NULL DEFAULT ''")
        ensure_profile_schema(conn)
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_eidolons_profile_name
            ON eidolons(profile_id, name)
            """
        )


def has_unique_name_index(conn: sqlite3.Connection) -> bool:
    for index in conn.execute("PRAGMA index_list(eidolons)"):
        if not index["unique"]:
            continue
        columns = [
            row["name"]
            for row in conn.execute(f"PRAGMA index_info({index['name']})")
            if row["name"] is not None
        ]
        if columns == ["name"]:
            return True
    return False


def rebuild_eidolons_for_profiles(conn: sqlite3.Connection) -> None:
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(
        """
        CREATE TABLE eidolons_new (
            id INTEGER PRIMARY KEY,
            profile_id INTEGER NOT NULL DEFAULT 1 REFERENCES profiles(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            owned INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            star_rating INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL,
            image_url TEXT NOT NULL DEFAULT '',
            icon_url TEXT NOT NULL DEFAULT '',
            detail_url TEXT NOT NULL DEFAULT '',
            character_note TEXT NOT NULL DEFAULT '',
            client_partner_id INTEGER NOT NULL DEFAULT 0,
            client_name TEXT NOT NULL DEFAULT '',
            UNIQUE(profile_id, name)
        );

        INSERT INTO eidolons_new (
            id, profile_id, name, source_row, owned, completed, star_rating, sort_order,
            image_url, icon_url, detail_url, character_note, client_partner_id, client_name
        )
        SELECT
            id, COALESCE(profile_id, 1), name, source_row, owned, completed, COALESCE(star_rating, 0), sort_order,
            COALESCE(image_url, ''), COALESCE(icon_url, ''), COALESCE(detail_url, ''),
            COALESCE(character_note, ''), COALESCE(client_partner_id, 0), COALESCE(client_name, '')
        FROM eidolons;

        DROP TABLE eidolons;
        ALTER TABLE eidolons_new RENAME TO eidolons;
        """
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def ensure_profile_schema(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT OR IGNORE INTO profiles (id, name) VALUES (1, 'Default')")
    ensure_column(conn, "eidolons", "profile_id", "INTEGER NOT NULL DEFAULT 1")
    if has_unique_name_index(conn):
        rebuild_eidolons_for_profiles(conn)
    conn.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('active_profile_id', '1')")


def seed_database(force: bool = False) -> dict[str, int]:
    init_db()
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"Seed data not found: {SEED_PATH}")

    with connect() as conn:
        profile_id = get_current_profile_id(conn)
        existing = conn.execute(
            """
            SELECT COUNT(*)
            FROM wish_items w
            JOIN eidolons e ON e.id = w.eidolon_id
            WHERE e.profile_id = ?
            """,
            (profile_id,),
        ).fetchone()[0]
        if existing and not force:
            return {
                "eidolons": conn.execute(
                    "SELECT COUNT(*) FROM eidolons WHERE profile_id = ?",
                    (profile_id,),
                ).fetchone()[0],
                "items": existing,
            }

        seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        reset_profile_data(conn, profile_id)
        insert_seed_data(conn, seed, profile_id)
        conn.execute(
            """
            INSERT INTO app_settings (key, value)
            VALUES ('seed_data_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (SEED_DATA_VERSION,),
        )
        return profile_counts(conn, profile_id)


def reset_profile_data(conn: sqlite3.Connection, profile_id: int) -> None:
    conn.execute(
        """
        DELETE FROM item_progress
        WHERE item_id IN (
            SELECT w.id
            FROM wish_items w
            JOIN eidolons e ON e.id = w.eidolon_id
            WHERE e.profile_id = ?
        )
        """,
        (profile_id,),
    )
    conn.execute(
        """
        DELETE FROM wish_items
        WHERE eidolon_id IN (
            SELECT id
            FROM eidolons
            WHERE profile_id = ?
        )
        """,
        (profile_id,),
    )
    conn.execute("DELETE FROM eidolons WHERE profile_id = ?", (profile_id,))


def insert_seed_data(conn: sqlite3.Connection, seed: dict, profile_id: int) -> None:
    for eidolon in seed["eidolons"]:
        cursor = conn.execute(
            """
            INSERT INTO eidolons (
                profile_id, name, source_row, owned, completed, star_rating, sort_order,
                image_url, icon_url, detail_url, character_note, client_partner_id, client_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                eidolon["name"],
                eidolon["source_row"],
                eidolon.get("owned", 0),
                eidolon.get("completed", 0),
                eidolon.get("star_rating", 0),
                eidolon["sort_order"],
                eidolon.get("image_url", ""),
                eidolon.get("icon_url", ""),
                eidolon.get("detail_url", ""),
                eidolon.get("character_note", ""),
                eidolon.get("client_partner_id", 0),
                eidolon.get("client_name", ""),
            ),
        )
        eidolon_id = cursor.lastrowid
        for item in eidolon["items"]:
            conn.execute(
                """
                INSERT INTO wish_items (
                    eidolon_id, wish_group, item, item_quality_code, quantity_text, quantity_value,
                    how_to_obtain, source_row, sort_order, image_url, detail_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eidolon_id,
                    item.get("wish_group", ""),
                    item["item"],
                    item.get("item_quality_code", ""),
                    item["quantity_text"],
                    item.get("quantity_value"),
                    item.get("how_to_obtain", ""),
                    item["source_row"],
                    item["sort_order"],
                    item.get("image_url", ""),
                    item.get("detail_url", ""),
                ),
            )


def profile_counts(conn: sqlite3.Connection, profile_id: int) -> dict[str, int]:
    return {
        "eidolons": conn.execute(
            "SELECT COUNT(*) FROM eidolons WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()[0],
        "items": conn.execute(
            """
            SELECT COUNT(*)
            FROM wish_items w
            JOIN eidolons e ON e.id = w.eidolon_id
            WHERE e.profile_id = ?
            """,
            (profile_id,),
        ).fetchone()[0],
    }


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def get_current_profile_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'active_profile_id'").fetchone()
    profile_id = int(row["value"]) if row and str(row["value"]).isdigit() else 1
    exists = conn.execute("SELECT id FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if exists:
        return profile_id
    conn.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('active_profile_id', '1')")
    conn.execute("UPDATE app_settings SET value = '1' WHERE key = 'active_profile_id'")
    return 1


def set_current_profile_id(conn: sqlite3.Connection, profile_id: int) -> None:
    exists = conn.execute("SELECT id FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not exists:
        raise ValueError("Profile not found.")
    conn.execute(
        """
        INSERT INTO app_settings (key, value)
        VALUES ('active_profile_id', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (str(profile_id),),
    )


def profiles_payload(conn: sqlite3.Connection) -> dict:
    return {
        "current_profile_id": get_current_profile_id(conn),
        "profiles": [
            row_to_dict(row)
            for row in conn.execute(
                """
                SELECT id, name
                FROM profiles
                ORDER BY id
                """
            )
        ],
    }


def normalize_profile_name(name: object) -> str:
    value = str(name or "").strip()
    if not value:
        raise ValueError("Profile name is required.")
    return value[:60]


def create_profile(name: str) -> int:
    init_db()
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"Seed data not found: {SEED_PATH}")
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    with connect() as conn:
        cursor = conn.execute("INSERT INTO profiles (name) VALUES (?)", (normalize_profile_name(name),))
        profile_id = cursor.lastrowid
        insert_seed_data(conn, seed, profile_id)
        set_current_profile_id(conn, profile_id)
        return profile_id


def rename_profile(profile_id: int, name: str) -> None:
    with connect() as conn:
        cursor = conn.execute(
            "UPDATE profiles SET name = ? WHERE id = ?",
            (normalize_profile_name(name), profile_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Profile not found.")


def switch_profile(profile_id: int) -> None:
    with connect() as conn:
        set_current_profile_id(conn, profile_id)


def validate_tracker_database(path: Path) -> None:
    conn = None
    try:
        conn = sqlite3.connect(path)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        required = {"eidolons", "wish_items", "item_progress"}
        missing = required - tables
        if missing:
            raise ValueError(f"Backup is missing tracker tables: {', '.join(sorted(missing))}.")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("Backup failed SQLite integrity check.")
    except sqlite3.DatabaseError as exc:
        raise ValueError("Backup is not a readable SQLite tracker database.") from exc
    finally:
        if conn is not None:
            conn.close()


def copy_sqlite_database(source: Path, destination: Path) -> None:
    source_conn = sqlite3.connect(source)
    destination_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(destination_conn)
    finally:
        destination_conn.close()
        source_conn.close()


def backup_download_name() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"EidolonTracker-backup-{stamp}.db"


def ensure_database_file() -> None:
    if DB_PATH.exists():
        init_db()
    else:
        seed_database()


def restore_tracker_database(body: bytes) -> dict:
    if not body:
        raise ValueError("Choose a tracker backup file to restore.")
    if len(body) > 100 * 1024 * 1024:
        raise ValueError("Backup file is too large.")

    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="tracker.restore.", suffix=".db", dir=USER_DATA_DIR, delete=False) as temp_file:
        temp_path = Path(temp_file.name)
    try:
        temp_path.write_bytes(body)
        validate_tracker_database(temp_path)

        if DB_PATH.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(DB_PATH, USER_DATA_DIR / f"tracker.backup.before-restore.{stamp}.db")

        copy_sqlite_database(temp_path, DB_PATH)
        init_db()
        return get_payload()
    finally:
        if temp_path.exists():
            temp_path.unlink()


def cell_column(cell_ref: str) -> str:
    match = re.match(r"[A-Z]+", cell_ref)
    return match.group(0) if match else ""


def cell_row(cell_ref: str) -> int:
    match = re.search(r"\d+", cell_ref)
    return int(match.group(0)) if match else 0


def shared_text(si: ET.Element) -> str:
    return "".join(t.text or "" for t in si.findall(".//m:t", NS))


def column_number(column: str) -> int:
    number = 0
    for char in column:
        number = number * 26 + ord(char) - ord("A") + 1
    return number


def column_name(number: int) -> str:
    chars = []
    while number:
        number, remainder = divmod(number - 1, 26)
        chars.append(chr(ord("A") + remainder))
    return "".join(reversed(chars))


def merged_cells(root: ET.Element) -> list[tuple[str, int, str, int]]:
    ranges = []
    for merge in root.findall(".//m:mergeCells/m:mergeCell", NS):
        ref = merge.attrib.get("ref", "")
        if ":" not in ref:
            continue
        start, end = ref.split(":", 1)
        ranges.append((cell_column(start), cell_row(start), cell_column(end), cell_row(end)))
    return ranges


def read_sheet_abcd(workbook_path: Path, sheet_name: str) -> dict[int, dict[str, str]]:
    with zipfile.ZipFile(workbook_path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = [shared_text(si) for si in root.findall("m:si", NS)]

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

        sheet_path = None
        for sheet in workbook.find("m:sheets", NS) or []:
            if sheet.attrib.get("name") == sheet_name:
                rid = sheet.attrib[f"{{{REL_NS}}}id"]
                target = relmap[rid]
                sheet_path = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
                break

        if sheet_path is None:
            raise ValueError(f"Sheet not found: {sheet_name}")

        root = ET.fromstring(archive.read(sheet_path))
        rows: dict[int, dict[str, str]] = {}
        for row in root.findall(".//m:sheetData/m:row", NS):
            row_number = int(row.attrib["r"])
            values: dict[str, str] = {}
            for cell in row.findall("m:c", NS):
                ref = cell.attrib.get("r", "")
                column = cell_column(ref)
                if column not in {"A", "B", "C", "D"}:
                    continue

                cell_type = cell.attrib.get("t")
                value_node = cell.find("m:v", NS)
                inline_node = cell.find("m:is", NS)
                value = ""
                if cell_type == "s" and value_node is not None:
                    value = shared[int(value_node.text or "0")]
                elif cell_type == "inlineStr" and inline_node is not None:
                    value = "".join(t.text or "" for t in inline_node.findall(".//m:t", NS))
                elif value_node is not None:
                    value = value_node.text or ""

                values[column] = value.strip()
            if values:
                rows[row_number] = values
        for start_col, start_row, end_col, end_row in merged_cells(root):
            source = rows.get(start_row, {}).get(start_col, "")
            if not source:
                continue
            for column_index in range(column_number(start_col), column_number(end_col) + 1):
                column = column_name(column_index)
                if column not in {"A", "B", "C", "D"}:
                    continue
                for row_number in range(start_row, end_row + 1):
                    rows.setdefault(row_number, {}).setdefault(column, source)
        return rows


def format_quantity(raw: str) -> tuple[str, float | None]:
    if not raw:
        return "1", 1
    try:
        number = float(raw)
    except ValueError:
        return raw, None
    if number.is_integer():
        return str(int(number)), number
    return str(number), number


def extract_eidolons(workbook_path: Path) -> list[dict]:
    rows = read_sheet_abcd(workbook_path, SHEET_NAME)
    row_numbers = sorted(rows)
    eidolons: list[dict] = []
    current: dict | None = None
    pending_title: tuple[int, str] | None = None

    for row_number in row_numbers:
        values = rows[row_number]
        a = values.get("A", "").strip()
        b = values.get("B", "").strip()
        c = values.get("C", "").strip()
        d = values.get("D", "").strip()

        if pending_title and b.lower() == "wishes" and c == "#" and "description" in d.lower():
            title_row, title = pending_title
            current = {"name": title, "source_row": title_row, "items": []}
            eidolons.append(current)
            pending_title = None
            continue

        if not a and b and not c and not d:
            pending_title = (row_number, b)
            continue

        pending_title = None
        if current is None or not b or b.lower() == "wishes":
            continue

        quantity_text, quantity_value = format_quantity(c)
        current["items"].append(
            {
                "wish_group": a,
                "item": b,
                "quantity_text": quantity_text,
                "quantity_value": quantity_value,
                "how_to_obtain": d,
                "source_row": row_number,
            }
        )

    return [eidolon for eidolon in eidolons if eidolon["items"]]


def fetch_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


def fetch_bytes(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        content_type = response.headers.get("Content-Type", "")
        return response.read(), content_type


def normalize_name(value: str) -> str:
    value = html.unescape(value).lower()
    value = value.replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def eidolon_name_candidates(name: str) -> set[str]:
    candidates = {normalize_name(name)}
    if "(" in name and ")" in name:
        outside = re.sub(r"\s*\([^)]*\)", "", name).strip()
        inside = re.findall(r"\(([^)]*)\)", name)
        if outside:
            candidates.add(normalize_name(outside))
        for alias in inside:
            candidates.add(normalize_name(alias))
    return {candidate for candidate in candidates if candidate}


def eidolon_display_candidates(name: str) -> set[str]:
    candidates = {name.strip()}
    outside = re.sub(r"\s*\([^)]*\)", "", name).strip()
    if outside:
        candidates.add(outside)
    for alias in re.findall(r"\(([^)]*)\)", name):
        candidates.add(alias.strip())
    return {candidate for candidate in candidates if candidate}


def key_fragment_bases(value: str) -> set[str]:
    clean = html.unescape(value).replace("&", "and").strip()
    bases: set[str] = set()
    patterns = [
        r"key of gaia fragments? of (?P<base>.+)$",
        r"key fragments? of (?P<base>.+)$",
        r"(?P<base>.+?)(?:'s|s'|')?\s+key of gaia fragments?$",
        r"(?P<base>.+?)(?:'s|s'|')?\s+key fragments?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean, re.I)
        if match:
            base = match.group("base").strip(" -:")
            if base:
                bases.add(normalize_name(base))
    return bases


def key_fragment_display_bases(value: str) -> set[str]:
    clean = html.unescape(value).replace("&", "and").strip()
    bases: set[str] = set()
    patterns = [
        r"key of gaia fragments? of (?P<base>.+)$",
        r"key fragments? of (?P<base>.+)$",
        r"(?P<base>.+?)(?:'s|s'|')?\s+key of gaia fragments?$",
        r"(?P<base>.+?)(?:'s|s'|')?\s+key fragments?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean, re.I)
        if match:
            base = match.group("base").strip(" -:")
            if base:
                bases.add(base)
    return bases


def singular_plural_variants(word: str) -> set[str]:
    variants = {word}
    lower = word.lower()
    if lower.endswith("s") and not lower.endswith("ss"):
        variants.add(word[:-1])
    else:
        variants.add(word + "s")
    return {variant for variant in variants if variant}


def possessive_variants(word: str) -> set[str]:
    variants = {word}
    lower = word.lower()
    if lower.endswith("'s"):
        root = word[:-2]
        variants.add(root)
        variants.add(root + "s")
    elif lower.endswith("s'"):
        root = word[:-1]
        variants.add(root)
    elif lower.endswith("s"):
        variants.add(word + "'")
        variants.add(word[:-1] + "'s")
    else:
        variants.add(word + "'s")
        variants.add(word + "s")
    return {variant for variant in variants if variant}


def smart_item_name_variants(item_name: str) -> list[str]:
    words = item_name.split()
    variants = {item_name}
    if not words:
        return [item_name]

    for last in singular_plural_variants(words[-1]):
        variants.add(" ".join(words[:-1] + [last]))

    if len(words) > 1:
        for first in possessive_variants(words[0]):
            variants.add(" ".join([first] + words[1:]))

        for first in possessive_variants(words[0]):
            for last in singular_plural_variants(words[-1]):
                variants.add(" ".join([first] + words[1:-1] + [last]))

    ordered = []
    seen = set()
    for variant in [item_name, *sorted(variants)]:
        key = normalize_name(variant)
        if key and key not in seen:
            ordered.append(variant)
            seen.add(key)
    return ordered


def is_key_fragment_match(title: str, item_name: str, eidolon_name: str = "") -> bool:
    title_lower = title.lower()
    if "key fragment" not in title_lower and "key of gaia fragment" not in title_lower:
        return False
    wanted_bases = key_fragment_bases(item_name)
    for candidate in eidolon_display_candidates(eidolon_name):
        wanted_bases.add(normalize_name(candidate))
    title_bases = key_fragment_bases(title)
    return bool(wanted_bases & title_bases)


def parse_eidolon_list() -> dict[str, dict[str, str]]:
    data = fetch_url(f"{AKDB_BASE}/eidolons")
    matches = re.finditer(
        r'<a[^>]+href="(?P<href>/eidolon/[^"]+)"[^>]*>(?P<name>.*?)</a>',
        data,
        re.S,
    )
    by_name: dict[str, dict[str, str]] = {}
    for match in matches:
        name = re.sub(r"<.*?>", "", match.group("name")).strip()
        if not name or name == "Image":
            continue
        detail_url = f"{AKDB_BASE}{match.group('href')}"
        by_name[normalize_name(name)] = {"name": html.unescape(name), "detail_url": detail_url}
    return by_name


def parse_detail_assets(detail_url: str) -> dict:
    data = fetch_url(detail_url)
    imgs = re.findall(r'<img[^>]+src="([^"]+)"', data)
    icon_url = next((src for src in imgs if "/images/icons/P" in src), "")
    image_url = next((src for src in imgs if "/images/npcs/" in src), icon_url)

    materials: dict[str, dict[str, str]] = {}
    wish_start = data.find("Eidolon Wishes")
    wish_html = data[wish_start:] if wish_start >= 0 else data
    for match in re.finditer(
        r'<a[^>]+title="(?P<title>[^"]+)"[^>]+href="(?P<href>/item/[^"]+)"[^>]*>.*?<img[^>]+src="(?P<src>[^"]+)"',
        wish_html,
        re.S,
    ):
        title = html.unescape(match.group("title")).strip()
        materials[normalize_name(title)] = {
            "title": title,
            "detail_url": f"{AKDB_BASE}{match.group('href')}",
            "image_url": match.group("src"),
        }

    return {"image_url": image_url, "icon_url": icon_url, "materials": materials}


def item_search_queries(item_name: str, eidolon_name: str = "") -> list[str]:
    queries = smart_item_name_variants(item_name)
    if "key fragment" in item_name.lower():
        bases = key_fragment_display_bases(item_name)
        bases.update(eidolon_display_candidates(eidolon_name))
        for base in sorted({base for base in bases if base}):
            queries.extend(
                [
                    f"{base} Key Fragment",
                    f"{base} Key Fragments",
                    f"{base} Key of Gaia Fragment",
                    f"{base} Key of Gaia Fragments",
                    f"Key Fragment of {base}",
                    f"Key Fragments of {base}",
                    f"Key of Gaia Fragment of {base}",
                    f"Key of Gaia Fragments of {base}",
                    base,
                ]
            )
    seen = set()
    ordered = []
    for query in queries:
        key = normalize_name(query)
        if key and key not in seen:
            ordered.append(query)
            seen.add(key)
    return ordered


def search_item_asset(item_name: str, eidolon_name: str = "") -> dict[str, str] | None:
    queries = item_search_queries(item_name, eidolon_name)
    accepted_names = {normalize_name(query) for query in queries}
    for query in queries:
        data = fetch_url(f"{AKDB_BASE}/search?s={quote_plus(query)}")
        for match in re.finditer(
            r'<tr>.*?<img[^>]+src="(?P<src>[^"]+)".*?<a[^>]+href="(?P<href>/item/[^"]+)"[^>]*>(?P<title>.*?)</a>.*?</tr>',
            data,
            re.S,
        ):
            title = html.unescape(re.sub(r"<.*?>", "", match.group("title")).strip())
            title_key = normalize_name(title)
            if title_key in accepted_names or is_key_fragment_match(title, item_name, eidolon_name):
                return {
                    "title": title,
                    "detail_url": f"{AKDB_BASE}{match.group('href')}",
                    "image_url": match.group("src"),
                }
    return None


def sync_missing_item_assets(limit: int | None = None) -> dict[str, int]:
    init_db()
    searched = 0
    matched = 0
    cache: dict[str, dict[str, str] | None] = {}
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT w.item, e.name AS eidolon_name
            FROM wish_items w
            JOIN eidolons e ON e.id = w.eidolon_id
            WHERE w.image_url = ''
            GROUP BY w.item, e.name
            ORDER BY w.item
            """
        ).fetchall()
        for row in rows:
            if limit is not None and searched >= limit:
                break
            item_name = row["item"]
            eidolon_name = row["eidolon_name"]
            key = f"{normalize_name(item_name)}:{normalize_name(eidolon_name)}"
            if key not in cache:
                try:
                    cache[key] = search_item_asset(item_name, eidolon_name)
                except Exception as exc:
                    safe_print(f"Item image lookup failed for {item_name}: {exc}")
                    cache[key] = None
                searched += 1
            asset = cache[key]
            if not asset:
                continue
            cursor = conn.execute(
                """
                UPDATE wish_items
                SET image_url = ?, detail_url = ?
                WHERE image_url = '' AND item = ?
                """,
                (asset["image_url"], asset["detail_url"], item_name),
            )
            matched += cursor.rowcount
    return {"searched": searched, "items": matched}


def cached_image_path(url: str, bucket: str) -> str | None:
    if not url.startswith("http"):
        return url if url.startswith("/img/") else None
    ext = Path(urlparse(url).path).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        ext = ".img"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    local_dir = IMAGE_CACHE / bucket
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / f"{digest}{ext}"
    public_path = f"/img/{bucket}/{local_path.name}"
    if local_path.exists() and local_path.stat().st_size > 0:
        return public_path
    data, content_type = fetch_bytes(url)
    if not data or not content_type.startswith("image/"):
        return None
    local_path.write_bytes(data)
    return public_path


def cache_remote_images() -> dict[str, int]:
    init_db()
    IMAGE_CACHE.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    skipped = 0
    failed = 0

    with connect() as conn:
        eidolons = conn.execute(
            """
            SELECT id, image_url, icon_url
            FROM eidolons
            WHERE image_url LIKE 'http%' OR icon_url LIKE 'http%'
            """
        ).fetchall()
        for row in eidolons:
            updates = {}
            for column in ("image_url", "icon_url"):
                url = row[column]
                if not url:
                    continue
                try:
                    local = cached_image_path(url, "eidolons")
                    if local and local != url:
                        updates[column] = local
                        downloaded += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    failed += 1
                    safe_print(f"Image cache failed for {url}: {exc}")
            if updates:
                assignments = ", ".join(f"{column} = ?" for column in updates)
                conn.execute(
                    f"UPDATE eidolons SET {assignments} WHERE id = ?",
                    list(updates.values()) + [row["id"]],
                )

        items = conn.execute(
            """
            SELECT id, image_url
            FROM wish_items
            WHERE image_url LIKE 'http%'
            """
        ).fetchall()
        for row in items:
            try:
                local = cached_image_path(row["image_url"], "items")
                if local and local != row["image_url"]:
                    conn.execute("UPDATE wish_items SET image_url = ? WHERE id = ?", (local, row["id"]))
                    downloaded += 1
                else:
                    skipped += 1
            except Exception as exc:
                failed += 1
                safe_print(f"Image cache failed for {row['image_url']}: {exc}")

    return {"downloaded": downloaded, "skipped": skipped, "failed": failed}


def sync_assets() -> dict[str, int]:
    init_db()
    eidolon_index = parse_eidolon_list()
    matched_eidolons = 0
    matched_items = 0

    with connect() as conn:
        eidolons = conn.execute("SELECT * FROM eidolons ORDER BY sort_order").fetchall()
        for eidolon in eidolons:
            match = None
            for candidate in eidolon_name_candidates(eidolon["name"]):
                if candidate in eidolon_index:
                    match = eidolon_index[candidate]
                    break
            if not match:
                continue

            assets = parse_detail_assets(match["detail_url"])
            conn.execute(
                """
                UPDATE eidolons
                SET image_url = ?, icon_url = ?, detail_url = ?
                WHERE id = ?
                """,
                (assets["image_url"], assets["icon_url"], match["detail_url"], eidolon["id"]),
            )
            matched_eidolons += 1

            items = conn.execute(
                "SELECT id, item FROM wish_items WHERE eidolon_id = ?",
                (eidolon["id"],),
            ).fetchall()
            for item in items:
                material = assets["materials"].get(normalize_name(item["item"]))
                if not material:
                    continue
                conn.execute(
                    """
                    UPDATE wish_items
                    SET image_url = ?, detail_url = ?
                    WHERE id = ?
                    """,
                    (material["image_url"], material["detail_url"], item["id"]),
                )
                matched_items += 1

    fallback = sync_missing_item_assets()
    return {
        "eidolons": matched_eidolons,
        "items": matched_items,
        "fallback_searched": fallback["searched"],
        "fallback_items": fallback["items"],
    }


def import_workbook(workbook_path: Path, force: bool = False) -> dict[str, int]:
    init_db()
    eidolons = extract_eidolons(workbook_path)
    with connect() as conn:
        profile_id = get_current_profile_id(conn)
        existing = conn.execute(
            """
            SELECT COUNT(*)
            FROM wish_items w
            JOIN eidolons e ON e.id = w.eidolon_id
            WHERE e.profile_id = ?
            """,
            (profile_id,),
        ).fetchone()[0]
        if existing and not force:
            return {
                "eidolons": conn.execute(
                    "SELECT COUNT(*) FROM eidolons WHERE profile_id = ?",
                    (profile_id,),
                ).fetchone()[0],
                "items": existing,
            }

        if force:
            reset_profile_data(conn, profile_id)

        for eidolon_index, eidolon in enumerate(eidolons):
            cursor = conn.execute(
                """
                INSERT INTO eidolons (
                    profile_id, name, source_row, owned, completed, star_rating, sort_order,
                    client_partner_id, client_name
                )
                VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)
                ON CONFLICT(profile_id, name) DO UPDATE SET
                    source_row = excluded.source_row,
                    owned = CASE
                        WHEN eidolons.owned = 1 OR excluded.owned = 1 THEN 1
                        ELSE 0
                    END,
                    sort_order = excluded.sort_order,
                    client_partner_id = CASE
                        WHEN excluded.client_partner_id != 0 THEN excluded.client_partner_id
                        ELSE eidolons.client_partner_id
                    END,
                    client_name = CASE
                        WHEN excluded.client_name != '' THEN excluded.client_name
                        ELSE eidolons.client_name
                    END
                """,
                (
                    profile_id,
                    eidolon["name"],
                    eidolon["source_row"],
                    1 if eidolon["name"] in STARTER_EIDOLONS else 0,
                    eidolon.get("star_rating", 0),
                    eidolon_index,
                    eidolon.get("client_partner_id", 0),
                    eidolon.get("client_name", ""),
                ),
            )
            eidolon_id = cursor.lastrowid or conn.execute(
                "SELECT id FROM eidolons WHERE profile_id = ? AND name = ?",
                (profile_id, eidolon["name"]),
            ).fetchone()[0]

            for item_index, item in enumerate(eidolon["items"]):
                conn.execute(
                    """
                    INSERT INTO wish_items (
                        eidolon_id, wish_group, item, item_quality_code, quantity_text, quantity_value,
                        how_to_obtain, source_row, sort_order
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        eidolon_id,
                        item["wish_group"],
                        item["item"],
                        item.get("item_quality_code", ""),
                        item["quantity_text"],
                        item["quantity_value"],
                        item["how_to_obtain"],
                        item["source_row"],
                        item_index,
                    ),
                )

        return {
            **profile_counts(conn, profile_id),
        }


def item_key(item_name: str) -> str:
    return normalize_name(item_name)


def progress_snapshot(conn: sqlite3.Connection, profile_id: int | None = None) -> dict:
    if profile_id is None:
        profile_id = get_current_profile_id(conn)
    eidolons = conn.execute("SELECT * FROM eidolons WHERE profile_id = ?", (profile_id,)).fetchall()
    items = conn.execute(
        """
        SELECT
            e.name AS eidolon_name,
            w.item,
            w.sort_order,
            w.image_url,
            w.detail_url,
            COALESCE(p.completed, 0) AS completed
        FROM wish_items w
        JOIN eidolons e ON e.id = w.eidolon_id
        LEFT JOIN item_progress p ON p.item_id = w.id
        WHERE e.profile_id = ?
        """,
        (profile_id,),
    ).fetchall()
    return {
        "eidolons": {
            row["name"]: {
                "owned": row["owned"],
                "completed": row["completed"],
                "star_rating": row["star_rating"],
                "image_url": row["image_url"],
                "icon_url": row["icon_url"],
                "detail_url": row["detail_url"],
                "character_note": row["character_note"],
                "client_partner_id": row["client_partner_id"],
                "client_name": row["client_name"],
            }
            for row in eidolons
        },
        "items": {
            (row["eidolon_name"], item_key(row["item"])): {
                "completed": row["completed"],
                "image_url": row["image_url"],
                "detail_url": row["detail_url"],
            }
            for row in items
        },
        "items_by_order": {
            (row["eidolon_name"], row["sort_order"]): {
                "completed": row["completed"],
                "image_url": row["image_url"],
                "detail_url": row["detail_url"],
            }
            for row in items
        },
    }


def seed_refresh_needed(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'seed_data_version'").fetchone()
    return not row or row["value"] != SEED_DATA_VERSION


def refresh_seed_data(force: bool = False) -> dict[str, int]:
    init_db()
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"Seed data not found: {SEED_PATH}")

    with connect() as conn:
        if not force and not seed_refresh_needed(conn):
            return profile_counts(conn, get_current_profile_id(conn))

        seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        profile_ids = [
            row["id"]
            for row in conn.execute("SELECT id FROM profiles ORDER BY id").fetchall()
        ]
        restored_completed = 0

        for profile_id in profile_ids:
            snapshot = progress_snapshot(conn, profile_id)
            reset_profile_data(conn, profile_id)
            for eidolon in seed["eidolons"]:
                saved_eidolon = snapshot["eidolons"].get(eidolon["name"], {})
                cursor = conn.execute(
                    """
                    INSERT INTO eidolons (
                        profile_id, name, source_row, owned, completed, star_rating, sort_order,
                        image_url, icon_url, detail_url, character_note, client_partner_id, client_name
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id,
                        eidolon["name"],
                        eidolon["source_row"],
                        1 if eidolon["name"] in STARTER_EIDOLONS else saved_eidolon.get("owned", eidolon.get("owned", 0)),
                        saved_eidolon.get("completed", eidolon.get("completed", 0)),
                        saved_eidolon.get("star_rating", eidolon.get("star_rating", 0)),
                        eidolon["sort_order"],
                        saved_eidolon.get("image_url") or eidolon.get("image_url", ""),
                        saved_eidolon.get("icon_url") or eidolon.get("icon_url", ""),
                        saved_eidolon.get("detail_url") or eidolon.get("detail_url", ""),
                        saved_eidolon.get("character_note") or eidolon.get("character_note", ""),
                        saved_eidolon.get("client_partner_id") or eidolon.get("client_partner_id", 0),
                        saved_eidolon.get("client_name") or eidolon.get("client_name", ""),
                    ),
                )
                eidolon_id = cursor.lastrowid
                for item in eidolon["items"]:
                    saved_item = snapshot["items"].get((eidolon["name"], item_key(item["item"])))
                    if saved_item is None:
                        saved_item = snapshot["items_by_order"].get((eidolon["name"], item["sort_order"]), {})
                    item_cursor = conn.execute(
                        """
                        INSERT INTO wish_items (
                            eidolon_id, wish_group, item, item_quality_code, quantity_text, quantity_value,
                            how_to_obtain, source_row, sort_order, image_url, detail_url
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            eidolon_id,
                            item.get("wish_group", ""),
                            item["item"],
                            item.get("item_quality_code", ""),
                            item["quantity_text"],
                            item.get("quantity_value"),
                            item.get("how_to_obtain", ""),
                            item["source_row"],
                            item["sort_order"],
                            saved_item.get("image_url") or item.get("image_url", ""),
                            saved_item.get("detail_url") or item.get("detail_url", ""),
                        ),
                    )
                    if saved_item.get("completed"):
                        conn.execute("INSERT INTO item_progress (item_id, completed) VALUES (?, 1)", (item_cursor.lastrowid,))
                        restored_completed += 1

        conn.execute(
            """
            INSERT INTO app_settings (key, value)
            VALUES ('seed_data_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (SEED_DATA_VERSION,),
        )
        counts = profile_counts(conn, get_current_profile_id(conn))
        counts["restored_completed_items"] = restored_completed
        return counts


def rebuild_from_reference(reference_path: Path, live_path: Path) -> dict[str, int]:
    init_db()
    reference_eidolons = extract_eidolons(reference_path)
    live_eidolons = extract_eidolons(live_path)
    live_items = {
        eidolon["name"]: {item_key(item["item"]) for item in eidolon["items"]}
        for eidolon in live_eidolons
    }

    with connect() as conn:
        profile_id = get_current_profile_id(conn)
        snapshot = progress_snapshot(conn)
        reset_profile_data(conn, profile_id)

        inferred_completed = 0
        restored_completed = 0
        owned_count = 0

        for eidolon_index, eidolon in enumerate(reference_eidolons):
            saved_eidolon = snapshot["eidolons"].get(eidolon["name"], {})
            starter_owned = eidolon["name"] in STARTER_EIDOLONS
            cursor = conn.execute(
                """
                INSERT INTO eidolons (
                    profile_id, name, source_row, owned, completed, star_rating, sort_order,
                    image_url, icon_url, detail_url, character_note, client_partner_id, client_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    eidolon["name"],
                    eidolon["source_row"],
                    1 if starter_owned else saved_eidolon.get("owned", 0),
                    0,
                    saved_eidolon.get("star_rating", eidolon.get("star_rating", 0)),
                    eidolon_index,
                    saved_eidolon.get("image_url", ""),
                    saved_eidolon.get("icon_url", ""),
                    saved_eidolon.get("detail_url", ""),
                    saved_eidolon.get("character_note", ""),
                    saved_eidolon.get("client_partner_id") or eidolon.get("client_partner_id", 0),
                    saved_eidolon.get("client_name") or eidolon.get("client_name", ""),
                ),
            )
            eidolon_id = cursor.lastrowid
            live_keys = live_items.get(eidolon["name"], set())
            has_inferred_completion = False

            for item_index, item in enumerate(eidolon["items"]):
                saved_item = snapshot["items"].get((eidolon["name"], item_key(item["item"])), {})
                item_cursor = conn.execute(
                    """
                    INSERT INTO wish_items (
                        eidolon_id, wish_group, item, item_quality_code, quantity_text, quantity_value,
                        how_to_obtain, source_row, sort_order, image_url, detail_url
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        eidolon_id,
                        item["wish_group"],
                        item["item"],
                        item.get("item_quality_code", ""),
                        item["quantity_text"],
                        item["quantity_value"],
                        item["how_to_obtain"],
                        item["source_row"],
                        item_index,
                        saved_item.get("image_url", ""),
                        saved_item.get("detail_url", ""),
                    ),
                )

                missing_from_live = item_key(item["item"]) not in live_keys
                completed = bool(saved_item.get("completed")) or missing_from_live or bool(saved_eidolon.get("completed"))
                if completed:
                    conn.execute(
                        "INSERT INTO item_progress (item_id, completed) VALUES (?, 1)",
                        (item_cursor.lastrowid,),
                    )
                    if missing_from_live:
                        inferred_completed += 1
                        has_inferred_completion = True
                    elif saved_item.get("completed") or saved_eidolon.get("completed"):
                        restored_completed += 1

            if starter_owned or saved_eidolon.get("owned") or has_inferred_completion or saved_eidolon.get("completed"):
                conn.execute("UPDATE eidolons SET owned = 1 WHERE id = ? AND profile_id = ?", (eidolon_id, profile_id))

            counts = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN COALESCE(p.completed, 0) = 1 THEN 1 ELSE 0 END) AS done
                FROM wish_items w
                LEFT JOIN item_progress p ON p.item_id = w.id
                WHERE w.eidolon_id = ?
                """,
                (eidolon_id,),
            ).fetchone()
            if counts["total"] and counts["total"] == (counts["done"] or 0):
                conn.execute(
                    "UPDATE eidolons SET owned = 1, completed = 1 WHERE id = ? AND profile_id = ?",
                    (eidolon_id, profile_id),
                )

        owned_count = conn.execute(
            "SELECT COUNT(*) FROM eidolons WHERE profile_id = ? AND owned = 1",
            (profile_id,),
        ).fetchone()[0]
        return {
            **profile_counts(conn, profile_id),
            "inferred_completed_items": inferred_completed,
            "restored_completed_items": restored_completed,
            "owned": owned_count,
            "completed_eidolons": conn.execute(
                "SELECT COUNT(*) FROM eidolons WHERE profile_id = ? AND completed = 1",
                (profile_id,),
            ).fetchone()[0],
        }


def row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def seed_collections() -> list[dict]:
    if not SEED_PATH.exists():
        return []
    try:
        seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    return seed.get("collections", [])


def collection_matches_progress(collection: dict, progress_filter: str) -> bool:
    max_star = collection.get("active_star_level", 0)
    owned_count = collection.get("owned_count", 0)
    member_count = collection.get("member_count", 0)
    if progress_filter == "all":
        return True
    if progress_filter == "complete":
        return max_star >= 4
    if progress_filter == "active":
        return owned_count > 0 and max_star < 4
    return max_star < 4


def build_collections(eidolons: list[dict]) -> list[dict]:
    collection_aliases = {
        normalize_name("Yamata no Orochi"): {normalize_name("Orochi")},
        normalize_name("Shuten-Douji"): {normalize_name("Shuten-Doji")},
        normalize_name("Summer Shuten-Douji"): {normalize_name("Summer Shuten-Doji")},
    }

    def collection_name_candidates(name: str) -> set[str]:
        candidates = eidolon_name_candidates(name) | {
            normalize_name(value) for value in eidolon_display_candidates(name)
        }
        for candidate in list(candidates):
            candidates.update(collection_aliases.get(candidate, set()))
        return {candidate for candidate in candidates if candidate}

    partner_map = {
        int(eidolon.get("client_partner_id", 0)): eidolon
        for eidolon in eidolons
        if int(eidolon.get("client_partner_id", 0) or 0) > 0
    }
    name_map: dict[str, dict] = {}
    for eidolon in eidolons:
        for candidate in collection_name_candidates(eidolon["name"]):
            if candidate:
                name_map[candidate] = eidolon
    collections = []
    for entry in seed_collections():
        members = []
        stars = []
        owned_count = 0
        source_names = entry.get("member_names") or entry.get("member_client_names") or []
        for index, partner_id in enumerate(entry.get("member_partner_ids", [])):
            eidolon = partner_map.get(int(partner_id))
            if eidolon is None and index < len(source_names):
                for candidate in collection_name_candidates(source_names[index]):
                    eidolon = name_map.get(candidate)
                    if eidolon is not None:
                        break
            member_name = source_names[index] if index < len(source_names) else str(partner_id)
            member = {
                "partner_id": partner_id,
                "name": eidolon["name"] if eidolon else member_name,
                "eidolon_id": eidolon["id"] if eidolon else 0,
                "owned": int(eidolon["owned"]) if eidolon else 0,
                "star_rating": int(eidolon.get("star_rating", 0) or 0) if eidolon else 0,
                "detail_url": eidolon.get("detail_url", "") if eidolon else "",
            }
            if member["owned"]:
                owned_count += 1
            stars.append(member["star_rating"])
            members.append(member)
        active_star_level = 0
        for tier in range(1, 5):
            if members and all(star >= tier for star in stars):
                active_star_level = tier
            else:
                break
        collections.append(
            {
                **entry,
                "members": members,
                "member_count": len(members),
                "owned_count": owned_count,
                "active_star_level": active_star_level,
                "one_star_active": 1 if active_star_level >= 1 else 0,
                "two_star_active": 1 if active_star_level >= 2 else 0,
                "three_star_active": 1 if active_star_level >= 3 else 0,
                "four_star_active": 1 if active_star_level >= 4 else 0,
            }
        )
    return collections


def apply_wish_metrics(eidolons: list[dict], items: list[dict]) -> None:
    eidolon_metrics = {
        eidolon["id"]: {
            "wish_count": 0,
            "completed_wish_count": 0,
            "item_count": 0,
            "completed_item_count": 0,
        }
        for eidolon in eidolons
    }
    wish_groups: dict[tuple[int, str], dict] = {}
    current_groups: dict[int, str] = {}
    current_tiers: dict[int, int] = {}

    for item in items:
        eidolon_id = item["eidolon_id"]
        raw_group = (item.get("wish_group") or "").strip()
        previous_group = current_groups.get(eidolon_id, "")
        starts_group = 0
        if raw_group:
            effective_group = raw_group
            if raw_group != previous_group:
                current_tiers[eidolon_id] = current_tiers.get(eidolon_id, 0) + 1
                starts_group = 1
            elif eidolon_id not in current_tiers:
                current_tiers[eidolon_id] = 1
                starts_group = 1
            current_groups[eidolon_id] = raw_group
        else:
            if eidolon_id not in current_tiers:
                current_tiers[eidolon_id] = 1
            effective_group = previous_group or f"Item {item['sort_order'] + 1}"
        effective_tier = current_tiers.get(eidolon_id, 1)
        item["wish_group_effective"] = effective_group
        item["wish_tier"] = effective_tier
        item["starts_wish_group"] = starts_group

        key = (eidolon_id, effective_group)
        group = wish_groups.setdefault(
            key,
            {
                "eidolon_id": eidolon_id,
                "group": effective_group,
                "tier": effective_tier,
                "total": 0,
                "completed": 0,
            },
        )
        group["total"] += 1
        if item.get("completed"):
            group["completed"] += 1

        metrics = eidolon_metrics[eidolon_id]
        metrics["item_count"] += 1
        if item.get("completed"):
            metrics["completed_item_count"] += 1

    for group in wish_groups.values():
        metrics = eidolon_metrics[group["eidolon_id"]]
        metrics["wish_count"] += 1
        if group["total"] and group["total"] == group["completed"]:
            metrics["completed_wish_count"] += 1

    for eidolon in eidolons:
        metrics = eidolon_metrics.get(eidolon["id"], {})
        eidolon["wish_count"] = metrics.get("wish_count", 0)
        eidolon["completed_wish_count"] = metrics.get("completed_wish_count", 0)
        eidolon["item_count"] = metrics.get("item_count", eidolon.get("item_count", 0) or 0)
        eidolon["completed_item_count"] = metrics.get(
            "completed_item_count", eidolon.get("completed_item_count", 0) or 0
        )
        completed_tiers = {
            group["tier"]
            for group in wish_groups.values()
            if group["eidolon_id"] == eidolon["id"] and group["total"] and group["total"] == group["completed"]
        }
        completed_through_tier = 0
        for tier in range(1, metrics.get("wish_count", 0) + 1):
            if tier not in completed_tiers:
                break
            completed_through_tier = tier
        eidolon["completed_wish_tier"] = completed_through_tier
        if metrics.get("wish_count", 0) and completed_through_tier < metrics.get("wish_count", 0):
            eidolon["current_wish_tier"] = completed_through_tier + 1
        else:
            eidolon["current_wish_tier"] = 0


def build_summary(eidolons: list[dict], items: list[dict], collections: list[dict] | None = None) -> dict:
    wishes_total = sum(eidolon.get("wish_count", 0) for eidolon in eidolons)
    wishes_completed = sum(eidolon.get("completed_wish_count", 0) for eidolon in eidolons)
    wishes_active = sum(
        max((eidolon.get("wish_count", 0) or 0) - (eidolon.get("completed_wish_count", 0) or 0), 0)
        for eidolon in eidolons
        if eidolon.get("owned") and not eidolon.get("completed")
    )
    item_total = len(items)
    item_completed = sum(1 for item in items if item.get("completed"))
    item_active = sum(
        1
        for item in items
        if item.get("eidolon_owned") and not item.get("eidolon_completed") and not item.get("completed")
    )
    summary = {
        "eidolons": len(eidolons),
        "owned": sum(1 for eidolon in eidolons if eidolon.get("owned")),
        "completed": sum(1 for eidolon in eidolons if eidolon.get("completed")),
        "wishes_total": wishes_total,
        "wishes_active": wishes_active,
        "wishes_completed": wishes_completed,
        "items_total": item_total,
        "items_active": item_active,
        "items_completed": item_completed,
    }
    if collections is not None:
        summary.update(
            {
                "collections_total": len(collections),
                "collections_three_star": sum(1 for collection in collections if collection.get("three_star_active")),
                "collections_four_star": sum(1 for collection in collections if collection.get("four_star_active")),
            }
        )
    return summary


def get_payload() -> dict:
    with connect() as conn:
        profile_id = get_current_profile_id(conn)
        eidolon_rows = conn.execute(
            """
            SELECT
                e.*,
                COUNT(w.id) AS item_count,
                SUM(CASE WHEN COALESCE(p.completed, 0) = 1 THEN 1 ELSE 0 END) AS completed_item_count
            FROM eidolons e
            LEFT JOIN wish_items w ON w.eidolon_id = e.id
            LEFT JOIN item_progress p ON p.item_id = w.id
            WHERE e.profile_id = ?
            GROUP BY e.id
            ORDER BY e.sort_order
            """,
            (profile_id,),
        ).fetchall()
        items = conn.execute(
            """
            SELECT
                w.*,
                e.name AS eidolon_name,
                e.owned AS eidolon_owned,
                e.completed AS eidolon_completed,
                COALESCE(p.completed, 0) AS completed
            FROM wish_items w
            JOIN eidolons e ON e.id = w.eidolon_id
            LEFT JOIN item_progress p ON p.item_id = w.id
            WHERE e.profile_id = ?
            ORDER BY e.sort_order, w.sort_order
            """,
            (profile_id,),
        ).fetchall()
        eidolons = [row_to_dict(row) for row in eidolon_rows]
        for eidolon in eidolons:
            eidolon["is_starter"] = 1 if eidolon["name"] in STARTER_EIDOLONS else 0
        item_dicts = [row_to_dict(row) for row in items]
        apply_wish_metrics(eidolons, item_dicts)
        collections = build_collections(eidolons)
        return {
            **profiles_payload(conn),
            "summary": build_summary(eidolons, item_dicts, collections),
            "eidolons": eidolons,
            "items": item_dicts,
            "collections": collections,
        }


def set_eidolon(eidolon_id: int, payload: dict) -> None:
    flags = {key: 1 if value else 0 for key, value in payload.items() if key in {"owned", "completed"}}
    note = str(payload.get("character_note", ""))[:500] if "character_note" in payload else None
    star_rating = None
    if "star_rating" in payload:
        try:
            star_rating = max(0, min(int(payload.get("star_rating", 0) or 0), 4))
        except (TypeError, ValueError):
            star_rating = 0
    if not flags and note is None and star_rating is None:
        return
    with connect() as conn:
        profile_id = get_current_profile_id(conn)
        if flags:
            assignments = ", ".join(f"{key} = ?" for key in flags)
            values = list(flags.values()) + [eidolon_id, profile_id]
            conn.execute(f"UPDATE eidolons SET {assignments} WHERE id = ? AND profile_id = ?", values)
        if star_rating is not None:
            conn.execute(
                "UPDATE eidolons SET star_rating = ?, owned = CASE WHEN ? > 0 THEN 1 ELSE owned END WHERE id = ? AND profile_id = ?",
                (star_rating, star_rating, eidolon_id, profile_id),
            )
        if flags.get("owned") == 0:
            conn.execute("UPDATE eidolons SET completed = 0, star_rating = 0 WHERE id = ? AND profile_id = ?", (eidolon_id, profile_id))
            conn.execute(
                """
                DELETE FROM item_progress
                WHERE item_id IN (
                    SELECT id
                    FROM wish_items
                    WHERE eidolon_id = ?
                )
                """,
                (eidolon_id,),
            )
        if note is not None:
            conn.execute(
                "UPDATE eidolons SET character_note = ? WHERE id = ? AND profile_id = ? AND name IN (%s)"
                % ",".join("?" for _ in STARTER_EIDOLON_NAMES),
                [note, eidolon_id, profile_id, *STARTER_EIDOLON_NAMES],
            )
        if flags.get("completed") == 1:
            conn.execute("UPDATE eidolons SET owned = 1 WHERE id = ? AND profile_id = ?", (eidolon_id, profile_id))
            item_rows = conn.execute(
                """
                SELECT w.id
                FROM wish_items w
                JOIN eidolons e ON e.id = w.eidolon_id
                WHERE w.eidolon_id = ? AND e.profile_id = ?
                """,
                (eidolon_id, profile_id),
            ).fetchall()
            for row in item_rows:
                conn.execute(
                    """
                    INSERT INTO item_progress (item_id, completed)
                    VALUES (?, 1)
                    ON CONFLICT(item_id) DO UPDATE SET completed = 1
                    """,
                    (row["id"],),
                )


def set_item(item_id: int, completed: bool) -> None:
    with connect() as conn:
        profile_id = get_current_profile_id(conn)
        item_row = conn.execute(
            """
            SELECT w.id, w.eidolon_id
            FROM wish_items w
            JOIN eidolons e ON e.id = w.eidolon_id
            WHERE w.id = ? AND e.profile_id = ?
            """,
            (item_id, profile_id),
        ).fetchone()
        if item_row is None:
            raise ValueError("Item not found.")
        conn.execute(
            """
            INSERT INTO item_progress (item_id, completed)
            VALUES (?, ?)
            ON CONFLICT(item_id) DO UPDATE SET completed = excluded.completed
            """,
            (item_id, 1 if completed else 0),
        )
        eidolon_id = item_row["eidolon_id"]
        counts = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN COALESCE(p.completed, 0) = 1 THEN 1 ELSE 0 END) AS done
            FROM wish_items w
            LEFT JOIN item_progress p ON p.item_id = w.id
            WHERE w.eidolon_id = ?
            """,
            (eidolon_id,),
        ).fetchone()
        if counts["total"] and counts["total"] == (counts["done"] or 0):
            conn.execute("UPDATE eidolons SET owned = 1, completed = 1 WHERE id = ? AND profile_id = ?", (eidolon_id, profile_id))
        elif not completed:
            conn.execute("UPDATE eidolons SET completed = 0 WHERE id = ? AND profile_id = ?", (eidolon_id, profile_id))


def apply_bulk_action(action: str) -> None:
    with connect() as conn:
        profile_id = get_current_profile_id(conn)
        if action == "own_all":
            conn.execute("UPDATE eidolons SET owned = 1 WHERE profile_id = ?", (profile_id,))
            return

        if action == "star_all_1":
            conn.execute("UPDATE eidolons SET owned = 1, star_rating = 1 WHERE profile_id = ?", (profile_id,))
            return

        if action == "star_all_4":
            conn.execute("UPDATE eidolons SET owned = 1, star_rating = 4 WHERE profile_id = ?", (profile_id,))
            return

        if action == "complete_all":
            conn.execute("UPDATE eidolons SET owned = 1, completed = 1, star_rating = CASE WHEN star_rating = 0 THEN 4 ELSE star_rating END WHERE profile_id = ?", (profile_id,))
            conn.execute(
                """
                INSERT OR REPLACE INTO item_progress (item_id, completed)
                SELECT w.id, 1
                FROM wish_items w
                JOIN eidolons e ON e.id = w.eidolon_id
                WHERE e.profile_id = ?
                """,
                (profile_id,),
            )
            return

        if action == "clear_wishes":
            conn.execute(
                """
                DELETE FROM item_progress
                WHERE item_id IN (
                    SELECT w.id
                    FROM wish_items w
                    JOIN eidolons e ON e.id = w.eidolon_id
                    WHERE e.profile_id = ?
                )
                """,
                (profile_id,),
            )
            conn.execute("UPDATE eidolons SET completed = 0 WHERE profile_id = ?", (profile_id,))
            return

        if action == "starter_only":
            conn.execute(
                """
                DELETE FROM item_progress
                WHERE item_id IN (
                    SELECT w.id
                    FROM wish_items w
                    JOIN eidolons e ON e.id = w.eidolon_id
                    WHERE e.profile_id = ?
                )
                """,
                (profile_id,),
            )
            conn.execute(
                "UPDATE eidolons SET owned = CASE WHEN name IN ({0}) THEN 1 ELSE 0 END, completed = 0, star_rating = CASE WHEN name IN ({0}) THEN star_rating ELSE 0 END WHERE profile_id = ?".format(
                    ",".join("?" for _ in STARTER_EIDOLON_NAMES)
                ),
                [*STARTER_EIDOLON_NAMES, *STARTER_EIDOLON_NAMES, profile_id],
            )
            return

        raise ValueError(f"Unknown bulk action: {action}")


def item_tiers_for_eidolon(conn: sqlite3.Connection, eidolon_id: int) -> list[tuple[int, int]]:
    rows = conn.execute(
        """
        SELECT id, wish_group
        FROM wish_items
        WHERE eidolon_id = ?
        ORDER BY sort_order
        """,
        (eidolon_id,),
    ).fetchall()
    tier = 0
    item_tiers = []
    for row in rows:
        if (row["wish_group"] or "").strip():
            tier += 1
        elif tier == 0:
            tier = 1
        item_tiers.append((row["id"], tier))
    return item_tiers


def apply_quick_setup(entries: list[dict]) -> None:
    if not isinstance(entries, list):
        raise ValueError("Quick setup requires an eidolons list.")

    with connect() as conn:
        profile_id = get_current_profile_id(conn)
        valid_ids = {
            row["id"]
            for row in conn.execute(
                """
                SELECT id
                FROM eidolons
                WHERE profile_id = ?
                """,
                (profile_id,),
            )
        }
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            eidolon_id = int(entry.get("id", 0) or 0)
            if eidolon_id not in valid_ids:
                continue

            owned = 1 if entry.get("owned") else 0
            wish_tier = max(0, min(int(entry.get("wish_tier", 0) or 0), 6))
            mark_completed = 1 if entry.get("completed") else 0
            star_rating = max(0, min(int(entry.get("star_rating", 0) or 0), 4))
            if not owned:
                wish_tier = 0
                mark_completed = 0
                star_rating = 0
            elif star_rating > 0:
                owned = 1

            item_tiers = item_tiers_for_eidolon(conn, eidolon_id)
            max_tier = max((tier for _, tier in item_tiers), default=0)
            completed = 1 if owned and mark_completed and max_tier else 0

            conn.execute(
                """
                UPDATE eidolons
                SET owned = ?, completed = ?, star_rating = ?
                WHERE id = ? AND profile_id = ?
                """,
                (owned, completed, star_rating, eidolon_id, profile_id),
            )
            conn.execute(
                """
                DELETE FROM item_progress
                WHERE item_id IN (
                    SELECT id
                    FROM wish_items
                    WHERE eidolon_id = ?
                )
                """,
                (eidolon_id,),
            )
            completed_ids = [
                item_id
                for item_id, tier in item_tiers
                if owned and ((completed and tier <= max_tier) or (not completed and tier < wish_tier))
            ]
            if completed_ids:
                conn.executemany(
                    """
                    INSERT INTO item_progress (item_id, completed)
                    VALUES (?, 1)
                    ON CONFLICT(item_id) DO UPDATE SET completed = 1
                    """,
                    [(item_id,) for item_id in completed_ids],
                )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        stream = getattr(sys, "stdout", None)
        if stream is None:
            return
        try:
            stream.write("%s - %s\n" % (self.address_string(), fmt % args))
        except (OSError, RuntimeError, AttributeError):
            return

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return b""
        return self.rfile.read(length)

    def send_database_backup(self) -> None:
        ensure_database_file()
        body = DB_PATH.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{backup_download_name()}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self.send_json(200, get_payload())
            return
        if parsed.path == "/api/backup/download":
            try:
                self.send_database_backup()
            except Exception as exc:
                self.send_json(400, {"error": str(exc)})
            return
        if parsed.path == "/":
            self.serve_file(STATIC / "index.html")
            return
        self.serve_file(STATIC / parsed.path.lstrip("/"))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        try:
            if len(parts) == 2 and parts == ["api", "shutdown"]:
                self.send_json(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if len(parts) == 3 and parts == ["api", "backup", "restore"]:
                self.send_json(200, restore_tracker_database(self.read_body()))
                return
            payload = self.read_json()
            if len(parts) == 3 and parts[:2] == ["api", "eidolons"]:
                set_eidolon(int(parts[2]), payload)
                self.send_json(200, get_payload())
                return
            if len(parts) == 3 and parts[:2] == ["api", "items"]:
                set_item(int(parts[2]), bool(payload.get("completed")))
                self.send_json(200, get_payload())
                return
            if len(parts) == 2 and parts == ["api", "bulk"]:
                apply_bulk_action(str(payload.get("action", "")))
                self.send_json(200, get_payload())
                return
            if len(parts) == 2 and parts == ["api", "quick-setup"]:
                apply_quick_setup(payload.get("eidolons", []))
                self.send_json(200, get_payload())
                return
            if len(parts) == 2 and parts == ["api", "profiles"]:
                create_profile(str(payload.get("name", "")))
                self.send_json(200, get_payload())
                return
            if len(parts) == 3 and parts == ["api", "profiles", "active"]:
                switch_profile(int(payload.get("id", 0) or 0))
                self.send_json(200, get_payload())
                return
            if len(parts) == 3 and parts[:2] == ["api", "profiles"]:
                rename_profile(int(parts[2]), str(payload.get("name", "")))
                self.send_json(200, get_payload())
                return
        except Exception as exc:
            self.send_json(400, {"error": str(exc)})
            return
        self.send_json(404, {"error": "Not found"})

    def serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file() or STATIC not in path.resolve().parents:
            self.send_json(404, {"error": "Not found"})
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Eidolon wish tracker")
    parser.add_argument("--workbook", type=Path, default=None)
    parser.add_argument("--reference-workbook", type=Path, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reset-data", action="store_true", help="Reset local tracker data from the built-in defaults.")
    parser.add_argument("--reimport", action="store_true", help="Developer tool: replace data from a workbook passed with --workbook.")
    parser.add_argument("--import-only", action="store_true")
    parser.add_argument("--sync-assets", action="store_true", help="Fetch Eidolon and wish item image URLs from AuraKingdom-DB.")
    parser.add_argument(
        "--sync-missing-items",
        action="store_true",
        help="Search AuraKingdom-DB for missing item image URLs without refetching Eidolon pages.",
    )
    parser.add_argument(
        "--cache-images",
        action="store_true",
        help="Download remote image URLs into static/img and update the database to use local files.",
    )
    parser.add_argument(
        "--merge-live-progress",
        action="store_true",
        help="Rebuild from the full reference workbook and infer completed rows from the live workbook.",
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if args.merge_live_progress:
        if args.workbook is None or args.reference_workbook is None:
            raise SystemExit("Pass both --reference-workbook PATH and --workbook PATH for merge-live-progress.")
        workbook = args.workbook
        reference_workbook = args.reference_workbook
        if not workbook.exists():
            raise SystemExit(f"Live workbook not found. Pass --workbook PATH. Checked: {workbook}")
        if not reference_workbook.exists():
            raise SystemExit(f"Reference workbook not found. Pass --reference-workbook PATH. Checked: {reference_workbook}")
        counts = rebuild_from_reference(reference_workbook, workbook)
        safe_print(
            "Merged full reference data: "
            f"{counts['eidolons']} Eidolons, {counts['items']} wish items, "
            f"{counts['inferred_completed_items']} completed items inferred from live sheet."
        )
    elif args.reimport:
        if args.workbook is None:
            raise SystemExit("Pass --workbook PATH with --reimport.")
        if not args.workbook.exists():
            raise SystemExit(f"Workbook not found. Checked: {args.workbook}")
        counts = import_workbook(args.workbook, force=True)
        safe_print(f"Loaded {counts['eidolons']} Eidolons and {counts['items']} wish items.")
    else:
        if DB_PATH.exists() and not args.reimport:
            init_db()
            counts = refresh_seed_data()
        else:
            counts = seed_database(force=args.reset_data)
        if args.reset_data:
            counts = seed_database(force=True)
            counts = refresh_seed_data(force=True)
        safe_print(f"Loaded {counts['eidolons']} Eidolons and {counts['items']} wish items.")
    if args.sync_assets:
        asset_counts = sync_assets()
        safe_print(
            f"Matched images for {asset_counts['eidolons']} Eidolons and {asset_counts['items']} wish items. "
            f"Fallback item search filled {asset_counts['fallback_items']} rows from "
            f"{asset_counts['fallback_searched']} unique item searches."
        )
    if args.sync_missing_items:
        asset_counts = sync_missing_item_assets()
        safe_print(
            f"Fallback item search filled {asset_counts['items']} rows from "
            f"{asset_counts['searched']} unique item searches."
        )
    if args.cache_images:
        cache_counts = cache_remote_images()
        safe_print(
            f"Cached {cache_counts['downloaded']} images locally "
            f"({cache_counts['skipped']} skipped, {cache_counts['failed']} failed)."
        )
    if args.import_only:
        return

    url = f"http://{args.host}:{args.port}"
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        if is_address_in_use_error(exc):
            if tracker_server_running(args.host, args.port):
                safe_print(f"Eidolon tracker is already running at {url}")
                if not args.no_browser:
                    webbrowser.open(url)
                return
            raise SystemExit(
                f"Port {args.port} is already in use by another app. "
                "Close the other app or start Eidolon Tracker with --port <number>."
            ) from exc
        raise

    safe_print(f"Eidolon tracker running at {url}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        safe_print("\nStopping server.")
    finally:
        server.server_close()
        safe_print("Server stopped.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        safe_log(f"Fatal error: {type(exc).__name__}: {exc}")
        safe_log(traceback.format_exc())
        raise
