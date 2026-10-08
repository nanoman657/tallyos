import os

TEST_DB = os.environ.get("TALLYOS_TEST_DATABASE_URL", "postgresql://tallyos:tallyos@localhost:5432/tallyos_test")
os.environ["DATABASE_URL"] = TEST_DB   # before app.config is imported anywhere

import pytest  # noqa: E402

from app.cli import reset_schema  # noqa: E402
from app.db import Db, connect, init_schema  # noqa: E402
from app.seed import seed_catalog  # noqa: E402


@pytest.fixture
def db():
    reset_schema(TEST_DB)
    conn = connect(TEST_DB)
    init_schema(conn)
    d = Db(conn)
    seed_catalog(d)
    conn.commit()
    yield d
    conn.rollback()
    conn.close()
