import pytest

from app.database import make_engine, make_sessions
from app.models import Base
from tests.fakes import FakeTracker


@pytest.fixture
def tracker():
    remote = FakeTracker()
    yield remote
    remote.client.close()


@pytest.fixture
def sessions(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield make_sessions(engine)
    engine.dispose()


@pytest.fixture
def db(sessions):
    with sessions() as session:
        yield session
