# 승인된 MariaDB 스키마를 검증하고 저장소 세션을 구성한다.
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from investment_office.storage import DATABASE_NAME, MARIADB_METADATA, MariaDBStorage


@dataclass(frozen=True, slots=True)
class DatabaseRuntime:
    """실행 중인 MariaDB 연결과 저장소를 함께 보관한다."""

    engine: Engine
    session_factory: sessionmaker[Session]
    storage: MariaDBStorage
    server_version: str


def create_database_runtime(database_url: str, *, initialize: bool = True) -> DatabaseRuntime:
    """허용된 데이터베이스에만 연결하고 필요할 때 6개 테이블을 생성한다."""

    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != "mariadb":
        raise RuntimeError("DATABASE_URL은 mariadb 드라이버를 사용해야 합니다.")
    if parsed_url.database != DATABASE_NAME:
        raise RuntimeError(f"DATABASE_URL은 {DATABASE_NAME} 데이터베이스만 가리켜야 합니다.")

    engine = create_engine(
        parsed_url,
        pool_pre_ping=True,
        pool_recycle=1_800,
        future=True,
    )
    try:
        with engine.connect() as connection:
            current_database = connection.scalar(text("SELECT DATABASE()"))
            version = str(connection.scalar(text("SELECT VERSION()")))
        if current_database != DATABASE_NAME or "mariadb" not in version.casefold():
            raise RuntimeError("연결 대상이 승인된 MariaDB 데이터베이스가 아닙니다.")
        if initialize:
            MARIADB_METADATA.create_all(engine, checkfirst=True)
    except BaseException:
        engine.dispose()
        raise

    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    return DatabaseRuntime(
        engine=engine,
        session_factory=factory,
        storage=MariaDBStorage(factory),
        server_version=version,
    )
