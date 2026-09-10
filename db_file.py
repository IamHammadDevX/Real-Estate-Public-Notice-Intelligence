# -*- coding: utf-8 -*-
"""
Created on Fri Oct  1 12:32:10 2021

@author: Asad Mehmood (asadmahmood16@hotmail.com)
"""

import mysql.connector
import logging
from dotenv import load_dotenv
import os
import random
import time
import re

load_dotenv()
class Mysql:
    DISCONNECT_ERROR_CODES = {2006, 2013, 2014, 2045, 2055, 4031}

    def __init__(self, dev=True):
        self.dev = dev
        db_base = os.environ.get("DATABASE_NAME") or os.environ.get("DB_NAME")
        self.config = {
            'host': os.environ.get("DATABASE_HOST") or os.environ.get("DB_HOST"),
            'user': os.environ.get("DATABASE_USER") or os.environ.get("DB_USER"),
            'password': os.environ.get("DATABASE_PASSWORD") or os.environ.get("DB_PASSWORD"),
            'database': db_base
        }
        self.connection = None
        self.cursor = None
        self.reconnect(force=True)
        self.print_log("Database Connected: '{}'".format(db_base))

    def print_log(self, text, error=False):
        dev = self.dev
        if dev:
            print(text)
        else:
            if error:
                logging.error(text.strip())
            else:
                logging.info(text.strip())

    def show_data(self, name, extra=False):
        stmt = 'SELECT * FROM {}'.format(self._quote_identifier(name))
        if extra:
            if isinstance(extra, list):
                columns = extra.copy()
                column_str = ", ".join(self._quote_identifier(column) for column in columns)
                stmt = 'SELECT {} FROM {}'.format(column_str, self._quote_identifier(name))
            elif isinstance(extra, str):
                stmt = extra.strip()

        rows = self._execute(stmt, fetch="all")
        for row in rows:
            yield row

    def get_count(self, name, max_column=False):
        source_sql = name.strip() if str(name).strip().startswith('(') else self._quote_identifier(name)
        stmt = 'SELECT COUNT(1) FROM {}'.format(source_sql)
        if max_column:
            stmt = 'SELECT MAX({}) FROM {}'.format(
                self._quote_identifier(max_column), self._quote_identifier(name)
            )
        row = self._execute(stmt, fetch="one")
        return row[0]

    @staticmethod
    def _quote_identifier(value):
        value = str(value)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("Unsafe SQL identifier: {!r}".format(value))
        return "`{}`".format(value)

    @classmethod
    def _is_disconnect_error(cls, error):
        return getattr(error, "errno", None) in cls.DISCONNECT_ERROR_CODES

    def _execute(self, query, params=None, fetch=None, commit=False):
        """Execute one statement, reconnecting first and retrying once on disconnect."""
        params = () if params is None else params
        for attempt in range(2):
            try:
                self.reconnect()
                self.cursor.execute(query, params)
                rowcount = self.cursor.rowcount
                if fetch == "one":
                    result = self.cursor.fetchone()
                elif fetch == "all":
                    result = self.cursor.fetchall()
                else:
                    result = rowcount
                if commit:
                    self.connection.commit()
                return result
            except Exception as error:
                if attempt == 0 and self._is_disconnect_error(error):
                    self.print_log(
                        "MySQL disconnected ({}); reconnecting and retrying once.".format(
                            getattr(error, "errno", "unknown")
                        ),
                        True,
                    )
                    self.reconnect(force=True)
                    continue
                raise

    def run_query(self, query, params=None):
        return self._execute(query, params=params, commit=True)

    def fetch_all(self, query, params=None):
        rows = self._execute(query, params=params, fetch="all")
        return tuple(self.cursor.column_names), rows

    def get_pub_record(self, table_name, notice_id):
        """Return one saved source notice as a dict for restart-safe resume."""
        if table_name not in {'GaPub', 'NcPub'}:
            raise ValueError("Unsupported notice table: {}".format(table_name))
        columns, rows = self.fetch_all(
            "SELECT * FROM {} WHERE `Id` = %s LIMIT 1".format(
                self._quote_identifier(table_name)
            ),
            (notice_id,),
        )
        return dict(zip(columns, rows[0])) if rows else None

    def Close_db(self):
        if self.connection is not None and self.connection.is_connected():
            if self.cursor is not None:
                self.cursor.close()
            self.connection.close()
            self.print_log("Database Connection Close.")

    def reconnect(self, force=False):
        try:
            connected = self.connection is not None and self.connection.is_connected()
            if force or not connected:
                self.print_log("Connection lost. Reconnecting...", True)
                try:
                    if self.cursor is not None:
                        self.cursor.close()
                except Exception:
                    pass
                try:
                    if self.connection is not None:
                        self.connection.close()
                except Exception:
                    pass
                self.connection = mysql.connector.connect(**self.config)
                self.cursor = self.connection.cursor()
                self.print_log("Reconnected to MySQL server.")
        except Exception as e:
            error_str = "{}: {}".format(str(type(e).__name__), str(e))
            self.print_log(error_str, True)
            self.print_log(f"Reconnection failed: {e}", True)
            raise

    def pub_data(self, data, table_name):
        data = dict(data)
        table_sql = self._quote_identifier(table_name)
        if data.get('Id') not in (None, ''):
            where_sql = "`Id` = %s"
            where_params = (data['Id'],)
            immutable = {'Id'}
        elif data.get('Street') and data.get('City'):
            where_sql = "`Street` = %s AND `City` = %s"
            where_params = (data['Street'], data['City'])
            immutable = {'Street', 'City'}
        else:
            where_sql = "`Notice` = %s"
            where_params = (data.get('Notice', ''),)
            immutable = {'Notice'}
        try:
            row = self._execute(
                "SELECT COUNT(1) FROM {} WHERE {}".format(table_sql, where_sql),
                where_params,
                fetch="one",
            )
            if row and row[0]:
                update_columns = [key for key in data if key not in immutable]
                assignments = ", ".join(
                    "{} = %s".format(self._quote_identifier(key)) for key in update_columns
                )
                params = tuple(data[key] for key in update_columns) + where_params
                self.run_query(
                    "UPDATE {} SET {} WHERE {}".format(table_sql, assignments, where_sql),
                    params,
                )
                self.print_log("\nData Updated: '{}'".format(data['Id']))
            else:
                columns = list(data)
                column_sql = ", ".join(self._quote_identifier(key) for key in columns)
                placeholders = ", ".join(["%s"] * len(columns))
                self.run_query(
                    "INSERT INTO {} ({}) VALUES ({})".format(
                        table_sql, column_sql, placeholders
                    ),
                    tuple(data[key] for key in columns),
                )
                self.print_log("\nData Inserted: '{}'".format(data['Id']))
            return True
        except Exception as e:
            error_str = "{}: {}".format(str(type(e).__name__), str(e))
            self.print_log(error_str, True)
            raise

    def propstreams(self, table_name, data):
        data = dict(data)
        table_sql = self._quote_identifier(table_name)
        address = data.get('address_db', '')
        try:
            row = self._execute(
                "SELECT COUNT(1) FROM {} WHERE `address_db` = %s".format(table_sql),
                (address,),
                fetch="one",
            )
            if row and row[0]:
                columns = [key for key in data if key != 'address_db']
                assignments = ", ".join(
                    "{} = %s".format(self._quote_identifier(key)) for key in columns
                )
                params = tuple(data[key] for key in columns) + (address,)
                self.run_query(
                    "UPDATE {} SET {} WHERE `address_db` = %s".format(
                        table_sql, assignments
                    ),
                    params,
                )
                self.print_log("Data Updated: '{}'".format(data['address_db']))
            else:
                columns = list(data)
                column_sql = ", ".join(self._quote_identifier(key) for key in columns)
                placeholders = ", ".join(["%s"] * len(columns))
                self.run_query(
                    "INSERT INTO {} ({}) VALUES ({})".format(
                        table_sql, column_sql, placeholders
                    ),
                    tuple(data[key] for key in columns),
                )
                self.print_log("Data Inserted: '{}'".format(data['address_db']))
            return True
        except Exception as e:
            error_str = "{}: {}".format(str(type(e).__name__), str(e))
            self.print_log(error_str, True)
            raise

    def set_propstream_info(self, table_name, notice_id, value):
        if table_name not in {'GaPub', 'NcPub'}:
            raise ValueError("Unsupported notice table: {}".format(table_name))
        if value not in {'Y', 'N', None}:
            raise ValueError("propstream_info must be Y, N, or None")
        table_sql = self._quote_identifier(table_name)
        row = self._execute(
            "SELECT COUNT(1) FROM {} WHERE `Id` = %s".format(table_sql),
            (notice_id,),
            fetch="one",
        )
        if not row or not row[0]:
            self.print_log(
                "PropStream tag {} not saved: notice {} missing from {}.".format(
                    value, notice_id, table_name
                ),
                True,
            )
            return False
        affected = self.run_query(
            "UPDATE {} SET `propstream_info` = %s WHERE `Id` = %s".format(
                table_sql
            ),
            (value, notice_id),
        )
        self.print_log(
            "PropStream tag {} saved for {} in {} (affected rows: {}).".format(
                value, notice_id, table_name, affected
            )
        )
        return True

    def truthfinder(self, table_name, array):
        parse_once = True
        table_sql = self._quote_identifier(table_name)
        for i, data in enumerate(array, start=1):
            data = dict(data)
            address = data.get('address_db', '')
            if parse_once:
                row = self._execute(
                    "SELECT COUNT(1) FROM {} WHERE `address_db` = %s".format(table_sql),
                    (address,),
                    fetch="one",
                )
                if row and row[0]:
                    try:
                        self.run_query(
                            "DELETE FROM {} WHERE `address_db` = %s".format(table_sql),
                            (address,),
                        )
                        v = random.randint(2, 3)
                        time.sleep(v)
                    except Exception as e:
                        error_str = "{}: {}".format(str(type(e).__name__), str(e))
                        self.print_log(error_str, True)
                parse_once = False

            columns = list(data)
            columns_sql = ", ".join(self._quote_identifier(key) for key in columns)
            placeholders = ", ".join(["%s"] * len(columns))
            stmt = "INSERT INTO {} ({}) VALUES ({})".format(
                table_sql, columns_sql, placeholders
            )
            try:
                self.run_query(stmt, tuple(data[key] for key in columns))
                self.print_log("Data Inserted: '{}'".format(data['name']))
            except Exception as e:
                error_str = "{}: {}".format(str(type(e).__name__), str(e))
                self.print_log(error_str, True)
                raise

            v = random.randint(2, 3)
            self.print_log("\tWaiting {} seconds for another query...".format(v))
            time.sleep(v)

if __name__ == "__main__":
    pass
