"""Apply a local SQL migration using configured MySQL credentials."""

import argparse
from pathlib import Path

import mysql.connector

from db_file import Mysql


def statements_from_sql(text):
    cleaned = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            cleaned.append(line)
    return [statement.strip() for statement in "\n".join(cleaned).split(";") if statement.strip()]


def main(path):
    migration = Path(path)
    statements = statements_from_sql(migration.read_text(encoding="utf-8"))
    database = Mysql(False)
    try:
        for index, statement in enumerate(statements, start=1):
            try:
                database.run_query(statement)
                status = "ok"
            except mysql.connector.Error as error:
                if error.errno == 1060:  # column already exists
                    status = "already-applied"
                else:
                    raise
            print("MIGRATION statement={}/{} status={}".format(index, len(statements), status))
    finally:
        database.Close_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    main(args.path)
