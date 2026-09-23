"""
Author: DbLayer
Date:   2026

Description:
    Single data access layer for Inventory Machine. Opens one SQLite
    or MariaDB connection from config. Every SQL call goes through
    this module.
"""
# Imports
import configparser
import logging
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlparse

# Globals
logger = logging.getLogger(__name__)

SQLITE_BACKEND = "sqlite"
MARIADB_BACKEND = "mariadb"


# Functions
def adapt_schema_for_mariadb(sql: str) -> str:
    """
    Input: sql -- SQLite-flavored schema text.
    Output: the same text with MariaDB syntax.
    Details:
        Replaces INTEGER PRIMARY KEY AUTOINCREMENT with
        INTEGER PRIMARY KEY AUTO_INCREMENT. Replaces datetime('now')
        with CURRENT_TIMESTAMP. Schema files stay SQLite-flavored.
    """
    return sql.replace(
        "INTEGER PRIMARY KEY AUTOINCREMENT",
        "INTEGER PRIMARY KEY AUTO_INCREMENT",
    ).replace("datetime('now')", "CURRENT_TIMESTAMP")


def _parse_mariadb_dsn(dsn: str) -> dict:
    """
    Input: dsn -- a URL of the form mariadb://user:pass@host:port/dbname.
    Output: a dict with host, port, user, password, and database.
    Details:
        Raises ValueError when the scheme is not mariadb, or when the
        host or database name is missing.
    """
    parsed = urlparse(dsn)
    if parsed.scheme != MARIADB_BACKEND:
        logger.warning("MariaDB DSN must use the mariadb scheme")
        raise ValueError(f"Invalid MariaDB DSN: {dsn}")
    database = unquote(parsed.path.lstrip("/"))
    if not parsed.hostname or not database:
        logger.warning("MariaDB DSN is missing host or database name")
        raise ValueError(f"Invalid MariaDB DSN: {dsn}")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": unquote(parsed.username) if parsed.username else "",
        "password": unquote(parsed.password) if parsed.password else "",
        "database": database,
    }


def _split_sql_statements(sql: str) -> list[str]:
    """
    Input: sql -- a schema script with one or more statements.
    Output: a list of non-empty statements.
    Details:
        Splits on semicolons. Schema files do not put a semicolon
        inside a string or a comment.
    """
    statements = []
    for chunk in sql.split(";"):
        statement = chunk.strip()
        if statement:
            statements.append(statement)
    return statements


def _is_pragma_statement(statement: str) -> bool:
    """
    Input: statement -- one SQL statement. Leading comments are allowed.
    Output: True when the first real command is PRAGMA.
    Details:
        MariaDB does not accept SQLite PRAGMA lines. load_schema skips
        those lines on the MariaDB path.
    """
    for line in statement.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        return stripped.upper().startswith("PRAGMA")
    return False


# Classes
class Database:
    """
    Owns the SQL connection for the project.
    Other modules call this class. They do not open a connection.
    """

    def __init__(self, cfg: configparser.ConfigParser):
        """
        Input: cfg -- a loaded ConfigParser with a [database] section.
        Output: None.
        Details:
            Reads [database] backend from cfg. sqlite opens sqlite_path.
            mariadb opens mariadb_dsn through a lazy PyMySQL import.
        """
        try:
            backend = cfg.get("database", "backend")
        except configparser.Error:
            logger.exception("Database config is missing backend")
            raise
        self._backend = backend
        if backend == SQLITE_BACKEND:
            try:
                sqlite_path = cfg.get("database", "sqlite_path")
            except configparser.Error:
                logger.exception("Database config is missing sqlite_path")
                raise
            self._conn = self._open_sqlite(sqlite_path)
        elif backend == MARIADB_BACKEND:
            try:
                dsn = cfg.get("database", "mariadb_dsn")
            except configparser.Error:
                logger.exception("Database config is missing mariadb_dsn")
                raise
            self._conn = self._open_mariadb(dsn)
        else:
            logger.warning("Unknown database backend: %s", backend)
            raise ValueError(f"Unknown database backend: {backend}")

    def _open_sqlite(self, sqlite_path: str) -> sqlite3.Connection:
        """
        Input: sqlite_path -- filesystem path or :memory:.
        Output: an open sqlite3 connection.
        Details:
            Sets PRAGMA foreign_keys = ON on this new connection.
        """
        try:
            conn = sqlite3.connect(sqlite_path)
            conn.execute("PRAGMA foreign_keys = ON")
            return conn
        except sqlite3.Error:
            logger.exception("Failed to open SQLite database at %s", sqlite_path)
            raise

    def _open_mariadb(self, dsn: str):
        """
        Input: dsn -- a mariadb:// connection URL.
        Output: an open PyMySQL connection.
        Details:
            Imports PyMySQL only on this path. The sqlite path does
            not need PyMySQL installed.
        """
        try:
            import pymysql
        except ImportError:
            logger.exception("PyMySQL is not installed")
            raise
        parts = _parse_mariadb_dsn(dsn)
        try:
            return pymysql.connect(
                host=parts["host"],
                port=parts["port"],
                user=parts["user"],
                password=parts["password"],
                database=parts["database"],
            )
        except Exception:
            logger.exception("Failed to open MariaDB connection")
            raise

    def get_connection(self):
        """
        Input: None.
        Output: the open database connection.
        Details:
            Returns the connection this object opened at init. Callers
            must not open a second connection.
        """
        return self._conn

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """
        Input: query -- a parameterized SQL statement. params -- bind values.
        Output: the cursor after the statement runs.
        Details:
            Binds params through the driver. Does not build SQL by string
            join. Commits after a successful run. Callers can read
            cursor.lastrowid.
        """
        try:
            cursor = self._conn.cursor()
            cursor.execute(query, params)
            self._conn.commit()
            return cursor
        except Exception:
            logger.exception("SQL execute failed")
            try:
                self._conn.rollback()
            except Exception:
                logger.exception("Rollback failed after execute error")
            raise

    def fetch_one(self, query: str, params: tuple = ()) -> tuple | None:
        """
        Input: query -- a parameterized SQL statement. params -- bind values.
        Output: one row as a tuple, or None when no row matches.
        Details:
            Binds params through the driver. Does not build SQL by string
            join.
        """
        try:
            cursor = self._conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()
        except Exception:
            logger.exception("SQL fetch_one failed")
            raise

    def fetch_all(self, query: str, params: tuple = ()) -> list[tuple]:
        """
        Input: query -- a parameterized SQL statement. params -- bind values.
        Output: every matching row as a list of tuples.
        Details:
            Binds params through the driver. Does not build SQL by string
            join.
        """
        try:
            cursor = self._conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
        except Exception:
            logger.exception("SQL fetch_all failed")
            raise

    def load_schema(self, schema_path: str) -> None:
        """
        Input: schema_path -- path to a .sql schema file.
        Output: None.
        Details:
            Reads the file text. On SQLite, runs it with executescript.
            On MariaDB, rewrites SQLite syntax and then runs each statement.
        """
        try:
            sql = Path(schema_path).read_text(encoding="utf-8")
        except OSError:
            logger.exception("Failed to read schema file %s", schema_path)
            raise
        if self._backend == SQLITE_BACKEND:
            try:
                self._conn.executescript(sql)
                self._conn.commit()
            except sqlite3.Error:
                logger.exception("Failed to load SQLite schema from %s", schema_path)
                raise
            return
        adapted = adapt_schema_for_mariadb(sql)
        for statement in _split_sql_statements(adapted):
            if _is_pragma_statement(statement):
                continue
            self.execute(statement)
