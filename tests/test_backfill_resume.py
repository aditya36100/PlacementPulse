import os
import tempfile
import unittest

from app import db


class TestBackfillResume(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.temp_file.close()
        db.DB_PATH = self.temp_file.name
        db.init_db()

    def tearDown(self):
        os.unlink(self.temp_file.name)

    def test_last_backfill_id_persists_per_group(self):
        self.assertEqual(db.get_last_backfill_id("group_a"), 0)

        db.set_last_backfill_id("group_a", 123)
        db.set_last_backfill_id("group_b", 456)

        self.assertEqual(db.get_last_backfill_id("group_a"), 123)
        self.assertEqual(db.get_last_backfill_id("group_b"), 456)

        db.set_last_backfill_id("group_a", 789)
        self.assertEqual(db.get_last_backfill_id("group_a"), 789)


if __name__ == "__main__":
    unittest.main()
