from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.database import make_engine
from app.models import Base


def test_upgrade_downgrade_upgrade_and_metadata(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = make_engine(url)
    with engine.connect() as connection:
        tables = inspect(connection).get_table_names()
        assert set(tables) == {
            "alembic_version",
            "campaigns",
            "streams",
            "offers",
            "stream_offers",
            "creation_operations",
        }
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    engine.dispose()
    command.downgrade(config, "base")
    engine = make_engine(url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()
    command.upgrade(config, "head")
