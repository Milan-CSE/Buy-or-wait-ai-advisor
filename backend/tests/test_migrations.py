"""
Tests verifying Alembic migrations from empty DB to head and rollback to base.
"""
import unittest
import os
import uuid
from alembic import command
from alembic.config import Config
from backend.database.session import get_engine, Base


class TestMigrations(unittest.TestCase):
    def setUp(self):
        self.db_path = f"d:/hacker_rank_projectt/test_mig_{uuid.uuid4().hex[:8]}.db"
        self.db_url = f"sqlite:///{self.db_path}"
        os.environ["DATABASE_URL"] = self.db_url
        self.alembic_cfg = Config("alembic.ini")
        self.alembic_cfg.set_main_option("sqlalchemy.url", self.db_url)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_upgrade_and_downgrade_lifecycle(self):
        """Verify migration upgrade head and downgrade base execute cleanly from empty DB."""
        # 1. Upgrade from zero
        command.upgrade(self.alembic_cfg, "head")
        engine = get_engine(self.db_url)
        with engine.connect() as conn:
            from sqlalchemy import inspect
            inspector = inspect(conn)
            tables = set(inspector.get_table_names())
            expected = {
                "users", "financial_profiles", "financial_accounts",
                "import_batches", "transactions", "purchase_requests",
                "decisions", "audit_events", "alembic_version"
            }
            self.assertTrue(expected.issubset(tables), f"Missing tables: {expected - tables}")
        engine.dispose()

        # 2. Downgrade back to base
        command.downgrade(self.alembic_cfg, "base")
        engine = get_engine(self.db_url)
        with engine.connect() as conn:
            from sqlalchemy import inspect
            inspector = inspect(conn)
            tables = set(inspector.get_table_names())
            self.assertNotIn("users", tables)
            self.assertNotIn("transactions", tables)
        engine.dispose()


if __name__ == '__main__':
    unittest.main()
