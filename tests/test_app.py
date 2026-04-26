import tempfile
import unittest
from pathlib import Path
import sqlite3

import app


class ClosingConnection:
    def __init__(self, connection):
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __enter__(self):
        return self._connection

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self._connection.close()
        return False


class TrackerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.temp_path = Path(self.temp_dir.name)

        self.original_user_data_dir = app.USER_DATA_DIR
        self.original_db_path = app.DB_PATH
        self.original_log_path = app.LOG_PATH
        self.original_updates_dir = app.UPDATES_DIR
        self.original_connect = app.connect

        app.USER_DATA_DIR = self.temp_path
        app.DB_PATH = self.temp_path / "tracker.db"
        app.LOG_PATH = self.temp_path / "tracker.log"
        app.UPDATES_DIR = self.temp_path / "updates"
        app.connect = self.make_connection

        app.init_db()

    def tearDown(self):
        app.USER_DATA_DIR = self.original_user_data_dir
        app.DB_PATH = self.original_db_path
        app.LOG_PATH = self.original_log_path
        app.UPDATES_DIR = self.original_updates_dir
        app.connect = self.original_connect

    def make_connection(self):
        app.prepare_runtime_storage()
        conn = sqlite3.connect(app.DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return ClosingConnection(conn)

    def create_eidolon(self, name="Test Eidolon", owned=1, completed=0, star_rating=1, sort_order=0):
        with app.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO eidolons (
                    profile_id, name, source_row, owned, completed, star_rating, sort_order,
                    image_url, icon_url, detail_url, character_note, client_partner_id, client_name
                )
                VALUES (1, ?, 1, ?, ?, ?, ?, '', '', '', '', 0, '')
                """,
                (name, owned, completed, star_rating, sort_order),
            )
            return cursor.lastrowid

    def add_item(self, eidolon_id, sort_order, wish_group, item, completed=0):
        with app.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO wish_items (
                    eidolon_id, wish_group, item, item_quality_code, quantity_text, quantity_value,
                    how_to_obtain, source_row, sort_order, image_url, detail_url
                )
                VALUES (?, ?, ?, '', '1', 1, '', ?, ?, '', '')
                """,
                (eidolon_id, wish_group, item, sort_order + 1, sort_order),
            )
            item_id = cursor.lastrowid
            conn.execute(
                """
                INSERT INTO item_progress (item_id, completed)
                VALUES (?, ?)
                ON CONFLICT(item_id) DO UPDATE SET completed = excluded.completed
                """,
                (item_id, completed),
            )
            return item_id

    def payload(self):
        return app.get_payload()


class ApplyWishMetricsTests(TrackerTestCase):
    def test_repeated_group_labels_do_not_increment_tier(self):
        eidolons = [{"id": 1}]
        items = [
            {"eidolon_id": 1, "wish_group": "Tier I", "sort_order": 0, "completed": 1},
            {"eidolon_id": 1, "wish_group": "Tier I", "sort_order": 1, "completed": 0},
            {"eidolon_id": 1, "wish_group": "Tier II", "sort_order": 2, "completed": 0},
        ]

        app.apply_wish_metrics(eidolons, items)

        self.assertEqual(items[0]["wish_tier"], 1)
        self.assertEqual(items[1]["wish_tier"], 1)
        self.assertEqual(items[2]["wish_tier"], 2)
        self.assertEqual(eidolons[0]["wish_count"], 2)
        self.assertEqual(eidolons[0]["completed_wish_tier"], 0)
        self.assertEqual(eidolons[0]["current_wish_tier"], 1)


class QuickSetupTests(TrackerTestCase):
    def setUp(self):
        super().setUp()
        self.eidolon_id = self.create_eidolon(name="Grimm (Zhulong)", owned=1, completed=0, star_rating=1)
        self.tier1_item1 = self.add_item(self.eidolon_id, 0, "Tier I", "Item 1A", completed=1)
        self.tier1_item2 = self.add_item(self.eidolon_id, 1, "Tier I", "Item 1B", completed=1)
        self.tier2_item1 = self.add_item(self.eidolon_id, 2, "Tier II", "Item 2A", completed=1)
        self.tier2_item2 = self.add_item(self.eidolon_id, 3, "Tier II", "Item 2B", completed=0)
        self.tier3_item1 = self.add_item(self.eidolon_id, 4, "Tier III", "Item 3A", completed=0)

    def test_quick_setup_preserves_partial_progress_in_current_tier(self):
        app.apply_quick_setup(
            [
                {
                    "id": self.eidolon_id,
                    "owned": True,
                    "star_rating": 3,
                    "wish_tier": 2,
                    "completed": False,
                }
            ]
        )

        with app.connect() as conn:
            progress = {
                row["item_id"]: row["completed"]
                for row in conn.execute("SELECT item_id, completed FROM item_progress").fetchall()
            }
            eidolon = conn.execute(
                "SELECT owned, completed, star_rating FROM eidolons WHERE id = ?",
                (self.eidolon_id,),
            ).fetchone()

        self.assertEqual(progress[self.tier1_item1], 1)
        self.assertEqual(progress[self.tier1_item2], 1)
        self.assertEqual(progress[self.tier2_item1], 1)
        self.assertEqual(progress[self.tier2_item2], 0)
        self.assertEqual(progress[self.tier3_item1], 0)
        self.assertEqual(eidolon["owned"], 1)
        self.assertEqual(eidolon["completed"], 0)
        self.assertEqual(eidolon["star_rating"], 3)

    def test_quick_setup_owned_star_defaults_to_one(self):
        app.apply_quick_setup(
            [
                {
                    "id": self.eidolon_id,
                    "owned": True,
                    "star_rating": 0,
                    "wish_tier": 1,
                    "completed": False,
                }
            ]
        )

        with app.connect() as conn:
            eidolon = conn.execute(
                "SELECT owned, star_rating FROM eidolons WHERE id = ?",
                (self.eidolon_id,),
            ).fetchone()

        self.assertEqual(eidolon["owned"], 1)
        self.assertEqual(eidolon["star_rating"], 1)


