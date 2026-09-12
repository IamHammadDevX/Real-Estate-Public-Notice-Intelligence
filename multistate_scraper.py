"""Restart-safe scraper for FL, NY, NJ, MD, and TX."""

import argparse
import calendar
import html
import json
import os
import random
import re
import time
from datetime import date, datetime, timezone
from urllib.parse import urljoin

import requests
import helper_consolidated as util
from db_file import Mysql
from state_config import NEW_STATE_CODES, get_state_config


COLUMN_API = "https://us-central1-enotice-production.cloudfunctions.net/api/search/public-notices"
PAGE_SIZE = max(1, int(os.environ.get("DISCOVERY_PAGE_SIZE", "100")))
KEYWORD = os.environ.get("NOTICE_KEYWORD", "foreclosure")
SCRAPE_START_DATE = os.environ.get("SCRAPE_START_DATE") or date.today().isoformat()
SCRAPE_END_DATE = os.environ.get("SCRAPE_END_DATE") or date.today().isoformat()
FL_FORECLOSURE_SUBCATEGORIES = frozenset({7, 8, 9, 10, 21})
FL_FORECLOSURE_NOTICE = re.compile(
    r"\bNOTICE\s+OF\s+(?:MORTGAGE\s+)?FORECLOSURE\s+SALE\b",
    re.IGNORECASE,
)


def _post_json(session, url, payload, attempts=3):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.post(url, json=payload, timeout=60)
            response.raise_for_status()
            return response.json()
        except Exception as error:
            last_error = error
            util.print_log(
                "API request attempt {}/{} failed: {}".format(attempt, attempts, error),
                True,
            )
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise RuntimeError("API request failed after {} attempts: {}".format(attempts, last_error))


def _clean_text(value):
    if value is None:
        return ""
    text = re.sub(r"(?i)<br\s*/?>|</p\s*>|</div\s*>", "\n", str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return "\n".join(
        part.strip() for part in html.unescape(text).splitlines() if part.strip()
    )


def _parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc).date().isoformat()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def normalize_api_notice(state, payload, source_url):
    """Map FL/NY API data into the common public-notice schema."""
    notice = _clean_text(payload.get("notice") or payload.get("text") or payload.get("highlighted_text"))
    parsed = {
        "Street": "",
        "City": "",
        "Zip_Code": "",
        "owner_name": "",
        "parcel_number": "",
        "Address": str(False),
    }
    try:
        result = util.parse_notice(notice)
        if result:
            parsed.update(result)
    except Exception as error:
        util.print_log("Address parsing failed; saving notice without address: {}".format(error), True)

    parsed.update(
        {
            "State": state,
            "Id": str(payload.get("id") or payload.get("noticeId") or ""),
            "Notice": notice,
            "Publisher": str(payload.get("paper") or payload.get("newspapername") or "")[:100],
            "Date_Published": _parse_date(payload.get("date") or payload.get("publishedtimestamp")),
            "county": str(payload.get("county") or "")[:255],
            "page_url": source_url,
            "propstream_info": None,
        }
    )
    for field, limit in {
        "Street": 100,
        "City": 100,
        "Zip_Code": 10,
        "owner_name": 500,
        "parcel_number": 500,
    }.items():
        parsed[field] = str(parsed.get(field) or "")[:limit]
    parsed["Address"] = str(util.is_property_street(parsed.get("Street")))
    return parsed


def _month_after(value):
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _month_end(value):
    return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def is_florida_foreclosure(payload):
    """Reject incidental keyword hits while retaining official foreclosure notices."""
    try:
        if int(payload.get("subcategoryId")) in FL_FORECLOSURE_SUBCATEGORIES:
            return True
    except (TypeError, ValueError):
        pass
    notice = _clean_text(
        payload.get("notice") or payload.get("text") or payload.get("highlighted_text")
    )
    return bool(FL_FORECLOSURE_NOTICE.search(notice))


