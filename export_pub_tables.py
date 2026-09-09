# export_pub_tables.py
# Usage: python export_pub_tables.py
# Exports GaPub and NcPub tables from MySQL to CSV + XLSX, then zips both into a single archive.

import os
import csv
import zipfile
from datetime import datetime
from db_file import Mysql
from dotenv import load_dotenv

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False
    print("openpyxl not installed — XLSX export will be skipped. Run: pip install openpyxl")

load_dotenv()

OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'exports'))
os.makedirs(OUTPUT_DIR, exist_ok=True)

TABLES = ['GaPub', 'NcPub']


def fetch_table(db, table_name):
    table_sql = db._quote_identifier(table_name)
    return db.fetch_all(f"SELECT * FROM {table_sql}")


def export_csv(table_name, cols, rows):
    out_file = os.path.join(OUTPUT_DIR, f"{table_name}.csv")
    with open(out_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        for row in rows:
            writer.writerow(row)
    print(f"  CSV  -> {out_file}  ({len(rows)} rows)")
    return out_file


def export_xlsx(table_name, cols, rows):
    if not HAS_OPENPYXL:
        return None
    out_file = os.path.join(OUTPUT_DIR, f"{table_name}.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = table_name

    # Header row — bold
    ws.append(list(cols))
    for cell in ws[1]:
        cell.font = openpyxl.styles.Font(bold=True)

    for row in rows:
        ws.append([str(v) if v is not None else '' for v in row])

    # Auto-fit column widths (approximate)
    for col in ws.columns:
        max_len = max((len(str(cell.value)) if cell.value else 0) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

    wb.save(out_file)
    print(f"  XLSX -> {out_file}  ({len(rows)} rows)")
    return out_file


def create_zip(files):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    zip_path = os.path.join(OUTPUT_DIR, f"GA_NC_records_{timestamp}.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if f and os.path.exists(f):
                zf.write(f, os.path.basename(f))
    print(f"\n  ZIP  -> {zip_path}")
    return zip_path


def main():
    dev = os.environ.get('DEV_MODE', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    db = Mysql(dev)
    exported_files = []

    try:
        for table_name in TABLES:
            print(f"\nExporting {table_name}...")
            try:
                cols, rows = fetch_table(db, table_name)
                exported_files.append(export_csv(table_name, cols, rows))
                exported_files.append(export_xlsx(table_name, cols, rows))
            except Exception as e:
                print(f"  ERROR exporting {table_name}: {e}")
    finally:
        db.Close_db()

    # Filter out None (skipped XLSX) before zipping
    valid_files = [f for f in exported_files if f]
    if valid_files:
        zip_path = create_zip(valid_files)
        print(f"\nDone! Send this file to your client:\n  {zip_path}")
    else:
        print("\nNo files exported.")


if __name__ == '__main__':
    main()
