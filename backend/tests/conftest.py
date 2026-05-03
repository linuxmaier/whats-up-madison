import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from app.database import Base


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def engine(pg_container):
    eng = create_engine(pg_container.get_connection_url())
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def SessionFactory(engine):
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture
def db(SessionFactory, engine):
    session = SessionFactory()
    yield session
    session.close()
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE event_sources, events RESTART IDENTITY CASCADE"))
        conn.commit()