def discover_florida(db, config, limit=None, session=None):
    checkpoint = db.get_scrape_checkpoint(config.code) or {}
    if checkpoint.get("Discovery_Complete"):
        return int(checkpoint.get("Total_Discovered") or 0)
    cursor = checkpoint.get("cursor") or {}
    offset = int(cursor.get("offset", 0))
    discovered = int(checkpoint.get("Total_Discovered") or 0)
    http = session or requests.Session()

    while True:
        remaining = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit - discovered)
        if remaining <= 0:
            return discovered
        body = {
            "counties": [],
            "date-range--end-date": SCRAPE_END_DATE,
            "date-range--start-date": SCRAPE_START_DATE,
            "keywords": KEYWORD,
            "offset": offset,
            "paper": "-1",
            "sort-by": None,
            "limit": remaining,
        }
        data = _post_json(http, config.source_url, body)
        notices = (data.get("_embedded") or {}).get("notices") or []
        for item in notices:
            if not is_florida_foreclosure(item):
                continue
            notice_id = str(item.get("id") or "")
            if not notice_id:
                continue
            href = ((item.get("_links") or {}).get("self") or {}).get("href")
            source_url = href or urljoin(config.source_url, "notices/" + notice_id)
            inserted = db.enqueue_notice(config.code, notice_id, source_url, item)
            discovered += int(bool(inserted))
        offset += len(notices)
        complete = not notices or offset >= int(data.get("totalCount") or offset)
        db.save_scrape_checkpoint(
            config.code, config.adapter, {"offset": offset}, complete, discovered
        )
        util.print_log("DISCOVERY state=FL queued={} source_total={}".format(discovered, data.get("totalCount", "?")))
        if complete or (limit is not None and discovered >= limit):
            return discovered


def discover_new_york(db, config, limit=None, session=None):
    checkpoint = db.get_scrape_checkpoint(config.code) or {}
    if checkpoint.get("Discovery_Complete"):
        return int(checkpoint.get("Total_Discovered") or 0)
    cursor = checkpoint.get("cursor") or {}
    start = date.fromisoformat(cursor.get("window_start") or SCRAPE_START_DATE)
    current_page = int(cursor.get("page", 1))
    discovered = int(checkpoint.get("Total_Discovered") or 0)
    today = min(date.today(), date.fromisoformat(SCRAPE_END_DATE))
    http = session or requests.Session()

    while start <= today:
        end = min(_month_end(start), today)
        while True:
            if limit is not None and discovered >= limit:
                return discovered
            body = {
                "search": KEYWORD,
                "allFilters": [
                    {"state": ["New York"]},
                    {
                        "publishedtimestamp": {
                            "from": int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp() * 1000),
                            "to": int(datetime.combine(end, datetime.max.time(), timezone.utc).timestamp() * 1000),
                        }
                    },
                ],
                "noneFilters": [],
                "sort": [{"publishedtimestamp": "desc"}],
                "pageSize": PAGE_SIZE,
                "current": current_page,
                "isDemo": False,
            }
            data = _post_json(http, COLUMN_API, body)
            if not data.get("success", True):
                raise RuntimeError("Column API returned success=false")
            results = data.get("results") or []
            for item in results:
                if limit is not None and discovered >= limit:
                    db.save_scrape_checkpoint(
                        config.code,
                        config.adapter,
                        {"window_start": start.isoformat(), "page": current_page},
                        False,
                        discovered,
                    )
                    return discovered
                notice_id = str(item.get("id") or "")
                if not notice_id:
                    continue
                source_url = "{}?activeNotice={}".format(config.source_url.rstrip("/"), notice_id)
                inserted = db.enqueue_notice(config.code, notice_id, source_url, item)
                discovered += int(bool(inserted))
            page_info = data.get("page") or {}
            total_pages = max(1, int(page_info.get("total_pages") or 1))
            if current_page >= total_pages or not results:
                break
            current_page += 1
            db.save_scrape_checkpoint(
                config.code,
                config.adapter,
                {"window_start": start.isoformat(), "page": current_page},
                False,
                discovered,
            )
        start = _month_after(start)
        current_page = 1
        complete = start > today
        db.save_scrape_checkpoint(
            config.code,
            config.adapter,
            {"window_start": start.isoformat(), "page": 1},
            complete,
            discovered,
        )
        util.print_log("DISCOVERY state=NY queued={} through={}".format(discovered, end))
        if limit is not None and discovered >= limit:
            return discovered
    return discovered


