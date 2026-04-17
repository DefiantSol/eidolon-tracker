"""Compare tracker wishes with Aura Kingdom client tables.

The useful client tables are:
- data/db/t_partner.ini: English partner/Eidolon names by partner id.
- data/db/partnermission.ini: wish level rows and required item ids.
- data/db/t_item.ini: English item names by item id.

By default this only prints a report. Use --sync-db-assets to update the
runtime tracker.db with image/detail URLs found on AuraKingdom-DB Eidolon pages.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app  # noqa: E402

CLIENT_DATA_ENV = "EIDOLON_CLIENT_DATA"
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
    args = parser.parse_args()
    if args.data_dir is None:
        parser.error(f"--data-dir is required unless {CLIENT_DATA_ENV} is set.")

    item_names = load_items(args.data_dir)
    partners = load_partners(args.data_dir)
    wishes_by_partner = load_wishes(args.data_dir, item_names)
    report(partners, wishes_by_partner)
    if args.sync_db_assets:
        sync_db_assets(partners, wishes_by_partner)


if __name__ == "__main__":
    main()
