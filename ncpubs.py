# -*- coding: utf-8 -*-
"""
NC Public Notices — combined scraper + Propstream enrichment.
Produces one CSV + XLSX per run: exports/NcCombined_<timestamp>.csv/xlsx
"""

import time
import os
import random
import csv
from dotenv import load_dotenv

import helper_consolidated as util
from db_file import Mysql

load_dotenv()
dev = util.dev

def main(limit=None):
    strict_run = util._env_flag("STRICT_RUN")
    util.print_log("--Starts--")
    starts = time.time()
    site_link = "https://www.ncnotices.com/"
    state = 'NC'

    # ── Phase 1: Init browser & collect notice button IDs ────────────────────────
    try:
        util.print_log("Initializing Playwright webdriver...")
        browser, page = util.init_driver()
        util.print_log('Opening: "{}"'.format(site_link))
        page.goto(site_link, timeout=60000, wait_until="domcontentloaded")
        util.print_log("Page title: " + page.title())
    except Exception as e:
        util.print_log("{}: {}".format(type(e).__name__, e), True)
        util.print_log("Unable to initialize webdriver", True)
        if strict_run:
            raise
        return

    all_pages = util.evaluate_pages_to_work(page, limit)
    notice_data = all_pages[:limit] if limit else all_pages.copy()

    util.print_log('\n\nLoading: "{}"'.format(site_link))
    page.goto(site_link, timeout=60000, wait_until="domcontentloaded")

    db = None
    try:
        db = Mysql(dev)
    except Exception as e:
        util.print_log(f"Database connection failed — proceeding without DB: {e}", True)
        if strict_run:
            browser.close()
            raise RuntimeError("Database is required for strict server run") from e

    # ── Phase 2: Scrape all notices ───────────────────────────────────────────────
    scraped_records = []
    scrape_failures = []
    scrape_error = None
    try:
        page, scraped_records, scrape_failures = util.get_all_pages(
            page, notice_data, db, state, return_failures=True
        )
    except Exception as e:
        util.print_log(f"get_all_pages failed: {e}", True)
        scrape_error = e

    util.print_log(f"\nScraped {len(scraped_records)} notices. Starting Propstream enrichment...")

    # ── Phase 3: Propstream login & lookup ───────────────────────────────────────
    propstream_results = {}  # notice Id -> list of propstream dicts
    propstream_failures = []
    parse_propstream, propstream_session = util.login_propstream(page)
    propstream_login_failed = not parse_propstream

    if parse_propstream:
        usable = [
            r for r in scraped_records
            if util.is_propstream_eligible(r)
            and r.get("propstream_info") not in ("Y", "N")
        ]
        skipped = len(scraped_records) - len(usable)
        if skipped:
            util.print_log(f"Skipped {skipped} P.O. Box / incomplete-address records (not searchable in Propstream)")

        propstream_started = time.time()
        for count, rec in enumerate(usable, start=1):
            msg = "\nPropstream {} / {} — {}".format(count, len(usable), rec.get('Street', ''))
            util.print_log(msg)
            try:
                props = util.get_propstream_data(db, propstream_session, rec, f'propstream_{state.lower()}')
                if props:
                    propstream_results[str(rec.get('Id', ''))] = props
            except Exception as e:
                util.print_log(f"Propstream lookup failed for {rec.get('Street', '')}: {e}", True)
            if rec.get("propstream_info") not in ("Y", "N"):
                propstream_failures.append(str(rec.get("Id", "")))

            n = random.randint(2, 5)
            util.print_log(f"Waiting {n} seconds")
            time.sleep(n)
            util.print_progress(
                state,
                "propstream",
                count,
                len(usable),
                propstream_started,
                count - len(propstream_failures),
            )
    else:
        util.print_log("Propstream login failed — combined file will have scraping data only.", True)
        if strict_run:
            propstream_failures.append("LOGIN")

    if db is not None:
        try:
            db.Close_db()
        except Exception:
            pass

    browser.close()
    util.print_log("\nBrowser Closed.")

    # ── Phase 4: Merge pub + propstream records ───────────────────────────────────
    combined = []
    for rec in scraped_records:
        notice_id = str(rec.get('Id', ''))
        props = propstream_results.get(notice_id, [])
        if props:
            for prop in props:
                merged = dict(rec)
                merged.update(prop)
                combined.append(merged)
        else:
            combined.append(dict(rec))

    # ── Phase 5: Compute enrichment columns ──────────────────────────────────────
    try:
        combined = util.compute_columns(combined, scraped_records)
    except Exception as e:
        util.print_log(f"compute_columns failed: {e}", True)

    # ── Phase 6: Write combined output ───────────────────────────────────────────
    out_dir = os.path.join(os.getcwd(), 'exports')
    os.makedirs(out_dir, exist_ok=True)
    ts = util.FALLBACK_RUN_ID

    if combined:
        # Preserve column insertion order across all rows
        all_keys = list(dict.fromkeys(k for row in combined for k in row.keys()))

        csv_path = os.path.join(out_dir, f'NcCombined_{ts}.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=all_keys, extrasaction='ignore')
            writer.writeheader()
            for r in combined:
                writer.writerow(r)
        util.print_log(f"Wrote combined CSV: {csv_path}")

        try:
            import pandas as pd
            from openpyxl import load_workbook
            from openpyxl.styles import Font

            excel_records = util.sanitize_excel_records(combined)
            df = pd.DataFrame(excel_records, columns=all_keys)
            xlsx_path = os.path.join(out_dir, f'NcCombined_{ts}.xlsx')
            df.to_excel(xlsx_path, index=False)

            if 'url' in all_keys:
                url_col_idx = all_keys.index('url') + 1  # 1-based for openpyxl
                wb = load_workbook(xlsx_path)
                ws = wb.active
                for row in ws.iter_rows(min_row=2, min_col=url_col_idx, max_col=url_col_idx):
                    for cell in row:
                        if cell.value and str(cell.value).startswith('http'):
                            cell.hyperlink = cell.value
                            cell.font = Font(color='0563C1', underline='single')
                wb.save(xlsx_path)
            util.print_log(f"Wrote combined XLSX: {xlsx_path}")
        except Exception as e:
            util.print_log(f"XLSX export skipped: {e}")
    else:
        util.print_log("No records to write.", True)

    ends = time.time()
    util.print_log("--Finish--")
    util.print_log(util.time_elapsed_str(starts, ends))
    if propstream_failures and not propstream_login_failed:
        util.print_log(
            f"Propstream left {len(propstream_failures)} record(s) NULL after lookup errors; "
            "continuing because NULL is the required error state.",
            True,
        )
    if strict_run and (scrape_error or scrape_failures or propstream_login_failed):
        raise RuntimeError(
            "Incomplete NC run: scrape_error={}, failed_notices={}, "
            "failed_propstream={}".format(
                bool(scrape_error), len(scrape_failures), len(propstream_failures)
            )
        )


if __name__ == '__main__':
    env_limit = os.environ.get('LIMIT')
    main(int(env_limit) if env_limit else None)