def discover_legacy(db, config, limit=None):
    checkpoint = db.get_scrape_checkpoint(config.code) or {}
    if checkpoint.get("Discovery_Complete"):
        return int(checkpoint.get("Total_Discovered") or 0)
    cursor = checkpoint.get("cursor") or {}
    start_page = max(1, int(cursor.get("page", 1)))
    discovered = int(checkpoint.get("Total_Discovered") or 0)
    browser, page = util.init_driver()
    try:
        page = util.recover_search_page(page, config.source_url, 1)
        try:
            text = page.locator(
                "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_lblTotalPages"
            ).inner_text()
            total_pages = int(text.strip().split()[1])
        except Exception:
            total_pages = 1

        for page_number in range(start_page, total_pages + 1):
            page = util.recover_search_page(page, config.source_url, page_number)
            buttons = page.locator("input.viewButton[onclick^='javascript']")
            for index in range(buttons.count()):
                button = buttons.nth(index)
                notice_id = util.notice_id_from_button(button)
                if not notice_id:
                    continue
                source_url = urljoin(config.source_url, "Details.aspx?ID=" + notice_id)
                inserted = db.enqueue_notice(
                    config.code,
                    notice_id,
                    source_url,
                    {"search_page": page_number},
                )
                discovered += int(bool(inserted))
                if limit is not None and discovered >= limit:
                    db.save_scrape_checkpoint(
                        config.code, config.adapter, {"page": page_number}, False, discovered
                    )
                    return discovered
            complete = page_number >= total_pages
            db.save_scrape_checkpoint(
                config.code,
                config.adapter,
                {"page": page_number + 1},
                complete,
                discovered,
            )
            util.print_log(
                "DISCOVERY state={} page={}/{} queued={}".format(
                    config.code, page_number, total_pages, discovered
                )
            )
        return discovered
    finally:
        browser.close()


def discover(db, config, limit=None):
    if config.adapter == "florida_api":
        return discover_florida(db, config, limit)
    if config.adapter == "column_api":
        return discover_new_york(db, config, limit)
    return discover_legacy(db, config, limit)


def _payload_dict(raw):
    if isinstance(raw, dict):
        return raw
    return json.loads(raw) if raw else {}


def _open_legacy_task(page, config, task, notice_id):
    """Rebuild valid search session, then open only the queued notice ID."""
    payload = _payload_dict(task.get("Payload"))
    target_page = max(1, int(payload.get("search_page") or 1))
    def find_on_current_page():
        buttons = page.locator("input.viewButton[onclick^='javascript']")
        for index in range(buttons.count()):
            candidate = buttons.nth(index)
            if util.notice_id_from_button(candidate) == notice_id:
                return candidate
        return None

    page = util.recover_search_page(page, config.source_url, target_page)
    target = find_on_current_page()
    if target is None:
        try:
            total_text = page.locator(
                "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_lblTotalPages"
            ).inner_text()
            total_pages = int(total_text.strip().split()[1])
        except Exception:
            total_pages = 1
        util.print_log(
            "Queued notice {} moved from page {}; scanning {} pages.".format(
                notice_id, target_page, total_pages
            )
        )
        for page_number in range(1, total_pages + 1):
            if page_number == target_page:
                continue
            page = util.recover_search_page(page, config.source_url, page_number)
            target = find_on_current_page()
            if target is not None:
                break
    if target is None:
        raise RuntimeError(
            "notice ID {} no longer present in {} search results".format(
                notice_id, config.code
            )
        )
    util.open_notice_detail(page, target)
    return page


