# -*- coding: utf-8 -*-
"""
Consolidated helper module: Playwright-based browser helpers + non-browser utilities.
This replaces multiple helper_*.py files. Keep this file as the canonical helper.
"""

import os
import json
import random
import logging
import time
import stat
import tempfile
import shutil
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI
import csv
import io
import pathlib
import requests
import re
from urllib.parse import urljoin
from pypdf import PdfReader


try:
    from anticaptchaofficial.recaptchav2proxyless import recaptchaV2Proxyless
except Exception:
    class recaptchaV2Proxyless:
        def __init__(self):
            self.error_code = "MISSING_LIB"
        def set_key(self, k):
            pass
        def set_website_url(self, url):
            pass
        def set_website_key(self, key):
            pass
        def solve_and_return_solution(self):
            return 0

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:
    sync_playwright = None
    class PlaywrightTimeoutError(Exception):
        pass

load_dotenv()

def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


dev = _env_flag("DEV_MODE")
FAST_MODE = _env_flag("FAST_MODE", not dev)
HEADLESS = _env_flag("HEADLESS", not dev)
# sleep scaling (set SLEEP_SCALE in env to override). Default is very small to speed scraping.
SLEEP_SCALE = float(os.environ.get("SLEEP_SCALE", "0.05" if FAST_MODE else "1.0"))
GRID_TIMEOUT_MS = int(os.environ.get("GRID_TIMEOUT_MS", "90000"))
NAVIGATION_RETRIES = max(1, int(os.environ.get("NAVIGATION_RETRIES", "3")))
NOTICE_RETRIES = max(1, int(os.environ.get("NOTICE_RETRIES", "2")))
PDF_TEXT_LIMIT = max(1000, int(os.environ.get("PDF_TEXT_LIMIT", "50000")))
RESUME_EXISTING = _env_flag("RESUME_EXISTING")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)

_pw_instance = None

# Fallback run id for CSV exports when DB is unavailable
FALLBACK_RUN_ID = datetime.now().strftime('%Y%m%d_%H%M%S')
EXCEL_ILLEGAL_CHARACTERS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def sanitize_excel_value(value):
    """Remove control characters that openpyxl rejects in worksheet cells."""
    if isinstance(value, str):
        return EXCEL_ILLEGAL_CHARACTERS.sub("", value)
    return value


def sanitize_excel_records(records):
    return [
        {key: sanitize_excel_value(value) for key, value in row.items()}
        for row in records
    ]


def _ensure_exports_dir():
    p = os.path.join(os.getcwd(), 'exports')
    os.makedirs(p, exist_ok=True)
    return p


