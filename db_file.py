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

load_dotenv()
class Mysql:
    def __init__(self, dev=True):
        self.dev = dev
        db_base = os.environ.get("DATABASE_NAME")
        config = {
            'host': os.environ.get("DATABASE_HOST"),
            'user': os.environ.get("DATABASE_USER"),
            'password': os.environ.get("DATABASE_PASSWORD"),
            'database': db_base
        }

        self.connection = mysql.connector.connect(**config)
        if self.connection.is_connected():
            self.cursor = self.connection.cursor()
            self.print_log("Database Connected: '{}'".format(db_base))
        else:
            self.print_log("Unable to Connect: '{}'".format(db_base))

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
        stmt = 'SELECT * FROM {}'.format(name)
        if extra:
            if isinstance(extra, list):
                columns = extra.copy()
                column_str = ", ".join(columns)
                stmt = 'SELECT {} FROM {}'.format(column_str, name)
            elif isinstance(extra, str):
                stmt = extra.strip()

        self.cursor.execute(stmt)
        rows = self.cursor.fetchall()
        for row in rows:
            yield row

    def get_count(self, name, max_column=False):
        stmt = 'SELECT COUNT(1) FROM {}'.format(name)
        if max_column:
            stmt = 'SELECT MAX({}) FROM {}'.format(max_column, name)
        self.cursor.execute(stmt)
        rows = self.cursor.fetchall()
        return rows[0][0]

    def run_query(self, query):
        self.reconnect()
        self.cursor.execute(query)
        self.cursor.execute("COMMIT")

    def Close_db(self):
        if self.connection.is_connected():
            self.cursor.close()
            self.connection.close()
            self.print_log("Database Connection Close.")

    def reconnect(self):
        try:
            if not self.connection.is_connected():
                self.print_log("Connection lost. Reconnecting...", True)
                self.connection.reconnect(attempts=3, delay=5)
                self.cursor = self.connection.cursor()
                self.print_log("Reconnected to MySQL server.")
        except Exception as e:
            error_str = "{}: {}".format(str(type(e).__name__), str(e))
            self.print_log(error_str, True)
            self.print_log(f"Reconnection failed: {e}", True)
            raise

    def pub_data(self, data, table_name):
        data = {
            **data,
            'table_name': table_name
        }
        key_list = list(data.keys())
        val_list = list()
        for value in data.values():
            if type(value) == str:
                value = value.replace('\'', '')
                values = f"'{value}'"
                val_list.append(values)
            else:
                if not bool(value):
                    values = "-1"
                    val_list.append(values)
                else:
                    values = f"{value}"
                    val_list.append(values)

        street, city = data['Street'], data['City']
        query = None
        address = False
        if bool(street) and bool(city):
            query = "SELECT COUNT(1) FROM `{table_name}` WHERE `Street` = '{Street}' AND `City` = '{City}'".format_map(data)
            address = True
        else:
            query = "SELECT COUNT(1) FROM `{table_name}` WHERE `Notice` = '{Notice}'".format_map(data)
        self.cursor.execute(query)
        rows = self.cursor.fetchall()
        if bool(rows[0][0]):
            set_equal = list()
            skip_columns = ['table_name']
            if bool(address):
                skip_columns.extend(['Street', 'City'])
            else:
                skip_columns.append('Notice')
            for column, values in zip(key_list, val_list):
                if column in skip_columns:
                    continue
                sets = "{} = {}".format(column, values)
                set_equal.append(sets)
            equals = ", ".join(set_equal)

            where_clause = None
            if address:
                where_clause = "`Street` = '{Street}' AND `City` = '{City}'".format_map(data)
            else:
                where_clause = "`Notice` = '{Notice}'".format_map(data)

            stmt = """UPDATE `{}` SET {} WHERE {}""".format(table_name, equals, where_clause)
        else:
            key_list.remove('table_name')
            val_list.remove("'{}'".format(table_name))
            columns_str = "`, `".join(key_list)
            values = ", ".join(val_list)

            stmt = "INSERT INTO `{}` (`{}`) VALUES ({})".format(table_name, columns_str, values)

        try:
            self.run_query(stmt)
            if stmt.startswith("UPDATE"):
                self.print_log("\nData Updated: '{}'".format(data['Id']))
            else:
                self.print_log("\nData Inserted: '{}'".format(data['Id']))
        except Exception as e:
            error_str = "{}: {}".format(str(type(e).__name__), str(e))
            error_sql = "SQL: '{}'".format(stmt)
            self.print_log(error_str, True)
            self.print_log(error_sql, True)

    def propstreams(self, table_name, data):
        data = {
            **data,
            'table_name': table_name
        }

        key_list = list(data.keys())
        val_list = list()
        for value in data.values():
            if type(value) == str:
                value = value.replace('\'', '')
                values = f"'{value}'"
                val_list.append(values)
            else:
                values = f"{value}"
                val_list.append(values)

        query = "SELECT COUNT(1) FROM `{table_name}` WHERE `address_db` = '{address_db}';".format_map(data)
        self.cursor.execute(query)
        rows = self.cursor.fetchall()
        if bool(rows[0][0]):
            set_equal = list()
            skip_columns = ['table_name']
            for column, values in zip(key_list, val_list):
                if column in skip_columns:
                    continue
                sets = "{} = {}".format(column, values)
                set_equal.append(sets)
            equals = ", ".join(set_equal)

            where_clause = "`address_db` = '{address_db}'".format_map(data)
            stmt = """UPDATE `{}` SET {} WHERE {}""".format(table_name, equals, where_clause)
        else:
            key_list.remove('table_name')
            val_list.remove("'{}'".format(table_name))

            columns_str = "`, `".join(key_list)
            values = ", ".join(val_list)
            stmt = "INSERT INTO `{}` (`{}`) VALUES ({})".format(table_name, columns_str, values)

        try:
            self.run_query(stmt)
            if stmt.startswith("UPDATE"):
                self.print_log("Data Updated: '{}'".format(data['address_db']))
            else:
                self.print_log("Data Inserted: '{}'".format(data['address_db']))
        except Exception as e:
            error_str = "{}: {}".format(str(type(e).__name__), str(e))
            error_sql = "SQL: '{}'".format(stmt)
            self.print_log(error_str, True)
            self.print_log(error_sql, True)

    def truthfinder(self, table_name, array):
        parse_once = True
        for i, data in enumerate(array, start=1):
            data = {
                **data,
                'table_name': table_name
            }
            key_list = list(data.keys())
            val_list = list()
            for value in data.values():
                if type(value) == str:
                    value = value.replace('\'', '')
                    values = f"'{value}'"
                    val_list.append(values)
                else:
                    values = f"{value}"
                    val_list.append(values)

            if parse_once:
                query = "SELECT COUNT(1) FROM `{table_name}` WHERE `address_db` = '{address_db}'".format_map(data)
                self.cursor.execute(query)
                rows = self.cursor.fetchall()
                if bool(rows[0][0]):
                    stmt_del = "DELETE FROM `{table_name}` WHERE `address_db` = '{address_db}'".format_map(data)
                    try:
                        self.run_query(stmt_del)
                        v = random.randint(2, 3)
                        time.sleep(v)
                    except Exception as e:
                        error_str = "{}: {}".format(str(type(e).__name__), str(e))
                        self.print_log(error_str, True)
                parse_once = False

            key_list.remove('table_name')
            val_list.remove("'{}'".format(table_name))

            columns_str = "`, `".join(key_list)
            values = ", ".join(val_list)
            stmt = "INSERT INTO `{}` (`{}`) VALUES ({})".format(table_name, columns_str, values)
            try:
                self.run_query(stmt)
                if stmt.startswith("UPDATE"):
                    self.print_log("Data Updated: '{}'".format(data['name']))
                else:
                    self.print_log("Data Inserted: '{}'".format(data['name']))
            except Exception as e:
                error_str = "{}: {}".format(str(type(e).__name__), str(e))
                error_sql = "SQL: '{}'".format(stmt)
                self.print_log(error_str, True)
                self.print_log(error_sql, True)

            v = random.randint(2, 3)
            self.print_log("\tWaiting {} seconds for another query...".format(v))
            time.sleep(v)

if __name__ == "__main__":
    pass
