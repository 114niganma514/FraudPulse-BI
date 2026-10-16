"""
db_utils.py - Shared database helpers for FraudPulse BI.

Provides a single source of truth for loading the MySQL connection
configuration and creating SQLAlchemy engines / PyMySQL connections.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pymysql
from sqlalchemy import create_engine

# Project root is two levels up from this file (scripts/ -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "db_config.json"


def load_db_config(config_path: Path = CONFIG_PATH) -> dict:
    """Load database connection parameters from the JSON config file."""
    if not config_path.exists():
        raise FileNotFoundError(
            f"DB config not found: {config_path}. "
            "Copy config/db_config.example.json to config/db_config.json "
            "and fill in your MySQL credentials."
        )
    with open(config_path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    return cfg


def get_engine(cfg: dict | None = None):
    """Create a SQLAlchemy engine for the configured MySQL database."""
    cfg = cfg or load_db_config()
    url = (
        f"mysql+pymysql://{cfg['user']}:{cfg['password']}@"
        f"{cfg['host']}:{cfg['port']}/{cfg['database']}?charset=utf8mb4"
    )
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600)


def get_connection(cfg: dict | None = None):
    """Create a raw PyMySQL connection (useful for executemany bulk loads).

    Connects to the server without selecting a database, so the connection
    can also be used to *create* the database first. Callers that need a
    specific database should use ``conn.select_db(cfg["database"])`` once the
    database exists.
    """
    cfg = cfg or load_db_config()
    return pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        charset="utf8mb4",
        autocommit=False,
        local_infile=True,  # enables LOAD DATA LOCAL INFILE bulk loads
    )
