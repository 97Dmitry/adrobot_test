from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


def make_engine(url: str):
    options = (
        {"connect_args": {"check_same_thread": False, "timeout": 20}}
        if url.startswith("sqlite")
        else {}
    )
    engine = create_engine(url, **options)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_sessions(engine):
    return sessionmaker(engine, expire_on_commit=False)
