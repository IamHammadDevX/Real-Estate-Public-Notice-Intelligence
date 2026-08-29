# -*- coding: utf-8 -*-
"""
Created on Sun Oct  7 12:36:21 2018

@author: Asad Mehmood
"""

from db_file import Mysql
import time
from dotenv import load_dotenv
import helper as util
import random

load_dotenv()

def time_elapsed_str(start, end):
    elapse = end - start
    hours, rem = divmod(elapse, 3600)
    minutes, seconds = divmod(rem, 60)
    strings = "{:0>2}:{:0>2}:{:0>2}".format(int(hours), int(minutes), int(seconds))
    if elapse < 1:
        mili = str(round(elapse, 3))
        miliseconds = mili[1:]
        strings += miliseconds
    return strings

def update_data(database, data, table):
    set_equal = list()
    # skip_columns = ['Table_Index', 'Notice']
    skip_columns = ['Street', 'City', 'Zip_Code', 'Address', 'Table_Index', 'Notice']
    for column, values in data.items():
        if column in skip_columns:
            continue
        sets = "`{}` = '{}'".format(column, values)
        set_equal.append(sets)
    equals = ", ".join(set_equal)

    where_clause = "`Table_Index` = {Table_Index}".format_map(data)

    stmt = """UPDATE `{}` SET {} WHERE {};""".format(table, equals, where_clause)
    try:
        database.run_query(stmt)
        print("Data Updated: '{}'".format(data['Table_Index']))

    except Exception as e:
        error_str = "{}: {}".format(str(type(e).__name__), str(e))
        error_sql = "SQL: '{}'".format(stmt)
        print(error_str)
        print(error_sql)

if __name__ == '__main__':
    print("--Starts--")
    starts = time.monotonic()
    parse = True
    try:
        print("Connecting Database...")
        db = Mysql()
    except Exception as e:
        error_str = "{}: {}".format(str(type(e).__name__), str(e))
        print(error_str)
        parse = False

    if parse:
        limit = 0
        table_name = "NcPub"
        # table_name = "GaPub"

        columns = ['Table_Index', 'Notice']
        column_names = ", ".join(columns)
        stmt = [
            "SELECT {} FROM {}".format(column_names, table_name),
            "WHERE parcel_number IS NULL"
        ]
        if table_name in ['GaPub', 'NcPub']:
            order = 'ORDER BY Date_Added DESC'
            stmt.append(order)

        if limit:
            limits = 'LIMIT {}'.format(limit)
            stmt.append(limits)
        db_query = " ".join(stmt)

        print("\n{}".format(db_query))
        rows = db.show_data(table_name, db_query)
        db_data = [dict(zip(columns, row)) for row in list(rows)]

        print("\nWorking on {:,} Records".format(len(db_data)))
        for i, row in enumerate(db_data):
            print("-" * 120)
            raw_notice = row['Notice']
            ind = row['Table_Index']
            print("Index = {}".format(ind))
            api_result = util.parse_notice(raw_notice)
            if api_result:
                api_result.update(row)
                update_data(db, api_result, table_name)

            ii = random.randint(2, 3)
            print("\nWaiting {} Seconds...".format(ii))
            time.sleep(ii)

        db.Close_db()


    ends = time.monotonic()
    print("--Finish--")
    elapsed = time_elapsed_str(starts, ends)
    print(elapsed)