class BulkMutationTests(TrackerTestCase):
    def setUp(self):
        super().setUp()
        self.eidolon_id = self.create_eidolon(name="Bulk Test", owned=0, completed=0, star_rating=0)
        self.item1 = self.add_item(self.eidolon_id, 0, "Tier I", "Bulk Item 1", completed=0)
        self.item2 = self.add_item(self.eidolon_id, 1, "Tier I", "Bulk Item 2", completed=0)

    def test_set_eidolons_bulk_updates_star_and_ownership(self):
        app.set_eidolons_bulk(
            [
                {
                    "id": self.eidolon_id,
                    "owned": True,
                    "star_rating": 4,
                }
            ]
        )

        with app.connect() as conn:
            eidolon = conn.execute(
                "SELECT owned, star_rating FROM eidolons WHERE id = ?",
                (self.eidolon_id,),
            ).fetchone()

        self.assertEqual(eidolon["owned"], 1)
        self.assertEqual(eidolon["star_rating"], 4)

    def test_set_items_bulk_completes_eidolon_when_all_items_done(self):
        app.set_items_bulk(
            [
                {"id": self.item1, "completed": True},
                {"id": self.item2, "completed": True},
            ]
        )

        with app.connect() as conn:
            eidolon = conn.execute(
                "SELECT owned, completed FROM eidolons WHERE id = ?",
                (self.eidolon_id,),
            ).fetchone()

        self.assertEqual(eidolon["owned"], 1)
        self.assertEqual(eidolon["completed"], 1)


class InventoryTests(TrackerTestCase):
    def setUp(self):
        super().setUp()
        self.eidolon_id = self.create_eidolon(name="Inventory Test", owned=1, completed=0, star_rating=1)
        self.item_id = self.add_item(self.eidolon_id, 0, "Tier I", "Enhanced Reinforcing Pliers", completed=0)

    def test_inventory_quantity_is_saved_in_payload(self):
        app.set_inventory_quantity("Enhanced Reinforcing Pliers", 12)
        payload = self.payload()
        inventory = {entry["item_key"]: entry["quantity"] for entry in payload["inventory"]}
        self.assertEqual(inventory["enhanced reinforcing pliers"], 12)

    def test_inventory_does_not_complete_wishes(self):
        app.set_inventory_quantity("Enhanced Reinforcing Pliers", 99)
        payload = self.payload()
        eidolon = next(row for row in payload["eidolons"] if row["id"] == self.eidolon_id)
        item = next(row for row in payload["items"] if row["id"] == self.item_id)

        self.assertEqual(item["completed"], 0)
        self.assertEqual(eidolon["completed_wish_tier"], 0)
        self.assertEqual(eidolon["current_wish_tier"], 1)

    def test_inventory_zero_removes_row(self):
        app.set_inventory_quantity("Enhanced Reinforcing Pliers", 3)
        app.set_inventory_quantity("Enhanced Reinforcing Pliers", 0)
        payload = self.payload()
        self.assertEqual(payload["inventory"], [])

    def test_set_item_completed_consumes_inventory(self):
        app.set_inventory_quantity("Enhanced Reinforcing Pliers", 12)
        app.set_item(self.item_id, True)
        payload = self.payload()
        inventory = {entry["item_key"]: entry["quantity"] for entry in payload["inventory"]}
        self.assertEqual(inventory["enhanced reinforcing pliers"], 11)

    def test_restore_does_not_add_inventory_back(self):
        app.set_inventory_quantity("Enhanced Reinforcing Pliers", 1)
        app.set_item(self.item_id, True)
        app.set_item(self.item_id, False)
        payload = self.payload()
        self.assertEqual(payload["inventory"], [])


if __name__ == "__main__":
    unittest.main()
