# -*- coding: utf-8 -*-
"""
Created on Mon August 5, 2025 - 12:50:47

@author: Asad Mehmood
"""

import time
import os
from dotenv import load_dotenv
import random

from db_file import Mysql
import helper_consolidated as util

load_dotenv()
dev = util.dev

def main():
    util.print_log("--Starts--")
    starts = time.time()
    limit_env = os.environ.get("LIMIT")
    set_limit = bool(limit_env)
    limit = int(limit_env) if limit_env else 0

    db_table_name = 'GaPub'
    propstream_table = 'propstream_ga'
    truthfinder_table = 'truthfinder_ga'

    util.print_log("Initializing webdriver...")
    browser, page = util.init_driver()

    parse_propstream, propstream_session = util.login_propstream(page)

    if not parse_propstream:
        util.print_log("Unable to login to Propstream.", True)
        browser.close()
        util.print_log("\nBrowser Closed.")
        return

    # Determine data source: USE_DB=1 to use MySQL; otherwise read input CSV named input_propstream_ga.csv
    use_db = os.environ.get('USE_DB', '0') == '1'
    db_data = []
    db = None
    if use_db:
        try:
            db = Mysql(dev)
            db_data = util.get_db_data_for_truthfinder(db, db_table_name, limit)
        except Exception as e:
            util.print_log("{}: {}".format(type(e).__name__, e), True)
            util.print_log("Unable to Connect Database.", True)
            db_data = []
    else:
        import csv as _csv
        import glob as _glob

        def _read_pub_csv(filepath):
            rows = []
            if not os.path.exists(filepath):
                return rows
            with open(filepath, 'r', encoding='utf-8') as fh:
                for row in _csv.DictReader(fh):
                    try:
                        tidx = int(row.get('Table_Index', 0))
                    except (ValueError, TypeError):
                        tidx = 0
                    rows.append({
                        'Table_Index': tidx,
                        'Id': row.get('Id', ''),
                        'Street': row.get('Street', ''),
                        'City': row.get('City', ''),
                        'Zip_Code': row.get('Zip_Code', ''),
                        'State': row.get('State', ''),
                        'owner_name': row.get('owner_name', ''),
                        'Date_Published': row.get('Date_Published', ''),
                        'Notice': row.get('Notice', '')
                    })
            return rows

        input_file = os.path.join(os.getcwd(), 'input_propstream_ga.csv')
        db_data = _read_pub_csv(input_file)

        # If manual input file is missing or nearly empty, auto-load from GaPub scraped exports
        if len(db_data) <= 1:
            exports_dir = os.path.join(os.getcwd(), 'exports')
            # Prefer the full GaPub.csv; fall back to GaPub_fallback_*.csv files
            candidate_files = sorted(_glob.glob(os.path.join(exports_dir, 'GaPub.csv')))
            candidate_files += sorted(_glob.glob(os.path.join(exports_dir, 'GaPub_fallback_*.csv')))
            seen_ids = {r['Id'] for r in db_data}
            for gf in candidate_files:
                for r in _read_pub_csv(gf):
                    if r['Id'] not in seen_ids:
                        db_data.append(r)
                        seen_ids.add(r['Id'])
            if db_data:
                util.print_log(f"Auto-loaded {len(db_data)} rows from GaPub exports")
            else:
                util.print_log("No input data found. Nothing to process.", True)
                browser.close()
                return
        else:
            util.print_log(f"Loading input data from {input_file} ({len(db_data)} rows)")

    util.print_log("Dashboard Loaded...")

    import re as _re
    _po_box = _re.compile(r'^\s*(P\.?O\.?\s*Box|Post\s*Office\s*Box)', _re.IGNORECASE)

    # Filter out P.O. Box and blank street addresses — Propstream can't look up those
    usable = [r for r in db_data if r.get('Street') and not _po_box.match(r['Street'])]
    skipped = len(db_data) - len(usable)
    if skipped:
        util.print_log(f"Skipped {skipped} rows with P.O. Box or blank street (not searchable in Propstream)")
    db_data = usable

    if set_limit:
        util.print_log("Working on Limited {:,} Records".format(limit))
    else:
        util.print_log("Working on {:,} Records for Propstreams".format(len(db_data)))

    results = []
    for count, arr in enumerate(db_data, start=1):
        row_index = arr['Table_Index']
        msg = "\n{} - {}".format(count, row_index)
        n = 80 - len(msg)
        util.print_log(msg + '-' * n)

        # pass database if available; get_propstream_data will fallback to CSV if db is None
        propstream_data = util.get_propstream_data(db, propstream_session, arr, propstream_table)
        if propstream_data:
            if isinstance(propstream_data, list):
                results.extend(propstream_data)
            else:
                results.append(propstream_data)

        if limit and count >= limit:
            break
        n = random.randint(2, 5)
        util.print_log("Waiting {} seconds".format(n))
        time.sleep(n)

    if db is not None:
        try:
            db.Close_db()
        except Exception:
            pass

    # Write results to CSV and XLSX (if pandas available)
    if results:
        # Enrich computed columns (try to use the original pubs rows if available)
        try:
            results = util.compute_columns(results, db_data)
        except Exception as e:
            util.print_log(f'compute_columns failed: {e}', True)

        out_dir = os.path.join(os.getcwd(), 'exports')
        os.makedirs(out_dir, exist_ok=True)
        ts = util.FALLBACK_RUN_ID
        csv_path = os.path.join(out_dir, f'propstream_ga_{ts}.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
            fieldnames = sorted({key for result in results for key in result})
            writer = __import__('csv').DictWriter(
                fh, fieldnames=fieldnames, extrasaction='ignore'
            )
            writer.writeheader()
            for r in results:
                writer.writerow(r)
        util.print_log(f'Wrote propstream CSV: {csv_path}')
        try:
            import pandas as pd
            from openpyxl import load_workbook
            from openpyxl.styles import Font
            df = pd.DataFrame(results)
            xlsx_path = os.path.join(out_dir, f'propstream_ga_{ts}.xlsx')
            df.to_excel(xlsx_path, index=False)
            # Make the 'url' column clickable hyperlinks
            if 'url' in df.columns:
                url_col_idx = list(df.columns).index('url') + 1  # 1-based
                wb = load_workbook(xlsx_path)
                ws = wb.active
                for row in ws.iter_rows(min_row=2, min_col=url_col_idx, max_col=url_col_idx):
                    for cell in row:
                        if cell.value and str(cell.value).startswith('http'):
                            cell.hyperlink = cell.value
                            cell.font = Font(color='0563C1', underline='single')
                wb.save(xlsx_path)
            util.print_log(f'Wrote propstream XLSX: {xlsx_path}')
        except Exception as e:
            util.print_log(f'pandas not available — skipped XLSX export ({e})')

    browser.close()
    util.print_log("\nBrowser Closed.")

    ends = time.time()
    util.print_log("--Finish--")
    elapsed = util.time_elapsed_str(starts, ends)
    util.print_log(elapsed)

if __name__ == '__main__':
    main()
