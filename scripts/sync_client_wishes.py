"""Compare tracker wishes with Aura Kingdom client tables.

The useful client tables are:
- data/db/t_partner.ini: English partner/Eidolon names by partner id.
- data/db/partnermission.ini: wish level rows and required item ids.
- data/db/t_item.ini: English item names by item id.

By default this only prints a report. Use --sync-seed-wishes to update
data/seed.json from the decoded client wish table, and --sync-seed-workbook
to refresh wish names/quantities/descriptions from the reference workbook.
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app  # noqa: E402

CLIENT_DATA_ENV = "EIDOLON_CLIENT_DATA"
GOOGLE_API_KEY_ENV = "GOOGLE_API_KEY"
ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI"}


@dataclass
class ClientItem:
    ids: list[int]
    quantity: str
    name: str


@dataclass
class ClientWish:
    partner_id: int
    level: int
    group: str
    items: list[ClientItem]


@dataclass
class ClientPartner:
    partner_id: int
    title: str
    name: str


def split_row(line: str) -> list[str]:
    return [part.strip() for part in line.rstrip("\n").split("|")]


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\$[0-9]+\$", "", value)
    value = re.sub(r"#IMG\$[^#]+#", "", value)
    return value.strip().strip('"')


def load_items(data_dir: Path) -> dict[int, str]:
    items: dict[int, str] = {}
    for raw in (data_dir / "t_item.ini").read_text(encoding="utf-8", errors="ignore").splitlines():
        cols = split_row(raw)
        if len(cols) < 2 or not cols[0].isdigit():
            continue
        items[int(cols[0])] = clean_text(cols[1])
    return items


def load_partners(data_dir: Path) -> dict[int, ClientPartner]:
    partners: dict[int, ClientPartner] = {}
    for raw in (data_dir / "t_partner.ini").read_text(encoding="utf-8", errors="ignore").splitlines():
        cols = split_row(raw)
        if len(cols) < 3 or not cols[0].isdigit():
            continue
        partners[int(cols[0])] = ClientPartner(
            partner_id=int(cols[0]),
            title=clean_text(cols[1]),
            name=clean_text(cols[2]),
        )
    return partners


def item_name_for_ids(item_ids: list[int], item_names: dict[int, str]) -> str:
    names = [item_names.get(item_id, str(item_id)) for item_id in item_ids]
    if len(names) == 1:
        return names[0]
    if len(names) <= 4:
        return " / ".join(names)
    return f"{len(names)} possible items"


def parse_item_ids(raw: str) -> list[int]:
    ids = []
    for piece in raw.split(";"):
        piece = piece.strip()
        if piece.isdigit():
            ids.append(int(piece))
    return ids


def load_wishes(data_dir: Path, item_names: dict[int, str]) -> dict[int, list[ClientWish]]:
    by_partner: dict[int, list[ClientWish]] = {}
    for raw in (data_dir / "partnermission.ini").read_text(encoding="utf-8", errors="ignore").splitlines():
        cols = split_row(raw)
        if len(cols) < 8 or not cols[0].isdigit() or not cols[1].isdigit() or not cols[2].isdigit():
            continue
        partner_id = int(cols[1])
        level = int(cols[2])
        items: list[ClientItem] = []
        for item_col, qty_col in ((6, 7), (8, 9), (10, 11)):
            if item_col >= len(cols) or qty_col >= len(cols):
                continue
            item_ids = parse_item_ids(cols[item_col])
            quantity = cols[qty_col]
            if item_ids and quantity:
                items.append(
                    ClientItem(
                        ids=item_ids,
                        quantity=quantity,
                        name=item_name_for_ids(item_ids, item_names),
                    )
                )
        if items:
            by_partner.setdefault(partner_id, []).append(
                ClientWish(
                    partner_id=partner_id,
                    level=level,
                    group=ROMAN.get(level, str(level)),
                    items=items,
                )
            )
    for wishes in by_partner.values():
        wishes.sort(key=lambda wish: wish.level)
    return by_partner


def seed_eidolon_candidates(name: str) -> set[str]:
    candidates = app.eidolon_name_candidates(name) | {app.normalize_name(value) for value in app.eidolon_display_candidates(name)}
    if app.normalize_name(name) == "lanlan":
        candidates.add(app.normalize_name("Lan Lan Cat"))
    if app.normalize_name(name) == "numakawahime":
        candidates.add(app.normalize_name("Nunakawa-hime"))
    return candidates


def map_seed_eidolons(partners: dict[int, ClientPartner]) -> dict[int, sqlite3.Row]:
    with app.connect() as conn:
        rows = conn.execute("SELECT * FROM eidolons ORDER BY sort_order").fetchall()

    by_candidate: dict[str, sqlite3.Row] = {}
    for row in rows:
        for candidate in seed_eidolon_candidates(row["name"]):
            by_candidate[candidate] = row

    matched: dict[int, sqlite3.Row] = {}
    for partner_id, partner in partners.items():
        for candidate in (partner.name, partner.title, f"{partner.name} ({partner.title})"):
            key = app.normalize_name(candidate)
            if key in by_candidate:
                matched[partner_id] = by_candidate[key]
                break
    return matched


def flatten_client_items(wishes: list[ClientWish]) -> list[tuple[str, ClientItem]]:
    flat: list[tuple[str, ClientItem]] = []
    for wish in wishes:
        for item in wish.items:
            flat.append((wish.group, item))
    return flat


def flatten_client_items_for_seed(wishes: list[ClientWish]) -> list[tuple[str, ClientWish, ClientItem]]:
    flat: list[tuple[str, ClientWish, ClientItem]] = []
    for wish in wishes:
        for index, item in enumerate(wish.items):
            flat.append((wish.group if index == 0 else "", wish, item))
    return flat


def numeric_quantity(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def workbook_item_key(name: str) -> str:
    return app.normalize_name(name)


def sheet_ref_parts(sheet_ref: str) -> tuple[str, str | None]:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_ref)
    if not match:
        raise ValueError(f"Could not parse Google Sheets document id from: {sheet_ref}")
    parsed = urlparse(sheet_ref)
    query = parse_qs(parsed.query)
    gid = query.get("gid", [None])[0]
    fragment_gid = parse_qs(parsed.fragment).get("gid", [None])[0] if parsed.fragment else None
    return match.group(1), gid or fragment_gid


def value_from_grid_cell(cell: dict) -> str:
    if "formattedValue" in cell:
        return str(cell["formattedValue"]).strip()
    effective = cell.get("effectiveValue", {})
    for key in ("stringValue", "numberValue", "boolValue"):
        if key in effective:
            return str(effective[key]).strip()
    return ""


def apply_merge_ranges(rows: dict[int, dict[str, str]], merges: list[dict]) -> None:
    for merge in merges:
        start_row = int(merge.get("startRowIndex", 0)) + 1
        end_row = int(merge.get("endRowIndex", 0))
        start_col_idx = int(merge.get("startColumnIndex", 0)) + 1
        end_col_idx = int(merge.get("endColumnIndex", 0))
        start_col = app.column_name(start_col_idx)
        source = rows.get(start_row, {}).get(start_col, "")
        if not source:
            continue
        for row_number in range(start_row, end_row + 1):
            for column_index in range(start_col_idx, end_col_idx + 1):
                column = app.column_name(column_index)
                if column not in {"A", "B", "C", "D"}:
                    continue
                rows.setdefault(row_number, {}).setdefault(column, source)


def read_google_sheet_abcd(sheet_ref: str, sheet_name: str) -> dict[int, dict[str, str]]:
    spreadsheet_id, gid = sheet_ref_parts(sheet_ref)
    api_key = os.environ.get(GOOGLE_API_KEY_ENV)
    if api_key:
        api_url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
            f"?includeGridData=true&ranges={sheet_name}!A:D&key={api_key}"
        )
        payload = json.loads(app.fetch_url(api_url))
        sheets = payload.get("sheets", [])
        if not sheets:
            raise ValueError(f"No sheet data returned for {sheet_name}")
        sheet = sheets[0]
        grid = (sheet.get("data") or [{}])[0]
        row_data = grid.get("rowData") or []
        rows: dict[int, dict[str, str]] = {}
        for row_index, row in enumerate(row_data, start=1):
            values = {}
            for col_index, cell in enumerate(row.get("values") or [], start=1):
                column = app.column_name(col_index)
                if column not in {"A", "B", "C", "D"}:
                    continue
                values[column] = value_from_grid_cell(cell)
            if values:
                rows[row_index] = values
        apply_merge_ranges(rows, sheet.get("merges") or [])
        return rows

    if gid is None:
        raise ValueError("Google sheet URL must include gid when GOOGLE_API_KEY is not set.")
    export_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=tsv&gid={gid}"
    text = app.fetch_url(export_url)
    rows: dict[int, dict[str, str]] = {}
    for row_index, parts in enumerate(csv.reader(io.StringIO(text), delimiter="\t"), start=1):
        values = {}
        for col_index, value in enumerate(parts[:4], start=1):
            column = app.column_name(col_index)
            values[column] = value.strip()
        if values:
            rows[row_index] = values
    return rows


def client_item_link(item_id: int, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{app.AKDB_BASE}/item/{item_id}-{slug}" if slug else f"{app.AKDB_BASE}/item/{item_id}"


def eidolon_detail_url(partner_id: int, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{app.AKDB_BASE}/eidolon/{partner_id}-{slug}" if slug else f"{app.AKDB_BASE}/eidolon/{partner_id}"


def fetch_eidolon_wish_assets(partner_id: int, name: str) -> dict[int, dict[str, str]]:
    data = app.fetch_url(eidolon_detail_url(partner_id, name))
    wish_start = data.find("Eidolon Wishes")
    wish_html = data[wish_start:] if wish_start >= 0 else data
    assets: dict[int, dict[str, str]] = {}
    pattern = re.compile(
        r'<a[^>]+title="(?P<title>[^"]+)"[^>]+href="/item/(?P<id>\d+)-[^"]+"[^>]*>.*?'
        r'<img[^>]+src="(?P<src>[^"]+)"',
        re.S,
    )
    for match in pattern.finditer(wish_html):
        item_id = int(match.group("id"))
        assets[item_id] = {
            "title": html.unescape(match.group("title")).strip(),
            "detail_url": client_item_link(item_id, html.unescape(match.group("title")).strip()),
            "image_url": match.group("src"),
        }
    return assets


def fetch_eidolon_assets(partner_id: int, name: str) -> dict[str, str]:
    detail_url = eidolon_detail_url(partner_id, name)
    assets = app.parse_detail_assets(detail_url)
    return {
        "detail_url": detail_url,
        "image_url": assets["image_url"],
        "icon_url": assets["icon_url"],
    }


def fetch_item_asset_by_id(item_id: int, name: str) -> dict[str, str] | None:
    detail_url = client_item_link(item_id, name)
    data = app.fetch_url(detail_url)
    match = re.search(r'<img[^>]+src="(?P<src>[^"]*/images/icons/[^"]+)"', data)
    if not match:
        imgs = re.findall(r'<img[^>]+src="([^"]+)"', data)
        src = next((img for img in imgs if "/images/" in img), "")
    else:
        src = match.group("src")
    if not src:
        return None
    title_match = re.search(r"<h1[^>]*>(?P<title>.*?)</h1>", data, re.S)
    title = html.unescape(re.sub(r"<.*?>", "", title_match.group("title")).strip()) if title_match else name
    return {
        "title": title,
        "detail_url": detail_url,
        "image_url": src,
    }


def report(partners: dict[int, ClientPartner], wishes_by_partner: dict[int, list[ClientWish]]) -> None:
    matched = map_seed_eidolons(partners)
    total_wishes = sum(len(wishes_by_partner.get(pid, [])) for pid in matched)
    total_items = sum(len(flatten_client_items(wishes_by_partner.get(pid, []))) for pid in matched)
    print(f"Matched client partners to tracker Eidolons: {len(matched)}")
    print(f"Client wish groups for matched Eidolons: {total_wishes}")
    print(f"Client wish item slots for matched Eidolons: {total_items}")
    print()

    for partner_id in sorted(matched)[:8]:
        partner = partners[partner_id]
        seed_row = matched[partner_id]
        print(f"{partner_id}: {partner.name} -> {seed_row['name']}")
        for wish in wishes_by_partner.get(partner_id, [])[:6]:
            parts = ", ".join(f"{item.name} x{item.quantity} [{';'.join(map(str, item.ids))}]" for item in wish.items)
            print(f"  {wish.group}: {parts}")


def map_seed_entries(seed: dict, partners: dict[int, ClientPartner]) -> dict[int, dict]:
    by_candidate: dict[str, dict] = {}
    for eidolon in seed["eidolons"]:
        for candidate in seed_eidolon_candidates(eidolon["name"]):
            by_candidate[candidate] = eidolon

    matched: dict[int, dict] = {}
    for partner_id, partner in partners.items():
        for candidate in (partner.name, partner.title, f"{partner.name} ({partner.title})"):
            key = app.normalize_name(candidate)
            if key in by_candidate:
                matched[partner_id] = by_candidate[key]
                break
    return matched


def sync_seed_wishes(seed_path: Path, partners: dict[int, ClientPartner], wishes_by_partner: dict[int, list[ClientWish]]) -> None:
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    matched = map_seed_entries(seed, partners)
    updated_eidolons = 0
    updated_items = 0
    rebuilt_length = 0
    missing_wishes = 0

    for partner_id, eidolon in matched.items():
        client_items = flatten_client_items_for_seed(wishes_by_partner.get(partner_id, []))
        seed_items = eidolon.get("items", [])
        if not client_items:
            missing_wishes += 1
            continue
        if len(client_items) != len(seed_items):
            rebuilt_length += 1
            print(
                f"Rebuilt {eidolon['name']}: seed had {len(seed_items)} items, "
                f"client has {len(client_items)}"
            )

        partner = partners[partner_id]
        eidolon["client_partner_id"] = partner_id
        eidolon["client_name"] = partner.name
        changed_eidolon = False
        new_items = []
        for sort_order, (wish_group, client_wish, client_item) in enumerate(client_items):
            seed_item = dict(seed_items[sort_order]) if sort_order < len(seed_items) else {
                "item": client_item.name,
                "how_to_obtain": "",
                "source_row": 0,
                "image_url": "",
                "detail_url": "",
            }
            before = dict(seed_item)
            seed_item["wish_group"] = wish_group
            seed_item["quantity_text"] = client_item.quantity
            seed_item["quantity_value"] = numeric_quantity(client_item.quantity)
            seed_item["sort_order"] = sort_order
            seed_item["client_wish_level"] = client_wish.level
            seed_item["client_item_ids"] = client_item.ids
            seed_item["client_item_name"] = client_item.name
            if len(client_item.ids) == 1:
                seed_item["client_item_id"] = client_item.ids[0]
                seed_item["detail_url"] = client_item_link(client_item.ids[0], client_item.name)
            else:
                seed_item.pop("client_item_id", None)
                if not seed_item.get("detail_url"):
                    seed_item["detail_url"] = client_item_link(client_item.ids[0], client_item.name)
            if seed_item != before:
                updated_items += 1
                changed_eidolon = True
            new_items.append(seed_item)
        if len(new_items) != len(seed_items):
            changed_eidolon = True
        eidolon["items"] = new_items
        if changed_eidolon:
            updated_eidolons += 1

    seed_path.write_text(json.dumps(seed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Matched seed Eidolons: {len(matched)}")
    print(f"Updated seed Eidolons: {updated_eidolons}")
    print(f"Updated seed wish items: {updated_items}")
    print(f"Rebuilt item-count mismatches: {rebuilt_length}")
    print(f"Matched Eidolons without client wishes: {missing_wishes}")


def sync_seed_workbook(seed_path: Path, workbook_path: Path) -> None:
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    workbook_eidolons = {
        eidolon["name"]: eidolon
        for eidolon in app.extract_eidolons(workbook_path)
    }
    updated_eidolons = 0
    updated_items = 0
    unmatched_seed_items = 0
    workbook_only_items = 0

    for eidolon in seed["eidolons"]:
        workbook_eidolon = workbook_eidolons.get(eidolon["name"])
        if not workbook_eidolon:
            continue

        workbook_items = workbook_eidolon.get("items", [])
        available_by_name: dict[str, list[dict]] = {}
        for item in workbook_items:
            available_by_name.setdefault(workbook_item_key(item["item"]), []).append(item)

        new_items = []
        changed = False
        for index, seed_item in enumerate(eidolon.get("items", [])):
            workbook_item = None
            candidates = available_by_name.get(workbook_item_key(seed_item.get("item", "")), [])
            if candidates:
                workbook_item = candidates.pop(0)
            elif index < len(workbook_items):
                workbook_item = workbook_items[index]

            merged_item = dict(seed_item)
            if workbook_item:
                merged_item["wish_group"] = workbook_item.get("wish_group", "")
                merged_item["item"] = workbook_item["item"]
                merged_item["quantity_text"] = workbook_item["quantity_text"] or "1"
                merged_item["quantity_value"] = workbook_item.get("quantity_value")
                merged_item["how_to_obtain"] = workbook_item.get("how_to_obtain", "")
                merged_item["source_row"] = workbook_item["source_row"]
            else:
                unmatched_seed_items += 1
            if merged_item != seed_item:
                updated_items += 1
                changed = True
            new_items.append(merged_item)

        for remaining in available_by_name.values():
            workbook_only_items += len(remaining)
        eidolon["items"] = new_items
        if changed:
            updated_eidolons += 1

    seed_path.write_text(json.dumps(seed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Workbook Eidolons found: {len(workbook_eidolons)}")
    print(f"Updated seed Eidolons from workbook: {updated_eidolons}")
    print(f"Updated seed wish items from workbook: {updated_items}")
    print(f"Unmatched seed items left unchanged: {unmatched_seed_items}")
    print(f"Workbook-only items not inserted: {workbook_only_items}")


def extract_eidolons_from_rows(rows: dict[int, dict[str, str]]) -> list[dict]:
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

        quantity_text, quantity_value = app.format_quantity(c)
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


def sync_seed_google_sheet(seed_path: Path, google_sheet_url: str, sheet_name: str) -> None:
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    workbook_eidolons = {
        eidolon["name"]: eidolon
        for eidolon in extract_eidolons_from_rows(read_google_sheet_abcd(google_sheet_url, sheet_name))
    }
    updated_eidolons = 0
    updated_items = 0
    unmatched_seed_items = 0
    sheet_only_items = 0

    for eidolon in seed["eidolons"]:
        source_eidolon = workbook_eidolons.get(eidolon["name"])
        if not source_eidolon:
            continue
        source_items = source_eidolon.get("items", [])
        available_by_name: dict[str, list[dict]] = {}
        for item in source_items:
            available_by_name.setdefault(workbook_item_key(item["item"]), []).append(item)

        new_items = []
        changed = False
        for index, seed_item in enumerate(eidolon.get("items", [])):
            source_item = None
            candidates = available_by_name.get(workbook_item_key(seed_item.get("item", "")), [])
            if candidates:
                source_item = candidates.pop(0)
            elif index < len(source_items):
                source_item = source_items[index]

            merged_item = dict(seed_item)
            if source_item:
                merged_item["wish_group"] = source_item.get("wish_group", "")
                merged_item["item"] = source_item["item"]
                merged_item["quantity_text"] = source_item["quantity_text"] or "1"
                merged_item["quantity_value"] = source_item.get("quantity_value")
                merged_item["how_to_obtain"] = source_item.get("how_to_obtain", "")
                merged_item["source_row"] = source_item["source_row"]
            else:
                unmatched_seed_items += 1
            if merged_item != seed_item:
                updated_items += 1
                changed = True
            new_items.append(merged_item)

        for remaining in available_by_name.values():
            sheet_only_items += len(remaining)
        eidolon["items"] = new_items
        if changed:
            updated_eidolons += 1

    seed_path.write_text(json.dumps(seed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Google sheet Eidolons found: {len(workbook_eidolons)}")
    print(f"Updated seed Eidolons from Google sheet: {updated_eidolons}")
    print(f"Updated seed wish items from Google sheet: {updated_items}")
    print(f"Unmatched seed items left unchanged: {unmatched_seed_items}")
    print(f"Google-sheet-only items not inserted: {sheet_only_items}")


def sync_db_assets(partners: dict[int, ClientPartner], wishes_by_partner: dict[int, list[ClientWish]]) -> None:
    matched = map_seed_eidolons(partners)
    updated_eidolons = 0
    updated = 0
    direct_item_updates = 0
    fetched = 0
    item_pages_fetched = 0
    missing_pages = 0

    with app.connect() as conn:
        for partner_id, seed_row in matched.items():
            partner = partners[partner_id]
            client_items = flatten_client_items(wishes_by_partner.get(partner_id, []))
            db_items = conn.execute(
                "SELECT * FROM wish_items WHERE eidolon_id = ? ORDER BY sort_order",
                (seed_row["id"],),
            ).fetchall()
            assets: dict[int, dict[str, str]] = {}
            try:
                if not seed_row["image_url"] or not seed_row["icon_url"] or not seed_row["detail_url"]:
                    eidolon_assets = fetch_eidolon_assets(partner_id, partner.name)
                    conn.execute(
                        """
                        UPDATE eidolons
                        SET image_url = CASE WHEN image_url = '' THEN ? ELSE image_url END,
                            icon_url = CASE WHEN icon_url = '' THEN ? ELSE icon_url END,
                            detail_url = CASE WHEN detail_url = '' THEN ? ELSE detail_url END
                        WHERE id = ?
                        """,
                        (
                            eidolon_assets["image_url"],
                            eidolon_assets["icon_url"],
                            eidolon_assets["detail_url"],
                            seed_row["id"],
                        ),
                    )
                    updated_eidolons += 1
                assets = fetch_eidolon_wish_assets(partner_id, partner.name)
                fetched += 1
            except Exception as exc:
                missing_pages += 1
                print(f"Could not fetch {partner_id} {partner.name}: {exc}")
            if not client_items or len(client_items) != len(db_items):
                continue
            for db_item, (_group, client_item) in zip(db_items, client_items):
                concrete_ids = [item_id for item_id in client_item.ids if item_id in assets]
                if not concrete_ids:
                    continue
                asset = assets[concrete_ids[0]]
                if db_item["image_url"] and db_item["detail_url"]:
                    continue
                conn.execute(
                    """
                    UPDATE wish_items
                    SET image_url = CASE WHEN image_url = '' THEN ? ELSE image_url END,
                        detail_url = CASE WHEN detail_url = '' THEN ? ELSE detail_url END
                    WHERE id = ?
                    """,
                    (asset["image_url"], asset["detail_url"], db_item["id"]),
                )
                updated += 1
            for db_item, (_group, client_item) in zip(db_items, client_items):
                if db_item["image_url"] and db_item["detail_url"]:
                    continue
                if len(client_item.ids) > 4:
                    continue
                for item_id in client_item.ids:
                    try:
                        asset = fetch_item_asset_by_id(item_id, db_item["item"])
                        item_pages_fetched += 1
                    except Exception as exc:
                        print(f"Could not fetch item {item_id} {client_item.name}: {exc}")
                        continue
                    if not asset:
                        continue
                    conn.execute(
                        """
                        UPDATE wish_items
                        SET image_url = CASE WHEN image_url = '' THEN ? ELSE image_url END,
                            detail_url = CASE WHEN detail_url = '' THEN ? ELSE detail_url END
                        WHERE id = ?
                        """,
                        (asset["image_url"], asset["detail_url"], db_item["id"]),
                    )
                    direct_item_updates += 1
                    break
    print(f"Fetched Eidolon pages: {fetched}")
    print(f"Fetched direct item pages: {item_pages_fetched}")
    print(f"Pages unavailable: {missing_pages}")
    print(f"Updated DB Eidolon assets: {updated_eidolons}")
    print(f"Updated DB wish item assets: {updated}")
    print(f"Updated DB wish item assets from direct item ids: {direct_item_updates}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ[CLIENT_DATA_ENV]) if os.environ.get(CLIENT_DATA_ENV) else None,
        help=f"Path to ini_plain data/db directory. Can also be set with {CLIENT_DATA_ENV}.",
    )
    parser.add_argument("--sync-db-assets", action="store_true")
    parser.add_argument("--sync-seed-wishes", action="store_true")
    parser.add_argument("--sync-seed-workbook", action="store_true")
    parser.add_argument("--sync-seed-google-sheet", action="store_true")
    parser.add_argument("--seed-path", type=Path, default=ROOT / "data" / "seed.json")
    parser.add_argument("--workbook", type=Path, default=ROOT / "data" / "AKTO References (Compilation).xlsx")
    parser.add_argument("--google-sheet-url", default="")
    parser.add_argument("--sheet-name", default=app.SHEET_NAME)
    args = parser.parse_args()
    if args.data_dir is None:
        parser.error(f"--data-dir is required unless {CLIENT_DATA_ENV} is set.")

    item_names = load_items(args.data_dir)
    partners = load_partners(args.data_dir)
    wishes_by_partner = load_wishes(args.data_dir, item_names)
    report(partners, wishes_by_partner)
    if args.sync_db_assets:
        sync_db_assets(partners, wishes_by_partner)
    if args.sync_seed_wishes:
        sync_seed_wishes(args.seed_path, partners, wishes_by_partner)
    if args.sync_seed_workbook:
        sync_seed_workbook(args.seed_path, args.workbook)
    if args.sync_seed_google_sheet:
        if not args.google_sheet_url:
            parser.error("--google-sheet-url is required with --sync-seed-google-sheet.")
        sync_seed_google_sheet(args.seed_path, args.google_sheet_url, args.sheet_name)


if __name__ == "__main__":
    main()
