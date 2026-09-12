"""Read-only database status for server monitoring. Never prints credentials."""

from db_file import Mysql
from state_config import NOTICE_TABLES


def main():
    database = Mysql(False)
    try:
        for table in sorted(NOTICE_TABLES):
            try:
                row = database._execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN Street IS NOT NULL AND TRIM(Street) <> '' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN owner_name IS NOT NULL AND TRIM(owner_name) <> '' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN propstream_info = 'Y' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN propstream_info = 'N' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN propstream_info IS NULL THEN 1 ELSE 0 END) "
                "FROM `{}`".format(table),
                    fetch="one",
                )
            except Exception as error:
                print("{} unavailable: {}".format(table, error))
                continue
            total, address, owner, yes_count, no_count, null_count = (
                int(value or 0) for value in row
            )
            print(
                "{} total={} address={} owner={} Y={} N={} NULL={}".format(
                    table,
                    total,
                    address,
                    owner,
                    yes_count,
                    no_count,
                    null_count,
                )
            )
        try:
            rows = database._execute(
                "SELECT `State`, `Status`, COUNT(*) FROM `ScrapeQueue` "
                "GROUP BY `State`, `Status` ORDER BY `State`, `Status`",
                fetch="all",
            )
            if rows:
                print("Queue " + " ".join("{}:{}={}".format(*row) for row in rows))
        except Exception:
            pass
    finally:
        database.Close_db()


if __name__ == "__main__":
    main()