def process_queue(db, config, limit=None):
    db.reset_processing_notices(config.code)
    tasks = db.pending_notices(config.code, limit)
    total = len(tasks)
    failures = []
    started = time.time()
    browser = page = None
    if config.adapter == "legacy_asp" and tasks:
        browser, page = util.init_driver()
    try:
        for count, task in enumerate(tasks, start=1):
            notice_id = str(task["Notice_Id"])
            db.mark_notice_processing(config.code, notice_id)
            try:
                existing = db.get_pub_record(config.notice_table, notice_id)
                if existing and existing.get("Notice"):
                    util.print_log("RESUME state={} notice_id={} already_saved=true".format(config.code, notice_id))
                elif config.adapter == "legacy_asp":
                    page = _open_legacy_task(page, config, task, notice_id)
                    page, record = util.get_data(page, db, config.code)
                    if not record or str(record.get("Id")) != notice_id:
                        raise RuntimeError("notice detail was not saved")
                    if not db.get_pub_record(config.notice_table, notice_id):
                        raise RuntimeError("notice database insert was not confirmed")
                else:
                    payload = _payload_dict(task.get("Payload"))
                    record = normalize_api_notice(config.code, payload, task["Source_Url"])
                    if not record["Id"]:
                        record["Id"] = notice_id
                    if not db.pub_data(record, config.notice_table):
                        raise RuntimeError("notice database insert returned false")
                db.mark_notice_complete(config.code, notice_id)
            except Exception as error:
                failures.append(notice_id)
                db.mark_notice_failed(config.code, notice_id, error)
                util.print_log("QUEUE_FAILED state={} notice_id={} error={}".format(config.code, notice_id, error), True)
            util.print_progress(
                config.code, "notices", count, total, started, count - len(failures)
            )
    finally:
        if browser is not None:
            browser.close()
    return failures


def enrich_propstream(db, config, limit=None):
    records = db.propstream_candidates(config.code, limit)
    if not records:
        return 0
    browser, page = util.init_driver()
    unresolved = 0
    succeeded = 0
    started = time.time()
    try:
        logged_in, propstream_session = util.login_propstream(page)
        if not logged_in:
            util.print_log("PropStream login failed; eligible records remain NULL.", True)
            return len(records)
        for count, record in enumerate(records, start=1):
            if count > 1 and (count - 1) % 400 == 0:
                logged_in, propstream_session = util.login_propstream(page)
            util.get_propstream_data(db, propstream_session, record, config.propstream_table)
            if record.get("propstream_info") in ("Y", "N"):
                succeeded += 1
                unresolved = 0
            else:
                unresolved += 1
            if unresolved >= 3:
                util.print_log("Refreshing PropStream login after 3 unresolved lookups.")
                logged_in, propstream_session = util.login_propstream(page)
                unresolved = 0
            time.sleep(random.randint(2, 5))
            util.print_progress(config.code, "propstream", count, len(records), started, succeeded)
        return len(records) - succeeded
    finally:
        browser.close()


def main(state, limit=None, discover_only=False, skip_propstream=False):
    config = get_state_config(state)
    if config.code not in NEW_STATE_CODES:
        raise ValueError("Use gapubs.py/ncpubs.py for GA/NC")
    db = Mysql(util.dev)
    try:
        discovered = discover(db, config, limit)
        util.print_log("DISCOVERY_COMPLETE state={} queued={}".format(config.code, discovered))
        if discover_only:
            return
        failures = process_queue(db, config, limit)
        if failures:
            raise RuntimeError(
                "{} notice task(s) failed; restart will retry only those IDs".format(len(failures))
            )
        if not skip_propstream:
            unresolved = enrich_propstream(db, config, limit)
            if unresolved:
                util.print_log(
                    "PropStream left {} record(s) NULL after lookup errors.".format(unresolved),
                    True,
                )
    finally:
        db.Close_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("state", choices=NEW_STATE_CODES)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--skip-propstream", action="store_true")
    args = parser.parse_args()
    main(args.state, args.limit, args.discover_only, args.skip_propstream)
