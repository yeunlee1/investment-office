# MariaDB에 승인된 앱 데이터베이스와 최소 권한 계정을 만든다.
from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import quote_plus, unquote_plus, urlsplit

import pymysql

DATABASE_NAME = "pixel_investment_office"
APP_USER = "pixel_office"
HOST = "127.0.0.1"
PORT = 3307


def _workspace() -> Path:
    return Path(__file__).resolve().parents[1]


def _random_password(length: int = 48) -> str:
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _existing_app_password(env_path: Path) -> str | None:
    if not env_path.is_file():
        return None
    prefix = "INVESTMENT_OFFICE_DATABASE_URL="
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            parsed = urlsplit(line.removeprefix(prefix))
            if parsed.username == APP_USER and parsed.password:
                return unquote_plus(parsed.password)
    return None


def main() -> None:
    workspace = _workspace()
    root_secret_path = workspace / "var" / "secrets" / "mariadb-root.txt"
    if not root_secret_path.is_file():
        raise RuntimeError(
            "MariaDB root 자격 증명이 없습니다. install_mariadb.ps1을 먼저 실행하세요."
        )

    root_password = root_secret_path.read_text(encoding="utf-8").strip()
    env_path = workspace / ".env"
    app_password = _existing_app_password(env_path) or _random_password()
    connection = pymysql.connect(
        host=HOST,
        port=PORT,
        user="root",
        password=root_password,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{DATABASE_NAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cursor.execute(
                f"CREATE USER IF NOT EXISTS '{APP_USER}'@'{HOST}' IDENTIFIED BY %s",
                (app_password,),
            )
            cursor.execute(f"GRANT ALL PRIVILEGES ON `{DATABASE_NAME}`.* TO '{APP_USER}'@'{HOST}'")
    finally:
        connection.close()

    encoded_password = quote_plus(app_password)
    database_url = (
        f"mariadb+pymysql://{APP_USER}:{encoded_password}@{HOST}:{PORT}/"
        f"{DATABASE_NAME}?charset=utf8mb4"
    )
    env_content = "\n".join(
        (
            "INVESTMENT_OFFICE_HOST=127.0.0.1",
            "INVESTMENT_OFFICE_PORT=8765",
            "INVESTMENT_OFFICE_CODEX_COMMAND=codex",
            "INVESTMENT_OFFICE_CODEX_TIMEOUT_SECONDS=240",
            "INVESTMENT_OFFICE_MAX_PARALLEL_AGENTS=3",
            "INVESTMENT_OFFICE_MARKET_DATA_TIMEOUT_SECONDS=20",
            "INVESTMENT_OFFICE_PROVIDER=codex",
            f"INVESTMENT_OFFICE_DATABASE_URL={database_url}",
            "",
        )
    )
    env_path.write_text(env_content, encoding="utf-8")
    print("Approved MariaDB database and app account are ready.")


if __name__ == "__main__":
    main()