def _save_record_to_csv(data, table_name):
    """Upsert one fallback row while keeping a stable, unioned CSV schema."""
    exports = _ensure_exports_dir()
    fname = os.path.join(exports, f"{table_name}_fallback_{FALLBACK_RUN_ID}.csv")
    incoming = {str(k): (v if v is not None else '') for k, v in data.items()}

    def record_key(row):
        for field in ("url", "Id", "address_db"):
            value = row.get(field)
            if value not in (None, ""):
                return field, str(value)
        notice = row.get("Notice")
        return ("Notice", str(notice)) if notice not in (None, "") else (None, None)

    try:
        rows = []
        fieldnames = []
        if pathlib.Path(fname).exists():
            with open(fname, "r", newline='', encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                fieldnames = list(reader.fieldnames or [])
                rows = list(reader)

        fieldnames.extend(key for key in incoming if key not in fieldnames)
        key = record_key(incoming)
        replaced = False
        if key[0]:
            for index, row in enumerate(rows):
                if record_key(row) == key:
                    rows[index] = {**row, **incoming}
                    replaced = True
                    break
        if not replaced:
            rows.append(incoming)

        fd, temp_name = tempfile.mkstemp(
            prefix="fallback_", suffix=".csv", dir=exports, text=True
        )
        os.close(fd)
        try:
            with open(temp_name, "w", newline='', encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
            os.replace(temp_name, fname)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        print_log(f"Wrote fallback record to {fname}")
        return fname
    except Exception as e:
        print_log(f"Failed to write fallback CSV: {e}", True)
        raise


# ---- Generic utilities (from original helper.py) ----

def print_log(text, error=False):
    text = str(text)
    if dev:
        try:
            print(text, flush=True)
        except UnicodeEncodeError:
            print(text.encode("ascii", "replace").decode("ascii"), flush=True)
    else:
        if error:
            logging.error(text.strip())
        else:
            logging.info(text.strip())


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


def print_progress(state, stage, processed, total, started, succeeded=None):
    """Emit one grep-friendly progress line with elapsed time and ETA."""
    elapsed = max(0.001, time.time() - started)
    processed = max(0, int(processed))
    total = max(0, int(total))
    remaining = max(0, total - processed)
    eta_seconds = (elapsed / processed) * remaining if processed else 0
    percent = (processed / total * 100.0) if total else 100.0
    finish_at = datetime.now() + timedelta(seconds=eta_seconds)
    parts = [
        "PROGRESS",
        "state={}".format(state),
        "stage={}".format(stage),
        "processed={}".format(processed),
        "total={}".format(total),
        "percent={:.1f}".format(percent),
    ]
    if succeeded is not None:
        parts.append("succeeded={}".format(succeeded))
    parts.extend(
        [
            "elapsed={}".format(time_elapsed_str(0, elapsed)),
            "eta={}".format(time_elapsed_str(0, eta_seconds)),
            "finish_at={}".format(finish_at.strftime("%Y-%m-%d_%H:%M:%S")),
        ]
    )
    print_log(" ".join(parts))


def call_chatgpt(text):
    prompt = """
    Extract property information from the foreclosure notice provided. Use the
    foreclosed/tax-sale property address, never a lender, law firm, courthouse,
    or mailing address. owner_name means borrower, debtor, defendant, current
    owner, or party in possession associated with that property. Output only one
    JSON object containing the fields below.

    - When a foreclosure listing or description is shared, carefully identify and extract:
    - Street: (full street address)
    - City: (name of the city)
    - Zip_Code: (5-digit postal code)
    - owner_name: (property owner or borrower name; join multiple owners with " & ")
    - parcel_number: (tax parcel/APN, when present)

    - Output only the following JSON structure:

    {
    "Street": "[Extracted street address]",
    "City": "[Extracted city name]",
    "Zip_Code": "[Extracted zip code]",
    "owner_name": "[Extracted owner or borrower name]",
    "parcel_number": "[Extracted parcel number]"
    }

    - If any element cannot be confidently determined, leave its value an empty string ("").
    - If there are any shortcut words in "Street" like "Road", "Street", "Avenue", or "Drive" then correct

    - Produce only the JSON—no markdown formatting, headers, code blocks, or explanatory text.
    """

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    response = client.responses.create(
        model="gpt-4.1",
        instructions=prompt,
        input=text,
    )
    return response.output_text



def solve_captcha_token(site_url, site_key, captcha_type="recaptcha"):
    client_key = os.environ.get("CAPTCHA_SOLVER_KEY")
    if not client_key:
        return 0, "ERROR_KEY_MISSING"
    task_payload = {
        "clientKey": client_key,
        "task": {
            "type": "TurnstileTaskProxyless" if captcha_type == "turnstile" else "RecaptchaV2TaskProxyless",
            "websiteURL": site_url,
            "websiteKey": site_key,
        },
    }
    try:
        create = requests.post("https://api.anti-captcha.com/createTask", json=task_payload, timeout=30).json()
    except Exception as e:
        return 0, f"REQUEST_ERROR:{type(e).__name__}:{e}"
    if create.get("errorId"):
        return 0, create.get("errorCode", "CREATE_TASK_ERROR")

    task_id = create.get("taskId")
    print_log(f"Captcha task created: {task_id}")
    deadline = time.time() + int(os.environ.get("CAPTCHA_TIMEOUT", "180"))
    while time.time() < deadline:
        time.sleep(5)
        try:
            result = requests.post(
                "https://api.anti-captcha.com/getTaskResult",
                json={"clientKey": client_key, "taskId": task_id},
                timeout=30,
            ).json()
        except Exception as e:
            return 0, f"REQUEST_ERROR:{type(e).__name__}:{e}"
        if result.get("errorId"):
            return 0, result.get("errorCode", "GET_RESULT_ERROR")
        if result.get("status") == "ready":
            solution = result.get("solution") or {}
            return solution.get("token") or solution.get("gRecaptchaResponse") or 0, ""
        print_log("Captcha task still processing...")
    return 0, "ERROR_CAPTCHA_TIMEOUT"

_NOTICE_FIELDS = ("Street", "City", "Zip_Code", "owner_name", "parcel_number")
_STREET_PATTERN = re.compile(
    r"(?P<street>\d{1,7}\s+[A-Z0-9][A-Z0-9 .#'&/-]{1,80}?\b(?:"
    r"ROAD|RD|STREET|ST|DRIVE|DR|AVENUE|AVE|LANE|LN|COURT|CT|"
    r"BOULEVARD|BLVD|HIGHWAY|HWY|WAY|TRAIL|TRL|PLACE|PL|CIRCLE|"
    r"CIR|PARKWAY|PKWY|TERRACE|TER))\b",
    re.IGNORECASE,
)
_PO_BOX_PATTERN = re.compile(
    r"^\s*(?:P\.?\s*O\.?|POST\s+OFFICE)\s+BOX\b", re.IGNORECASE
)


def _clean_notice_value(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip(" \t\r\n,;:-")


def _fallback_notice_fields(notice):
    """Extract common GA/NC property phrases when API output misses fields."""
    text = re.sub(r"\s+", " ", str(notice or "")).strip()
    result = {field: "" for field in _NOTICE_FIELDS}
    if not text:
        return result

    matches = list(_STREET_PATTERN.finditer(text))
    if matches:
        labels = (
            "commonly known as",
            "property known as",
            "known as",
            "l/k/a",
            "occupant",
            "property address",
        )

        def address_score(match):
            prefix = text[max(0, match.start() - 60):match.start()].lower()
            score = max(
                (100 + prefix.rfind(label) for label in labels if label in prefix),
                default=0,
            )
            if any(
                word in prefix
                for word in ("attorney", "counsel", "prepared by", "undersigned at")
            ):
                score -= 100
            return score

        chosen = max(matches, key=address_score)
        result["Street"] = _clean_notice_value(chosen.group("street"))
        tail = text[chosen.end():chosen.end() + 100]
        city_state = re.match(
            r"\s*,?\s*(?P<city>[A-Za-z][A-Za-z .'-]{1,45}?)\s*,?\s+"
            r"(?:GA|GEORGIA|NC|NORTH CAROLINA)\s+(?P<zip>\d{5})(?:-\d{4})?\b",
            tail,
            re.IGNORECASE,
        )
        if city_state:
            city = _clean_notice_value(city_state.group("city"))
            if not city.lower().endswith(" county"):
                result["City"] = city
            result["Zip_Code"] = city_state.group("zip")
        if not result["City"]:
            town = re.search(
                r"\b(?:Town|City) of\s+([A-Za-z][A-Za-z .'-]{1,45}?)(?:,|\s+County\b)",
                text,
                re.IGNORECASE,
            )
            if town:
                result["City"] = _clean_notice_value(town.group(1))

    parcel = re.search(
        r"(?:tax\s+parcel(?:\s+identification)?(?:\s+(?:number|no\.?))?|"
        r"parcel(?:\s+(?:number|no\.?|id(?:entification)?))?|APN)\s*[:#]?\s*"
        r"([A-Z0-9][A-Z0-9._/-]{3,40})",
        text,
        re.IGNORECASE,
    )
    if parcel:
        result["parcel_number"] = _clean_notice_value(parcel.group(1)).rstrip(".")

    owner_patterns = (
        r"same parcel conveyed to\s+(.+?)\s+in a deed",
        r"party in possession of the property is\s+(.+?)(?:\s+or tenant|;|\.)",
        r"as Attorney in Fact for\s+(.+?)(?:\.|$)",
        r"Security Deed given by\s+(.+?)(?:,?\s+(?:dated|to|Mortgage Electronic))",
        r"\b(?:v\.?s?\.?)\s+([^,]+)",
        r"\bTO:\s+(.+?)\s+(?:Occupant\s+\d|RE:\s+FORECLOSURE)",
    )
    for pattern in owner_patterns:
        owner = re.search(pattern, text, re.IGNORECASE)
        if owner:
            result["owner_name"] = _clean_notice_value(owner.group(1))
            break
    return result


def _decode_notice_json(raw):
    text = str(raw or "").strip()
    text = re.sub(r"^\`\`\`(?:json)?\s*|\s*\`\`\`$", "", text, flags=re.IGNORECASE)
    return json.loads(text)


def extract_pdf_text(page, pdf_url):
    """Download notice PDF with browser cookies and return embedded text."""
    full_url = urljoin(page.url, str(pdf_url or "").strip())
    if not full_url:
        return ""
    response = page.context.request.get(full_url, timeout=GRID_TIMEOUT_MS)
    if not response.ok:
        raise RuntimeError(
            "PDF download failed: {} {}".format(
                response.status, response.status_text
            )
        )
    reader = PdfReader(io.BytesIO(response.body()))
    text = "\n".join(pdf_page.extract_text() or "" for pdf_page in reader.pages)
    return text.strip()[:PDF_TEXT_LIMIT]


def parse_notice(notice):
    arr_response = {}
    fallback = _fallback_notice_fields(notice)
    try:
        print_log("Parsing Notice with ChatGPT...")
        result = call_chatgpt(notice)
        try:
            arr_response = _decode_notice_json(result)
        except json.JSONDecodeError:
            fix_notice = notice.replace('"', '').strip()
            print_log("Parsing Notice again...")
            arr_response = _decode_notice_json(call_chatgpt(fix_notice))
    except Exception as e:
        error_str = "\n{}: {}".format(str(type(e).__name__), str(e))
        print_log(error_str, True)

    if not isinstance(arr_response, dict):
        arr_response = {}
    merged = {}
    for field in _NOTICE_FIELDS:
        merged[field] = _clean_notice_value(arr_response.get(field)) or fallback[field]
    if not any(merged.values()):
        return {}
    merged["Address"] = str(
        bool(merged["Street"]) and not _PO_BOX_PATTERN.match(merged["Street"])
    )
    return merged


def is_propstream_eligible(record):
    """Require complete property location; incomplete records stay NULL."""
    street = _clean_notice_value((record or {}).get("Street"))
    city = _clean_notice_value((record or {}).get("City"))
    state = _clean_notice_value((record or {}).get("State"))
    return bool(street and city and state and not _PO_BOX_PATTERN.match(street))


def start_logger(limited, database, source):
    TABLE_Logger = "Logger"
    r_starts = 1
    r_finish = limited
    date_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    where_clause = "Data_Source = '{}'".format(source)
    stmt = "SELECT Next_Starts,Next_Finish FROM {} WHERE {}".format(TABLE_Logger, where_clause)
    sql = "({}) AS NUM".format(stmt)
    num = database.get_count(sql)
    if num:
        rows = database.show_data(TABLE_Logger, stmt)
        r_starts, r_finish = list(rows).pop()
        if not bool(r_starts):
            r_starts = 1
        if not bool(r_finish):
            r_finish = limited
    else:
        info = dict(Data_Source=source, Run_Time=date_now, Next_Starts=str(r_starts), Next_Finish=str(r_finish))
        columns_str = "`, `".join(info.keys())
        values = "', '".join(info.values())
        stmt = "INSERT INTO `{}` (`{}`) VALUES ('{}');".format(TABLE_Logger, columns_str, values)
        if not dev:
            try:
                database.run_query(stmt)
            except Exception as e:
                error_str = "{}: {}".format(str(type(e).__name__), str(e))
                error_sql = "SQL: '{}'".format(stmt)
                print_log(error_str, True)
                print_log(error_sql, True)
    return date_now, r_starts, r_finish


def calculate_run(urls, total_return, limited, r_starts, r_finish, full_data):
    all_pages = urls.copy()
    if total_return <= limited:
        if r_starts > 1:
            all_pages = urls[r_starts:].copy()
            if full_data and len(all_pages) <= limited and total_return <= limited:
                all_pages = urls[-limited:].copy()

        if r_starts <= total_return:
            r_starts = total_return
    else:
        if r_starts == 1:
            all_pages = urls[:limited].copy()
            r_starts = limited
        else:
            if full_data:
                all_pages = urls[r_starts:r_finish].copy()
            else:
                all_pages = urls[:limited].copy()
            r_starts += len(all_pages)

    if bool(all_pages):
        r_finish = r_starts + limited
    return all_pages, r_starts, r_finish


def update_logger(database, source, date_now, limited, r_starts, r_finish, total_return, urls, full=True):
    TABLE_Logger = "Logger"
    set_equal = list()
    set_equal.append("Run_Time = '{}'".format(date_now))
    set_equal.append("Starts = {}".format(r_starts))
    set_equal.append("Finish = {}".format(r_finish))
    set_equal.append("Total_Records = {}".format(total_return))

    all_pages, r_starts, r_finish = calculate_run(urls, total_return, limited, r_starts, r_finish, full)

    n_records = len(all_pages)
    set_equal.append("Scrapped = {}".format(n_records))
    set_equal.append("Next_Starts = {}".format(r_starts))
    set_equal.append("Next_Finish = {}".format(r_finish))

    equals = ", ".join(set_equal)
    where_clause = "Data_Source = '{}'".format(source)
    stmt = """UPDATE `{}` SET {} WHERE {}""".format(TABLE_Logger, equals, where_clause)
    if not dev:
        try:
            database.run_query(stmt)
        except Exception as e:
            error_str = "{}: {}".format(str(type(e).__name__), str(e))
            error_sql = "SQL: '{}'".format(stmt)
            print_log(error_str, True)
            print_log(error_sql, True)
    return all_pages


def get_db_data_for_truthfinder(dbase, table_name, limit=False):
    columns = ['Table_Index', 'Id', 'Street', 'City', 'Zip_Code', 'State', 'owner_name']
    column_names = ", ".join(columns)

    stmt = [
        "SELECT {} FROM {}".format(column_names, table_name),
        "WHERE Street != '' AND City != '' AND Zip_Code != ''"
    ]
    if table_name in ['GaPub', 'NcPub']:
        order = 'ORDER BY Date_Added DESC'
        stmt.append(order)
    if limit:
        limits = 'LIMIT {}'.format(limit)
        stmt.append(limits)
    db_query = " ".join(stmt)
    rows = dbase.show_data(table_name, db_query)
    db_data = [dict(zip(columns, row)) for row in list(rows)]
    return db_data


def names_match(text_words, name_words):
    name_word_count = sum(1 for word in name_words if word in text_words)
    return name_word_count >= 2


def wait_loader_truthfinder(a_page):
    try:
        a_page.wait_for_selector("xpath=//div[contains(@class, '_loader')]", timeout=15000)
        print_log("Loading...")
    except Exception:
        pass

    i = random.randint(2, 3)
    time.sleep(i)

    try:
        a_page.wait_for_selector("xpath=//div[contains(@class, '_loader')]", timeout=15000, state='detached')
    except Exception:
        pass

# ---- Playwright browser helpers (migrated) ----

def init_driver():
    global _pw_instance
    _pw_instance = sync_playwright().start()
    browser = _pw_instance.chromium.launch(
        headless=HEADLESS,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1300, "height": 1000},
    )
    page = context.new_page()
    return browser, page


def wait_loader(page, max_attempts=4):
    loader_id = "ctl00_ContentPlaceHolder1_UpdateProgress1"
    print_log("Loading...")
    attempt = 0
    # Use short timeouts and limited retries to avoid indefinite waiting
    while attempt < max_attempts:
        attempt += 1
        ms = max(500, int(random.randint(1, 3) * 1000 * max(SLEEP_SCALE, 0.02)))
        try:
            # if loader appears visible, wait briefly for it to hide
            page.wait_for_selector(f'#{loader_id}[aria-hidden="false"]', timeout=ms)
            # now wait for it to become hidden
            page.wait_for_selector(f'#{loader_id}[aria-hidden="true"]', timeout=ms * 2)
            return
        except PlaywrightTimeoutError:
            # if loader not found or didn't hide, continue to next attempt
            time.sleep(0.2)
            continue
    # fallback: short sleep to allow page to settle
    time.sleep(0.2)
    return


SEARCH_GRID_SELECTOR = "#ctl00_ContentPlaceHolder1_upSearch"
RESULTS_PER_PAGE_SELECTOR = (
    "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_ddlPerPage"
)
CURRENT_PAGE_SELECTOR = (
    "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_lblCurrentPage"
)
NEXT_PAGE_SELECTOR = (
    "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_btnNext"
)


def _wait_for_search_grid(page, timeout=None):
    timeout = timeout or GRID_TIMEOUT_MS
    if str(page.url).startswith("chrome-error://"):
        raise RuntimeError("Browser is on Chrome error page: {}".format(page.url))
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except PlaywrightTimeoutError:
        pass
    grid = page.wait_for_selector(SEARCH_GRID_SELECTOR, timeout=timeout)
    if not grid:
        raise RuntimeError("Search grid did not load at {}".format(page.url))
    return grid


def _set_max_results_per_page(page):
    page.wait_for_selector(
        RESULTS_PER_PAGE_SELECTOR, state="visible", timeout=GRID_TIMEOUT_MS
    )
    options = page.eval_on_selector_all(
        f"{RESULTS_PER_PAGE_SELECTOR} option", "opts => opts.map(o => o.value)"
    )
    if not options:
        raise RuntimeError("Results-per-page selector has no options")
    page.select_option(RESULTS_PER_PAGE_SELECTOR, value=options[-1])
    wait_loader(page)
    return _wait_for_search_grid(page)


def _current_search_page(page):
    try:
        current = page.wait_for_selector(
            CURRENT_PAGE_SELECTOR, timeout=min(GRID_TIMEOUT_MS, 15000)
        )
        return int(current.inner_text().strip())
    except Exception:
        return 1


def select_site_filters(page, days_back=None):
    """Apply foreclosure keyword filter and optional date range.
    days_back=None means clear the from-date (show all available notices from earliest to today).
    """
    filter_county = False

    keyword_field = page.wait_for_selector("#ctl00_ContentPlaceHolder1_as1_txtSearch", timeout=5000)
    keyword_field.fill("")
    keyword_field.type("fore")
    time.sleep(random.randint(2, 5) * SLEEP_SCALE)
    keyword_field.type("closure")  # type without Enter so we can set dates first

    # Set date range via JS BEFORE submitting (fields are hidden — bypass visibility check)
    try:
        from datetime import date, timedelta
        date_to = date.today().strftime("%m/%d/%Y")
        if days_back is not None:
            date_from = (date.today() - timedelta(days=days_back)).strftime("%m/%d/%Y")
        else:
            date_from = ""  # clear from-date so site returns all available notices
        page.evaluate("""([df, dt]) => {
            var fromEl = document.getElementById('ctl00_ContentPlaceHolder1_as1_txtDateFrom');
            var toEl   = document.getElementById('ctl00_ContentPlaceHolder1_as1_txtDateTo');
            if (fromEl) { fromEl.value = df; fromEl.dispatchEvent(new Event('change')); }
            if (toEl)   { toEl.value   = dt; toEl.dispatchEvent(new Event('change')); }
        }""", [date_from, date_to])
        if date_from:
            print_log(f"Date filter set: {date_from} → {date_to}")
        else:
            print_log(f"Date filter set: (earliest available) → {date_to}")
    except Exception as de:
        print_log(f"Date filter not applied: {de}", True)

    # Now submit the search
    if not filter_county:
        keyword_field.press("Enter")

    if filter_county:
        county_holder = page.wait_for_selector("#ctl00_ContentPlaceHolder1_as1_divCounty", timeout=5000)
        time.sleep(1)
        county_holder.locator("label a").click()
        time.sleep(random.randint(2, 5) * SLEEP_SCALE)

        li_tags = county_holder.locator("#ctl00_ContentPlaceHolder1_as1_lstCounty li").all()
        for li in li_tags:
            li_label = li.locator("label")
            if li_label.inner_text().strip() == "Douglas":
                li_label.scroll_into_view_if_needed()
                time.sleep(random.randint(2, 3) * SLEEP_SCALE)
                li_label.click()
                break

        page.wait_for_selector("#ctl00_ContentPlaceHolder1_as1_btnGo", timeout=5000).click()

    wait_loader(page)


def select_filters_again(page):
    select_site_filters(page)
    time.sleep(random.randint(1, 3) * SLEEP_SCALE)
    _set_max_results_per_page(page)


def recover_search_page(page, site_url, target_page=1):
    """Rebuild search state after interrupted navigation and return to target page."""
    last_error = None
    for attempt in range(1, NAVIGATION_RETRIES + 1):
        try:
            print_log(
                "Recovering search grid (attempt {}/{}, target page {})".format(
                    attempt, NAVIGATION_RETRIES, target_page
                )
            )
            page.goto(site_url, timeout=GRID_TIMEOUT_MS, wait_until="domcontentloaded")
            select_filters_again(page)
            current = _current_search_page(page)
            while current < target_page:
                next_btn = page.wait_for_selector(
                    NEXT_PAGE_SELECTOR, timeout=GRID_TIMEOUT_MS
                )
                if next_btn.get_attribute("disabled") is not None:
                    raise RuntimeError(
                        "Cannot recover target page {}; Next is disabled on page {}".format(
                            target_page, current
                        )
                    )
                next_btn.click()
                wait_loader(page)
                _wait_for_search_grid(page)
                new_current = _current_search_page(page)
                if new_current <= current:
                    raise RuntimeError("Search page did not advance from {}".format(current))
                current = new_current
            if current != target_page:
                raise RuntimeError(
                    "Recovered page {} instead of {}".format(current, target_page)
                )
            return page
        except Exception as error:
            last_error = error
            print_log(
                "Search recovery attempt {} failed: {}".format(attempt, error), True
            )
            if attempt < NAVIGATION_RETRIES:
                time.sleep(attempt * 2)
    raise RuntimeError(
        "Unable to recover search page {} after {} attempts: {}".format(
            target_page, NAVIGATION_RETRIES, last_error
        )
    )


def return_to_search_page(page, site_url, target_page):
    """Use session search URL first; fully rebuild filters if state is unhealthy."""
    import re as _re

    try:
        session = _re.search(r'/\(S\([^)]+\)\)/', str(page.url))
        search_url = (
            site_url.rstrip('/') + session.group(0) + "Search.aspx"
            if session
            else site_url + "Search.aspx"
        )
        page.goto(search_url, timeout=GRID_TIMEOUT_MS, wait_until="domcontentloaded")
        _wait_for_search_grid(page)
        if _current_search_page(page) != target_page:
            raise RuntimeError("Search session returned to wrong page")
        return page
    except Exception as error:
        print_log("Direct search return failed: {}; rebuilding search.".format(error), True)
        return recover_search_page(page, site_url, target_page)


def open_notice_detail(page, button):
    """Open embedded detail URL directly, avoiding fragile JavaScript history."""
    import urllib.parse

    onclick = button.get_attribute("onclick") or ""
    marker = "location.href='"
    if marker in onclick:
        relative_url = onclick.split(marker, 1)[1].split("'", 1)[0]
        detail_url = urllib.parse.urljoin(page.url, relative_url)
        page.goto(
            detail_url, timeout=GRID_TIMEOUT_MS, wait_until="domcontentloaded"
        )
    else:
        button.click()
    if "Details.aspx" not in str(page.url):
        raise RuntimeError("Notice button did not open a detail page")
    return page


def notice_id_from_button(button):
    """Extract stable public-notice ID without opening its detail page."""
    onclick = button.get_attribute("onclick") or ""
    match = re.search(r"[?&]ID=([^&'\"]+)", onclick, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def evaluate_pages_to_work(page, max_records=None):
    pages = []
    print_log("Page Loaded...")
    site_url = page.url
    search_grid = None
    last_error = None
    for attempt in range(1, NAVIGATION_RETRIES + 1):
        try:
            if attempt > 1:
                page.goto(
                    site_url, timeout=GRID_TIMEOUT_MS, wait_until="domcontentloaded"
                )
            select_site_filters(page)
            time.sleep(random.randint(1, 3) * SLEEP_SCALE)
            _set_max_results_per_page(page)
            print_log("\nWaiting for Search Grid")
            search_grid = _wait_for_search_grid(page)
            break
        except Exception as error:
            last_error = error
            print_log(
                "Initial grid attempt {}/{} failed: {}".format(
                    attempt, NAVIGATION_RETRIES, error
                ),
                True,
            )
    if search_grid is None:
        raise RuntimeError(
            "Unable to initialize notice search grid after {} attempts: {}".format(
                NAVIGATION_RETRIES, last_error
            )
        )

    if search_grid:
        page_current = 0
        try:
            lbl = page.wait_for_selector("#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_lblTotalPages", timeout=15000)
            page_last = int(lbl.inner_text().strip().split()[1])
        except Exception:
            page_last = 1
        print_log("There are {} Total Search Pages...\n".format(page_last))

        seen_pages = set()

        while page_current != page_last:
            _wait_for_search_grid(page)
            page_current = _current_search_page(page)

            print_log("-" * 80)
            print_log("Working on Page # {}".format(page_current))

            # Skip pages we've already processed (happens when page label hasn't updated yet)
            if page_current not in seen_pages:
                seen_pages.add(page_current)

                page.wait_for_selector(
                    "input.viewButton[onclick^='javascript']",
                    timeout=GRID_TIMEOUT_MS,
                )
                button_count = page.locator("input.viewButton[onclick^='javascript']").count()

                for x in range(1, button_count + 1):
                    row_id = 2 + x
                    id_str = f"0{row_id}" if row_id < 10 else str(row_id)
                    pages.append("{}_{}".format(page_current, id_str))

            if max_records and len(pages) >= max_records:
                break

            if page_current == page_last:
                break

            # Check if Next button is enabled before clicking
            try:
                next_btn = page.wait_for_selector(
                    NEXT_PAGE_SELECTOR, timeout=GRID_TIMEOUT_MS
                )
                is_disabled = next_btn.get_attribute("disabled")
                if is_disabled is not None:
                    print_log("Next button is disabled — reached last page")
                    break
            except Exception:
                print_log("Next button not found — stopping pagination")
                break

            print_log("Click Next Page...")
            next_btn.click()
            wait_loader(page)
            _wait_for_search_grid(page)
            w = random.randint(1, 3)
            print_log("Waiting {} seconds for Search Grid...".format(w))
            time.sleep(w)

    return pages[:max_records] if max_records else pages


def save_notice_record(database, record, table_name):
    """Persist every scraped notice, falling back only when DB write fails."""
    if database is not None:
        try:
            if database.pub_data(record, table_name):
                return "database"
            raise RuntimeError("Database notice write returned false")
        except Exception as error:
            print_log(
                "Unable to save notice in database: {}".format(error), True
            )
    _save_record_to_csv(record, table_name)
    return "csv"


def get_data(page, database, state_name):
    url = page.url
    move = False
    captcha = True

    FATAL_CAPTCHA_ERRORS = {"ERROR_ZERO_BALANCE", "ERROR_KEY_DOES_NOT_EXIST", "ERROR_WRONG_USER_KEY"}
    RETRYABLE_CAPTCHA_ERRORS = {"ERROR_NO_SLOT_AVAILABLE", "ERROR_CAPTCHA_UNSOLVABLE", "ERROR_BAD_DUPLICATES"}
    MAX_CAPTCHA_RETRIES = int(os.environ.get("CAPTCHA_MAX_RETRIES", "5"))
    captcha_attempts = 0

    try:
        while captcha and captcha_attempts < MAX_CAPTCHA_RETRIES:
            captcha_attempts += 1
            print_log("Starting capture")
            ms = random.randint(8, 15) * 1000
            em = page.wait_for_selector('[name="ctl00$ContentPlaceHolder1$PublicNoticeDetailsBody1$btnViewNotice"]', timeout=ms)
            captcha = bool(em)
            print_log("Button Exist = {}".format(captcha))

            recaptcha_elem = None
            try:
                recaptcha_elem = page.wait_for_selector("#recaptcha", timeout=ms)
            except PlaywrightTimeoutError:
                pass

            if recaptcha_elem:
                sitekey_clean = recaptcha_elem.get_attribute("data-sitekey")
                captcha_key = os.environ.get("CAPTCHA_SOLVER_KEY")
                if not captcha_key:
                    print_log("CAPTCHA_SOLVER_KEY is missing; cannot open notice detail", True)
                    break
                captcha_type = "turnstile" if str(sitekey_clean).startswith("0x") else "recaptcha"
                print_log(f"Captcha type: {captcha_type}; site key: {sitekey_clean}")
                g_response, captcha_error = solve_captcha_token(page.url or url, sitekey_clean, captcha_type)
                if g_response != 0:
                    print_log("Captcha Solved >>>")
                    # Inject token AND trigger the recaptcha callback so ASP.NET
                    # includes it in the POST body (plain innerHTML injection is not enough)
                    page.evaluate("""([token]) => {
                        const setValue = (selector) => {
                            const el = document.querySelector(selector);
                            if (el) {
                                el.style.display = '';
                                el.value = token;
                                el.innerHTML = token;
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                        };
                        setValue('#g-recaptcha-response');
                        setValue('textarea[name="g-recaptcha-response"]');
                        setValue('input[name="cf-turnstile-response"]');
                        setValue('textarea[name="cf-turnstile-response"]');

                        const callbackEl = document.querySelector('[data-callback]');
                        if (callbackEl) {
                            const cbName = callbackEl.getAttribute('data-callback');
                            if (cbName && typeof window[cbName] === 'function') {
                                try { window[cbName](token); } catch(e) {}
                            }
                        }

                        try {
                            const cfg = window.___grecaptcha_cfg;
                            if (cfg && cfg.clients) {
                                Object.values(cfg.clients).forEach((client) => {
                                    Object.values(client).forEach((v) => {
                                        if (v && typeof v.callback === 'function') {
                                            try { v.callback(token); } catch(e) {}
                                        }
                                    });
                                });
                            }
                        } catch(e) {}
                    }""", [g_response])                    # DO NOT click the button here — the callback already triggered the ASP.NET
                    # postback. Clicking the button would fire a second postback WITHOUT the captcha
                    # token, overriding the first response and hiding the content.
                    # Just wait for the content panel to appear from the callback's postback.
                    try:
                        page.wait_for_selector(
                            "#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_pnlNoticeContent",
                            timeout=30000,
                        )
                        move = True
                    except PlaywrightTimeoutError:
                        # Callback postback didn't produce content — try clicking button as fallback
                        print_log("Callback postback timed out — trying button click fallback", True)
                        try:
                            page.locator("#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_btnViewNotice").click()
                            page.wait_for_selector(
                                "#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_pnlNoticeContent",
                                timeout=20000,
                            )
                            move = True
                        except PlaywrightTimeoutError:
                            print_log(f"Notice content did not appear after captcha click (now at: {page.url})", True)
                            move = False
                    captcha = False
                else:
                    err = captcha_error
                    print_log(f"Captcha failed ({err}), attempt {captcha_attempts}/{MAX_CAPTCHA_RETRIES}", True)
                    if err in FATAL_CAPTCHA_ERRORS:
                        print_log("Unrecoverable captcha error - skipping notice detail", True)
                        move = False
                        break
                    w = random.randint(10, 20) if err in RETRYABLE_CAPTCHA_ERRORS else random.randint(3, 5)
                    print_log(f"Waiting {w} seconds before retry...")
                    time.sleep(w)
            else:
                # No recaptcha — click and wait for notice content (UpdatePanel or full nav)
                page.locator("#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_btnViewNotice").click()
                try:
                    page.wait_for_selector(
                        "#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_pnlNoticeContent",
                        timeout=30000,
                    )
                    move = True
                except PlaywrightTimeoutError:
                    print_log(f"Notice content did not appear after button click (now at: {page.url})", True)
                    move = False
                captcha = False
    except Exception as ex:
        print_log(f"get_data exception: {ex}", True)
        move = False

    web_scrape = {}
    if move:
        print_log(f"\nLoading Notice... (url: {page.url})")
        try:
            page.wait_for_selector("#content-sub", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        try:
            page.wait_for_selector("#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_PublicNoticeDetails1_lblPubName", timeout=30000)
            publisher = page.locator("#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_PublicNoticeDetails1_lblPubName").inner_text().strip()

            date_pub = page.locator("#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_lblPublicationDAte").inner_text().strip()
            date_format = "%A, %B %d, %Y"
            sql_date_format = "%Y-%m-%d"
            date_object = datetime.strptime(date_pub, date_format).date()
            sql_date_string = date_object.strftime(sql_date_format)

            county_name = page.wait_for_selector("#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_PublicNoticeDetails1_lblCounty", timeout=30000).inner_text().strip()

            page.wait_for_selector("#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_pnlNoticeContent", timeout=30000)
            notice = page.locator("#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_lblContentText").inner_text().strip()
            api_data = notice

            try:
                print_log("Looking for PDF link")
                ms = random.randint(2, 3) * 1000
                pdf_tag = page.wait_for_selector("#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_spanFileLink", timeout=ms)
                if pdf_tag:
                    pdf_url = page.locator("#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_spanFileLink a").first.get_attribute("href")
                    print_log("PDF File: '{}'".format(pdf_url))
                    try:
                        pdf_text = extract_pdf_text(page, pdf_url)
                        if pdf_text:
                            api_data = notice + "\n\nATTACHED PDF TEXT:\n" + pdf_text
                            print_log(
                                "Extracted {} characters from PDF.".format(
                                    len(pdf_text)
                                )
                            )
                        else:
                            print_log("PDF contains no extractable text.", True)
                    except Exception as pdf_error:
                        print_log(
                            "Unable to extract PDF text: {}".format(pdf_error), True
                        )
            except PlaywrightTimeoutError:
                print_log("No PDF File")

            web_scrape = {
                "Street": "",
                "City": "",
                "Zip_Code": "",
                "owner_name": "",
                "parcel_number": "",
                "Address": str(False),
            }
            has_address = False
            try:
                api_result = parse_notice(api_data)
                if api_result:
                    web_scrape.update(api_result)
                    has_address = bool(web_scrape.get("Street"))
            except Exception:
                pass

            info = {
                "State": state_name,
                "Id": url.split("=")[-1],
                "Notice": notice,
                "Publisher": publisher,
                "Date_Published": sql_date_string,
                "county": county_name,
                "page_url": url,
                "propstream_info": None,
            }
            web_scrape.update(info)

            if dev:
                print_log("-" * 20)
                for k, val in web_scrape.copy().items():
                    if k == "Notice":
                        continue
                    if isinstance(val, str):
                        web_scrape[k] = val.strip()
                        print_log("'{}': '{}'".format(k, val.strip()))
                    else:
                        print_log("'{}': {}".format(k, val))

            table_name = "NcPub" if state_name == "NC" else "GaPub"
            save_notice_record(database, web_scrape, table_name)

            if not has_address:
                print_log(
                    "Address information is missing; notice saved with propstream_info NULL."
                )

        except Exception as scrape_ex:
            print_log(f"Failed to scrape notice content at {page.url}: {scrape_ex}", True)

    return page, web_scrape


def get_all_pages(
    page, pagers, database, state, site_url=None, return_failures=False
):
    if site_url is None:
        site_url = "https://www.ncnotices.com/" if state == "NC" else "https://www.georgiapublicnotice.com/"
    print_log("Page Loaded...")
    all_records = []
    failures = []
    total_notices = len(pagers)
    processed_notices = 0
    progress_started = time.time()
    page_map = {}
    for pager in pagers:
        page_number, row_id = pager.split("_", 1)
        page_map.setdefault(int(page_number), []).append(row_id)

    if not page_map:
        print_log("No notice buttons were selected.", True)
        result = (page, all_records, failures)
        return result if return_failures else result[:2]

    inc = 1
    for page_number in sorted(page_map):
        try:
            page = recover_search_page(page, site_url, page_number)
        except Exception as error:
            print_log(
                "Skipping page {} because search recovery failed: {}".format(
                    page_number, error
                ),
                True,
            )
            failures.extend(
                "{}_{}".format(page_number, row_id)
                for row_id in page_map[page_number]
            )
            processed_notices += len(page_map[page_number])
            print_progress(
                state,
                "notices",
                processed_notices,
                total_notices,
                progress_started,
                len(all_records),
            )
            inc += len(page_map[page_number])
            continue

        print_log("-" * 80)
        print_log("Working on Page # {}".format(page_number))

        for id_val in list(page_map[page_number]):
            msg = "Working on Notice # {}".format(inc)
            print_log(msg + "-" * max(1, 60 - len(msg)))
            saved = False
            resumed = False

            for attempt in range(1, NOTICE_RETRIES + 1):
                try:
                    _wait_for_search_grid(page)
                    if _current_search_page(page) != page_number:
                        page = recover_search_page(page, site_url, page_number)

                    button_selector = (
                        f"#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_"
                        f"GridView1_ctl{id_val}_btnView2"
                    )
                    button = page.wait_for_selector(
                        button_selector, state="visible", timeout=GRID_TIMEOUT_MS
                    )
                    notice_id = notice_id_from_button(button)
                    if (
                        RESUME_EXISTING
                        and database is not None
                        and notice_id
                        and hasattr(database, "get_pub_record")
                    ):
                        existing = database.get_pub_record(
                            "NcPub" if state == "NC" else "GaPub", notice_id
                        )
                        if existing and existing.get("Notice"):
                            all_records.append(existing)
                            saved = True
                            resumed = True
                            print_log(
                                "RESUME state={} notice_id={} already_saved=true".format(
                                    state, notice_id
                                )
                            )
                            break
                    button.scroll_into_view_if_needed()
                    open_notice_detail(page, button)
                    page, record = get_data(page, database, state)
                    if not record or not record.get("Id"):
                        raise RuntimeError("Notice detail returned no record")
                    all_records.append(record)
                    saved = True
                    break
                except Exception as error:
                    print_log(
                        "Notice {} attempt {}/{} failed: {}".format(
                            inc, attempt, NOTICE_RETRIES, error
                        ),
                        True,
                    )
                finally:
                    if not resumed:
                        try:
                            page = return_to_search_page(page, site_url, page_number)
                        except Exception as recovery_error:
                            print_log(
                                "Notice {} search recovery failed: {}".format(
                                    inc, recovery_error
                                ),
                                True,
                            )

            if not saved:
                failures.append("{}_{}".format(page_number, id_val))
                print_log(
                    "Notice {} skipped after {} attempts; continuing run.".format(
                        inc, NOTICE_RETRIES
                    ),
                    True,
                )
            processed_notices += 1
            print_progress(
                state,
                "notices",
                processed_notices,
                total_notices,
                progress_started,
                len(all_records),
            )
            inc += 1

    result = (page, all_records, failures)
    return result if return_failures else result[:2]


# ---- Propstream / Truthfinder helpers (ported from Selenium to Playwright) ----

def make_address_db(array):
    return '{Street}, {City}, {State} {Zip_Code}'.format_map(array)


def request_function(url, headers, payload, a_session):
    if hasattr(a_session, "evaluate") and hasattr(a_session, "context"):
        result = a_session.evaluate(
            """async ([requestUrl, requestHeaders]) => {
                const response = await fetch(requestUrl, {
                    method: 'GET',
                    headers: requestHeaders,
                    credentials: 'include'
                });
                return {
                    status: response.status,
                    statusText: response.statusText,
                    body: await response.text()
                };
            }""",
            [url, headers],
        )
        status = int(result.get("status", 0))
        if status != 200:
            raise RuntimeError(
                "PropStream browser request failed: {} {}".format(
                    status, result.get("statusText", "")
                )
            )
        try:
            return json.loads(result.get("body", ""))
        except json.JSONDecodeError as error:
            raise ValueError("PropStream response was not valid JSON") from error

    response = a_session.get(url, headers=headers, data=payload, timeout=45)
    response.raise_for_status()
    return response.json()


def propstream_information(db_info, propstream_session):
    """Return a list of propstream suggestion IDs for the given address."""
    import urllib.parse
    address = make_address_db(db_info)
    print_log(f"Searching Propstream for: {address}")
    encoded = urllib.parse.quote_plus(address)
    url = "https://app.propstream.com/eqbackend/resource/auth/ps4/property/suggestionsnew?q={}".format(encoded)
    headers = {
        'authority': 'app.propstream.com',
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'referer': 'https://app.propstream.com/search',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': USER_AGENT,
    }
    data = request_function(url, headers, {}, propstream_session)

    ids = []
    if isinstance(data, list):
        suggestions = data
    elif isinstance(data, dict):
        suggestions = data.get('results')
        if suggestions is None:
            suggestions = data.get('data', [])
    else:
        raise ValueError(
            "Unexpected PropStream suggestions response: {}".format(type(data).__name__)
        )
    if not isinstance(suggestions, list):
        raise ValueError("PropStream suggestions payload is not a list")
    for item in suggestions:
        if isinstance(item, dict) and item.get('id') not in (None, ''):
            ids.append(item['id'])

    ids = list(dict.fromkeys(ids))
    print_log(f"Propstream returned {len(ids)} suggestion(s)")
    return ids


def get_propstream_address_details(prop_id, propstream_session):
    url = "https://app.propstream.com/eqbackend/resource/auth/ps4/property/{}?m=F".format(prop_id)
    headers = {
        'authority': 'app.propstream.com',
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'referer': 'https://app.propstream.com/search/{}'.format(prop_id),
        'sec-ch-ua': '"Not/A)Brand";v="99", "Google Chrome";v="115", "Chromium";v="115"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': USER_AGENT,
    }
    r = request_function(url, headers, {}, propstream_session)
    if not isinstance(r, dict) or not r:
        return {}

    owner_property = r.get('ownerProperty') or {}
    address = r.get('address') or {}
    graph = r.get('estimatedValueGraph') or {}
    last_year = 0
    try:
        last_year = graph.get('series', [])[0].get('points', [])[0].get('value', '')
    except Exception:
        last_year = 0

    return {
        'beds': owner_property.get('bedrooms', ''),
        'baths': owner_property.get('bathrooms', ''),
        'sqFt': owner_property.get('squareFeet', ''),
        'lot_size': owner_property.get('lot_size', ''),
        'year_built': r.get('yearBuilt', ''),
        'apn': r.get('apn', ''),
        'property_type': r.get('landUse', ''),
        'status': r.get('marketStatus', ''),
        'distressed': r.get('distressed', ''),
        'short_scale': r.get('shortSale', ''),
        'hoa_coa': r.get('hoaPresent', ''),
        'owner_type': r.get('ownerType', ''),
        'owner_status': r.get('ownerOccupancy', ''),
        'occupancy': r.get('occupancy', ''),
        'length_of_ownership': r.get('ownershipLength', ''),
        'purchase_method': r.get('purchaseMethod', ''),
        'county': address.get('countyName', ''),
        'estimated_value': owner_property.get('estimatedValue', ''),
        'last_year': last_year,
        'properties': r.get('propertiesOwned', ''),
        'avg_sale_price': r.get('compSaleAmount', ''),
        'days_on_market': r.get('compDaysOnMarket', ''),
        'open_mortgages': owner_property.get('openLiens', ''),
        'est_mortgage_balance': owner_property.get('openMortgageBalance', ''),
        'public_record': owner_property.get('lastSaleAmount', ''),
        'est_equity': owner_property.get('estimatedEquity', ''),
        'monthly_rent': r.get('rentAmount', ''),
        'gross_yield': r.get('grossYield', ''),
        'owner_name': r.get('owner1FullName', ''),
    }

def _notice_table_for_propstream(table_name, db_info):
    table_lower = str(table_name).lower()
    state = str(db_info.get("State", "")).upper()
    if table_lower.endswith("_ga") or state == "GA":
        return "GaPub"
    if table_lower.endswith("_nc") or state == "NC":
        return "NcPub"
    raise ValueError("Cannot determine source notice table for {}".format(table_name))


def _set_propstream_status(database, db_info, table_name, status):
    notice_id = db_info.get("Id")
    if notice_id in (None, ""):
        print_log("PropStream tag not saved: source notice has no Id.", True)
        return False
    if database is None:
        db_info["propstream_info"] = status
        return True
    if not hasattr(database, "set_propstream_info"):
        print_log("PropStream tag not saved: database helper lacks updater.", True)
        return False
    try:
        saved = database.set_propstream_info(
            _notice_table_for_propstream(table_name, db_info), notice_id, status
        )
    except Exception as error:
        print_log(
            "PropStream tag {} failed for {}: {}".format(status, notice_id, error), True
        )
        return False
    if saved:
        db_info["propstream_info"] = status
    return bool(saved)


def get_propstream_data(database, request_session, db_info, table_name):
    """Save valid details and apply Y/N only for conclusive lookup outcomes."""
    results = []
    row_index = db_info.get('Table_Index', 0)

    try:
        print_log("Getting Propstream information...")
        ids = propstream_information(db_info, request_session)
    except Exception as e:
        print_log("{}: {}".format(type(e).__name__, e), True)
        print_log("Unable to fetch Propstream information: '{}'".format(row_index), True)
        return results

    if not ids:
        _set_propstream_status(database, db_info, table_name, "N")
        return results

    print_log(f"Found {len(ids)} suggestions for row {row_index}")
    valid_saved = False
    database_saved = False

    for prop_id in ids:
        try:
            print_log(f"Getting details for Propstream ID: {prop_id}")
            try:
                prop_data = get_propstream_address_details(prop_id, request_session)
            except Exception as e:
                print_log(f"Failed to get details for {prop_id}: {type(e).__name__}: {e}", True)
                continue
            if not isinstance(prop_data, dict) or not prop_data:
                print_log(
                    "PropStream detail {} was empty; leaving source tag NULL.".format(
                        prop_id
                    ),
                    True,
                )
                continue

            prop_details = {
                'ga_id': db_info.get('Id', ''),
                'address_db': make_address_db(db_info),
                **prop_data,
                'url': f"https://app.propstream.com/search/{prop_id}",
            }
            saved_this_result = False
            try:
                if database is not None and hasattr(database, 'propstreams'):
                    saved_this_result = bool(
                        database.propstreams(table_name, prop_details)
                    )
                    database_saved = database_saved or saved_this_result
                else:
                    _save_record_to_csv(prop_details, table_name)
                    saved_this_result = True
            except Exception as e:
                print_log("{}: {}".format(type(e).__name__, e), True)
                print_log("Unable to save Propstreams data in database: '{}'".format(row_index), True)
                try:
                    _save_record_to_csv(prop_details, table_name)
                    saved_this_result = True
                except Exception as fallback_error:
                    print_log(
                        "Unable to save PropStream fallback: {}".format(fallback_error),
                        True,
                    )

            if saved_this_result:
                valid_saved = True
                results.append(prop_details)
        except Exception as e:
            print_log(f"Unexpected error processing prop id {prop_id}: {type(e).__name__}: {e}", True)
            continue

    if valid_saved and (database is None or database_saved):
        _set_propstream_status(database, db_info, table_name, "Y")
    elif ids:
        print_log(
            "Suggestions existed but no valid detail was stored; propstream_info remains NULL.",
            True,
        )
    return results


def compute_columns(records, pubs_rows=None):
    """
    Enrich a list of propstream or pubs record dicts with computed columns:
    - Date_Range: bucket string
    - Listing_Age_Days: integer
    - Foreclosure_Stage: heuristic string
    - Seller_Motivation, Competition, Risk_Level, Opportunity_Level: scores 0-100
    - Recommended_Action: categorical suggestion

    pubs_rows: optional list of source pubs dicts (each should include 'Id' and 'Date_Published') to match by 'ga_id'
    """
    if not isinstance(records, list):
        return records

    # build lookup by Id if pubs_rows provided
    pubs_map = {}
    if isinstance(pubs_rows, list):
        for p in pubs_rows:
            pid = str(p.get('Id') or p.get('Id', ''))
            if pid:
                pubs_map[pid] = p

    def safe_int(v, default=0):
        try:
            return int(float(v))
        except Exception:
            return default

    def safe_float(v, default=0.0):
        try:
            return float(v)
        except Exception:
            return default

    today = datetime.today().date()

    for rec in records:
        # Initialize fields
        rec.setdefault('Date_Range', '')
        rec.setdefault('Listing_Age_Days', '')
        rec.setdefault('Foreclosure_Stage', '')
        rec.setdefault('Seller_Motivation', '')
        rec.setdefault('Competition', '')
        rec.setdefault('Risk_Level', '')
        rec.setdefault('Opportunity_Level', '')
        rec.setdefault('Recommended_Action', '')

        # Try to find a date from either pubs_rows (via ga_id) or direct field
        notice_date = None
        # check direct common fields
        for date_field in ('Date_Published', 'date_published', 'NoticeDate', 'notice_date', 'Date'):
            if date_field in rec and rec[date_field]:
                try:
                    notice_date = datetime.strptime(rec[date_field], '%m/%d/%Y').date()
                except Exception:
                    try:
                        notice_date = datetime.fromisoformat(rec[date_field]).date()
                    except Exception:
                        notice_date = None
                if notice_date:
                    break

        ga_id = str(rec.get('ga_id') or rec.get('Id') or '')
        if not notice_date and ga_id and ga_id in pubs_map:
            pub = pubs_map[ga_id]
            dp = pub.get('Date_Published') or pub.get('Date') or pub.get('date_published')
            if dp:
                try:
                    notice_date = datetime.strptime(dp, '%m/%d/%Y').date()
                except Exception:
                    try:
                        notice_date = datetime.fromisoformat(dp).date()
                    except Exception:
                        notice_date = None

        # Compute listing age and range
        age_days = None
        if notice_date:
            age_days = (today - notice_date).days
            rec['Listing_Age_Days'] = age_days
            if age_days <= 7:
                rec['Date_Range'] = '0-7'
            elif age_days <= 30:
                rec['Date_Range'] = '8-30'
            elif age_days <= 90:
                rec['Date_Range'] = '31-90'
            elif age_days <= 365:
                rec['Date_Range'] = '91-365'
            else:
                rec['Date_Range'] = '365+'
        else:
            rec['Listing_Age_Days'] = ''
            rec['Date_Range'] = ''

        # Foreclosure stage heuristic: look for keywords
        notice_text = (rec.get('Notice') or rec.get('notice') or '')
        stage = ''
        if notice_text:
            nt = notice_text.lower()
            if 'foreclos' in nt or 'sheriff' in nt or 'trustee' in nt:
                if age_days is not None and age_days > 90:
                    stage = 'Late'
                elif age_days is not None and age_days > 30:
                    stage = 'Scheduled'
                else:
                    stage = 'Initial'
            elif 'notice to creditors' in nt or 'probate' in nt:
                stage = 'Probate/Other'
            else:
                stage = 'Unknown'
        else:
            # fallback to propstream 'distressed' flag
            if str(rec.get('distressed')).lower() in ['true', '1', 'yes']:
                stage = 'Distressed'
            else:
                stage = 'Unknown'
        rec['Foreclosure_Stage'] = stage

        # Numeric inputs for scoring
        est_value = safe_float(rec.get('estimated_value', 0))
        est_equity = safe_float(rec.get('est_equity', 0))
        open_mortgages = safe_int(rec.get('open_mortgages', 0))
        properties_owned = safe_int(rec.get('properties', 0))
        owner_occ = str(rec.get('owner_status') or rec.get('ownerOccupancy') or rec.get('owner_occupancy') or '').lower()

        equity_pct = None
        if est_value > 0:
            try:
                equity_pct = max(0.0, min(100.0, (est_equity / est_value) * 100.0))
            except Exception:
                equity_pct = None
        if equity_pct is None:
            equity_pct = 50.0

        # seller motivation: older listings + low equity => higher motivation
        age_score = 0.0
        if age_days is not None:
            age_score = min(100.0, (age_days / 365.0) * 100.0)
        seller_motivation = int(max(0, min(100, (age_score * 0.6 + (100.0 - equity_pct) * 0.4))))

        # competition: fewer properties owned => less competition
        competition = 50
        if properties_owned > 0:
            competition = int(max(0, min(100, 100 - properties_owned * 10)))

        # risk: low equity, many liens, non-owner-occupied increase risk
        risk = int(max(0, min(100, ((100.0 - equity_pct) * 0.5) + (min(open_mortgages, 5) / 5.0 * 100.0) * 0.3 + (0 if 'owner' in owner_occ else 30) * 0.2)))

        # opportunity: combine motivation and low risk
        opportunity = int(max(0, min(100, (seller_motivation * 0.7 + (100 - risk) * 0.3))))

        # recommended action
        if opportunity >= 70:
            action = 'Make Offer'
        elif opportunity >= 40:
            action = 'Contact Owner'
        elif opportunity >= 20:
            action = 'Monitor / Research'
        else:
            action = 'Low Priority'

        rec['Seller_Motivation'] = seller_motivation
        rec['Competition'] = competition
        rec['Risk_Level'] = risk
        rec['Opportunity_Level'] = opportunity
        rec['Recommended_Action'] = action

    return records


def enrich_pubs_csv(csv_path, out_path=None):
    """
    Read a pubs CSV, compute enrichment columns, and write an enriched CSV to out_path.
    Returns the path to the enriched CSV.
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(csv_path)
    rows = []
    with open(csv_path, 'r', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            rows.append(r)
    if not rows:
        raise ValueError('No rows in ' + csv_path)
    # compute columns using compute_columns (it expects list of records)
    enriched = compute_columns(rows, rows)
    out_dir = _ensure_exports_dir()
    ts = FALLBACK_RUN_ID
    if not out_path:
        base = os.path.basename(csv_path)
        name = os.path.splitext(base)[0]
        out_path = os.path.join(out_dir, f"{name}_enriched_{ts}.csv")
    with open(out_path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted(enriched[0].keys()))
        writer.writeheader()
        for r in enriched:
            writer.writerow(r)
    print_log(f'Wrote enriched pubs CSV: {out_path}')
    return out_path


def login_propstream(page):
    request_session = requests.Session()
    logged_in = False
    website = 'https://login.propstream.com/'
    propstream_email = os.environ.get("PROPSTREAM_EMAIL")
    propstream_pwd = os.environ.get("PROPSTREAM_PASSWORD")

    def submit_once(attempt):
        page.goto(website, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_selector("#form-content", timeout=60000)
        print_log("Login Page loaded" if attempt == 1 else "Login Page reloaded")

        try:
            page.locator("#onetrust-accept-btn-handler").click(timeout=8000)
            print_log("Accept All Cookies")
        except Exception:
            print_log("No cookie popup")

        email_input = page.locator("input[name='username'], input[type='email']").first
        email_input.wait_for(state="visible", timeout=60000)
        email_input.click()
        email_input.fill("")
        email_input.type(propstream_email, delay=35)
        email_input.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")

        password_input = page.locator("input[name='password'], input[type='password']").first
        password_input.wait_for(state="visible", timeout=60000)
        password_input.click()
        password_input.fill("")
        password_input.type(propstream_pwd, delay=35)
        password_input.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")

        login_btn = page.locator("#form-content form button, button[type='submit']").first
        login_btn.wait_for(state="visible", timeout=60000)
        try:
            page.wait_for_function("btn => !btn.disabled", arg=login_btn.element_handle(), timeout=10000)
        except Exception:
            pass

        print_log("Submit" if attempt == 1 else "Submit retry")
        login_btn.click(timeout=15000, force=True)
        try:
            page.wait_for_url("**app.propstream.com**", timeout=90000)
            return True
        except Exception:
            return "app.propstream.com" in page.url

    try:
        if not propstream_email or not propstream_pwd:
            raise RuntimeError("PROPSTREAM_EMAIL or PROPSTREAM_PASSWORD is missing")

        for attempt in range(1, 3):
            if submit_once(attempt):
                logged_in = True
                break
            if attempt == 1:
                print_log("Propstream did not redirect after submit; retrying fresh login")
                time.sleep(3)

        n_ms = 15000
        success_selectors = [
            ".src-app-Search-Header-style__OvptX__appHeader",
            "input[placeholder*='Search']",
            "text=Dashboard",
            "text=My Properties",
        ]
        if logged_in:
            for selector in success_selectors:
                try:
                    page.wait_for_selector(selector, timeout=n_ms)
                    break
                except Exception:
                    continue
        if not logged_in:
            raise RuntimeError(f"Propstream login did not reach dashboard; current url: {page.url}")

        cookies = page.context.cookies()
        for cookie in cookies:
            request_session.cookies.set(cookie['name'], cookie['value'])

        print_log("Logging in successfully ...")
        request_session = page
    except Exception as e:
        print_log("{}: {}".format(type(e).__name__, e), True)
        logged_in = False
        print_log("Unable to Login...", True)
        try:
            screenshot_path = os.path.join(
                _ensure_exports_dir(), "propstream_login_failed.png"
            )
            page.screenshot(path=screenshot_path, full_page=True)
            print_log("PropStream login failure screenshot saved.")
        except Exception as screenshot_error:
            print_log(
                "Unable to save login failure screenshot: {}".format(
                    screenshot_error
                ),
                True,
            )

    return logged_in, request_session

def _login_to_email(page, email, password):
    try:
        page.wait_for_selector("#details-button", timeout=15000)
        page.click("#details-button")
        page.click("#proceed-link")
    except Exception as e:
        print_log("{}: {}".format(type(e).__name__, e), True)
        print_log("Login to Email for verification: All clear", True)

    page.wait_for_selector("#user", timeout=10000)
    time.sleep(random.randint(1, 2))
    page.fill("#user", email)
    page.fill("#pass", password)
    time.sleep(random.randint(1, 2))
    page.click("#login_submit")


def _click_mail_to_verify(email_page):
    nn_ms = 60 * 5 * 1000
    email_page.wait_for_selector("#messagelist", timeout=30000)

    i = random.randint(10, 15)
    print_log("Waiting {} seconds before refresh".format(i))
    time.sleep(i)

    for _ in range(10):
        try:
            email_page.wait_for_selector("#rcmbtn115", timeout=5000)
            email_page.click("#rcmbtn115")
            time.sleep(1)
        except Exception:
            pass

    email_page.wait_for_selector("#messagelist", timeout=30000)
    msg = email_page.wait_for_selector("xpath=//*[@id]/td[2]/span[4]/a/span", timeout=nn_ms)
    time.sleep(random.randint(1, 2))
    msg.click()

    time.sleep(3)
    frame = email_page.frame(name="messagecontframe")

    verify_xpath = 'xpath=//*[@id="message-htmlpart1"]/div/center/div/table/tbody/tr[2]/td/table/tbody/tr/td/table/tbody/tr/td[2]/a'
    time.sleep(random.randint(1, 2))

    with email_page.context.expect_page(timeout=30000) as new_page_info:
        if frame:
            frame.click(verify_xpath)
        else:
            email_page.click(verify_xpath)
    new_page = new_page_info.value
    new_page.wait_for_load_state("domcontentloaded")

    time.sleep(random.randint(1, 2))
    complete_str = ""
    try:
        token_div = new_page.wait_for_selector("#verification-token", timeout=60000)
        h3_tag = token_div.wait_for_selector("h3", timeout=nn_ms)
        complete_str = h3_tag.inner_text().strip()
        print_log(complete_str)
    except Exception as e:
        new_page.close()
        time.sleep(1)
        print_log("{}: {}".format(type(e).__name__, e), True)
        print_log("Click mail to verify has issue", True)
        complete_str = _click_mail_to_verify(email_page)
    else:
        try:
            new_page.close()
        except Exception:
            pass

    return complete_str


def login_truthfinder(page):
    logged_in = True
    website = 'https://www.truthfinder.com/'
    truth_email = os.environ.get("TRUTHFINDER_EMAIL")
    truth_pwd = os.environ.get("TRUTHFINDER_PASSWORD")
    try:
        page.goto(website, timeout=60000, wait_until="domcontentloaded")
        print_log("Page Loaded...")

        # Close/agree warning modal if present
        try:
            modal_btn = page.wait_for_selector("#warning-modal button", timeout=5000)
            if modal_btn:
                modal_btn.click()
                print_log("Clicked Agree")
        except Exception:
            pass

        # Try header login; if not present, navigate directly to login page
        try:
            page.wait_for_selector("#header-login", timeout=10000)
            time.sleep(1)
            page.click("#header-login")
        except Exception:
            print_log("Header login not found — navigating to /login")
            page.goto("https://www.truthfinder.com/login", timeout=60000, wait_until="domcontentloaded")

        # Flexible selectors for username/email input
        email_selectors = [
            "xpath=//*[@id='login']/div/div[2]/form/div[1]/input",
            "css=input[name='email']",
            "css=input[type='email']",
            "css=input#email",
        ]
        email_input = None
        for sel in email_selectors:
            try:
                email_input = page.wait_for_selector(sel, timeout=10000)
                if email_input:
                    break
            except Exception:
                continue
        if not email_input:
            raise Exception("Login email input not found")

        time.sleep(1)
        email_input.fill(truth_email or "")

        pwd_selectors = [
            "xpath=//*[@id='login']/div/div[2]/form/div[2]/input",
            "css=input[name='password']",
            "css=input[type='password']",
        ]
        pwd_input = None
        for sel in pwd_selectors:
            try:
                pwd_input = page.wait_for_selector(sel, timeout=5000)
                if pwd_input:
                    break
            except Exception:
                continue
        if not pwd_input:
            raise Exception("Password input not found")

        time.sleep(1)
        pwd_input.fill(truth_pwd or "")

        # Click submit — try common selectors
        btn_selectors = [
            "xpath=//*[@id='login']/div/div[2]/form/div[3]/button",
            "css=button[type='submit']",
        ]
        clicked = False
        for sel in btn_selectors:
            try:
                btn = page.wait_for_selector(sel, timeout=5000)
                btn.click()
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            # As a last resort, press Enter in password field
            try:
                pwd_input.press('Enter')
                clicked = True
            except Exception:
                pass
        
        # Wait for either verification prompt or dashboard
        try:
            page.wait_for_selector("xpath=//*[@id='verification']/div/div[2]/button", timeout=60000)
            page.click("xpath=//*[@id='verification']/div/div[2]/button")
        except Exception:
            # Maybe logged in already or different flow — proceed
            pass

        # Handle email verification via webmail if required
        try:
            i = random.randint(3, 5)
            print_log("Waiting {} seconds...".format(i))
            time.sleep(i)

            web_email = os.environ.get("WEB_EMAIL")
            web_password = os.environ.get("WEB_PASSWORD")
            email_page = page.context.new_page()
            email_page.goto('http://client1.jewelercart.com:2096/', timeout=60000, wait_until="domcontentloaded")

            i = random.randint(3, 5)
            print_log("Waiting {} seconds to switch window".format(i))
            time.sleep(i)

            _login_to_email(email_page, web_email, web_password)

            try:
                verify = _click_mail_to_verify(email_page)
                if verify and isinstance(verify, str) and verify.lower() == "verification complete":
                    print_log("Logging in successfully ...")
                else:
                    print_log("Unable to login")
                    logged_in = False
            except Exception as e:
                print_log("{}: {}".format(type(e).__name__, e), True)
                print_log("Error: Unable to login: _click_mail_to_verify()", True)

            try:
                email_page.close()
            except Exception:
                pass
        except Exception:
            # If webmail flow fails, don't treat as fatal here — rely on logged_in flag
            pass

    except Exception as e:
        print_log("{}: {}".format(type(e).__name__, e), True)
        logged_in = False
        print_log("There was an issue: Login to truth finder", True)
    return logged_in


def get_truthfinder_data(page, db_info, database, table_name):
    address_db = make_address_db(db_info)
    try:
        print_log("Fetching data from Truthfinder...")
        name_words = db_info['owner_name']
        print_log("Searching for address: '{}'".format(address_db))
        try:
            street, city, rem = [a.strip() for a in address_db.split(',')]
            state, zip_code = rem.split()
        except Exception as e:
            print_log("{}: {}".format(type(e).__name__, e), True)
            print_log("Unable to split address: '{}'".format(address_db), True)
            return page

        try:
            search_tag = page.wait_for_selector("xpath=//div[contains(@class, '_fauxSearchInput')]", timeout=30000)
            i = random.randint(2, 3)
            print_log("clicking Search in {} seconds...".format(i))
            time.sleep(i)
            search_tag.click()

            page.wait_for_selector("xpath=//ul[contains(@class, '_searchIcons')]", timeout=30000)
            li_tags = page.locator("xpath=//ul[contains(@class, '_searchIcons')]//li").all()
            last_tag = li_tags[-1]
            time.sleep(random.randint(1, 2))
            last_tag.click()

            page.wait_for_selector("xpath=//form[contains(@class, '_desktopSearchTabsHeader')]", timeout=30000)
            time.sleep(1)
            page.fill("input[name='street']", street)
            time.sleep(1)
            page.fill("input[name='city']", city)
            time.sleep(1)
            page.fill("input[name='zip']", zip_code)
            time.sleep(1)
            page.select_option("select[name='state']", value=state)
            time.sleep(1)
            page.click("xpath=//form[contains(@class, '_desktopSearchTabsHeader')]//button")
        except Exception as e:
            print_log("{}: {}".format(type(e).__name__, e), True)
            print_log("Unable to Search address: '{}'".format(address_db), True)

        try:
            n_ms = 60 * 5 * 1000
            print_log("Getting address details")
            wait_loader_truthfinder(page)

            io = random.randint(2, 5)
            print_log("Waiting {} seconds...".format(io))
            time.sleep(io)

            try:
                view_report = page.wait_for_selector("xpath=//a[contains(@class, '_reportLink')]", timeout=n_ms)
                time.sleep(1)
                view_report.click()
                wait_loader_truthfinder(page)

                view_detail = page.wait_for_selector("xpath=//button[contains(@class, 'viewDetailedReportBtn')]", timeout=n_ms)
                time.sleep(1)
                view_detail.click()
            except Exception:
                page.reload()

            page.wait_for_selector("xpath=//div[contains(@class, '_scrollContainer')]", timeout=30000)
            page.locator("xpath=//div[contains(@class, '_scrollContainer')]").locator(".residents").first.click()

            page.wait_for_selector("#residents", timeout=30000)
            page.wait_for_selector("xpath=//div[contains(@class, '_recordSubsectionCardContainer')]", timeout=30000)
            nametag_list = page.locator("xpath=//div[contains(@class, '_residentsSubsectionItem')]").all()

            profile_data = []
            for name_tag in nametag_list:
                try:
                    name_str = name_tag.locator("h3").first.inner_text().strip()
                    profile = {'name': name_str, 'is_match': 'False'}
                    try:
                        name_raw = [n.strip() for n in name_str.split(',')]
                        name, age_value = name_raw
                        age = int(age_value.split()[0])
                        profile['name'] = name
                        profile['age'] = age
                    except Exception:
                        name = name_str.strip()

                    sep = ":::"
                    if sep in name_words:
                        for n_word in name_words.split(sep):
                            if names_match(name.lower(), n_word.lower().split()):
                                profile['is_match'] = 'True'
                                break
                    else:
                        if names_match(name.lower(), name_words.lower().split()):
                            profile['is_match'] = 'True'

                    profile_link = name_tag.locator("a").first.get_attribute('href')
                    profile['link'] = profile_link
                    profile['address_db'] = address_db
                    profile_data.append(profile)
                except Exception as e:
                    print_log("{}: {}".format(type(e).__name__, e), True)
                    print_log("Unable to read profile name of an address: '{}'".format(address_db), True)

            print_log("Parsing {:,} profiles...".format(len(profile_data)))
            for profile in profile_data:
                try:
                    prof_link = profile['link']
                    prof_name = profile['name']
                    print_log("\tWorking on Profile: '{}'".format(prof_name))
                    try:
                        page.goto(prof_link, timeout=60000, wait_until="domcontentloaded")
                        wait_loader_truthfinder(page)

                        view_prof = page.wait_for_selector("xpath=//button[contains(@class, 'viewDetailedReportBtn')]", timeout=n_ms)
                        print_log("\tProfile Loaded: '{}'".format(prof_name))
                        view_prof.click()

                        page.wait_for_selector("xpath=//div[contains(@class, '_scrollContainer')]", timeout=30000)
                        page.locator("xpath=//div[contains(@class, '_scrollContainer')]").locator(".contact").first.click()

                        contact_div = page.wait_for_selector("#contact", timeout=30000)
                        h_tags = contact_div.locator("h2").all()
                    except Exception as e:
                        print_log("{}: {}".format(type(e).__name__, e), True)
                        print_log("Unable to load profile '{}': '{}'".format(prof_name, prof_link), True)
                        continue

                    phones = []
                    emails_list = []
                    for h2_el in h_tags:
                        head_name = h2_el.inner_text().strip().lower()
                        class_name = '_phonesSubsectionItem' if head_name == 'phone numbers' else '_emailsSubsectionItem'
                        sibling_div = h2_el.locator("xpath=following-sibling::*[1]")
                        infos = sibling_div.locator("xpath=//div[contains(@class, '{}')]".format(class_name)).all()
                        for info in infos:
                            m_tag = info.locator("p").first
                            if head_name == 'phone numbers':
                                info_div = m_tag.locator("xpath=following-sibling::*[1]")
                                phone = info_div.inner_text().strip()
                                phones.append(phone)
                            else:
                                email = m_tag.inner_text().strip()
                                emails_list.append(email)

                    profile['phone'] = ",".join(phones) if phones else ''
                    profile['email'] = ",".join(emails_list) if emails_list else ''
                except Exception as e:
                    print_log("{}: {}".format(type(e).__name__, e), True)
                    print_log("Unable to parse emails and phones", True)

                io = random.randint(2, 5)
                print_log("\tWaiting {} seconds...".format(io))
                time.sleep(io)

            if profile_data:
                try:
                    database.truthfinder(table_name, profile_data)
                except Exception as e:
                    print_log("{}: {}".format(type(e).__name__, e), True)
                    print_log("Unable to save Truthfinder data in database: '{}'".format(address_db), True)

        except Exception as e:
            print_log("{}: {}".format(type(e).__name__, e), True)
            print_log("Unable to work for Truthfinder: '{}'".format(address_db), True)

    except Exception as e:
        print_log("{}: {}".format(type(e).__name__, e), True)
        print_log("Cannot Parse Address: '{}'".format(address_db), True)
    return page
