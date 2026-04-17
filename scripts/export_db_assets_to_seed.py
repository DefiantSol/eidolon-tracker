"""Copy image/detail URLs from tracker.db into data/seed.json.

This intentionally copies only asset metadata. It does not copy owned,
completed, or starter character notes into the release seed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app  # noqa: E402


def main() -> None:
    app.init_db()
    seed = json.loads(app.SEED_PATH.read_text(encoding="utf-8"))

    with app.connect() as conn:
        eidolons = {
            row["name"]: row
            for row in conn.execute("SELECT name, image_url, icon_url, detail_url FROM eidolons")
        }
        items = {
            (row["eidolon_name"], app.normalize_name(row["item"])): row
            for row in conn.execute(
                """
                SELECT e.name AS eidolon_name, w.item, w.image_url, w.detail_url
                FROM wish_items w
                JOIN eidolons e ON e.id = w.eidolon_id
                """
            )
        }

    eidolon_updates = 0
    item_updates = 0
    for eidolon in seed["eidolons"]:
        saved_eidolon = eidolons.get(eidolon["name"])
        if saved_eidolon:
            for key in ("image_url", "icon_url", "detail_url"):
                value = saved_eidolon[key] or ""
                if value and eidolon.get(key, "") != value:
                    eidolon[key] = value
                    eidolon_updates += 1

        for item in eidolon["items"]:
            saved_item = items.get((eidolon["name"], app.normalize_name(item["item"])))
            if not saved_item:
                continue
            for key in ("image_url", "detail_url"):
                value = saved_item[key] or ""
                if value and item.get(key, "") != value:
                    item[key] = value
                    item_updates += 1

    app.SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Updated seed assets: {eidolon_updates} Eidolon fields, {item_updates} item fields")


if __name__ == "__main__":
    main()
