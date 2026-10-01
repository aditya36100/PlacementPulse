import os
import tempfile
import unittest

from app import db


class TestInstanceLock(unittest.TestCase):
    def test_instance_lock_blocks_second_process(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, "app.lock")
            fd = db.acquire_instance_lock(lock_path)

            self.assertIsNotNone(fd)

            with self.assertRaises(RuntimeError):
                db.acquire_instance_lock(lock_path)

            db.release_instance_lock(fd)


if __name__ == "__main__":
    unittest.main()
