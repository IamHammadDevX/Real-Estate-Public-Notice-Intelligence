# -*- coding: utf-8 -*-
"""
Playwright-based browser automation — replaces Selenium functions in helper.py.
Non-browser utilities (parse_notice, call_chatgpt, start_logger, etc.)
remain in helper.py and are re-imported from there.
"""

import os
import random
import time
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:
    sync_playwright = None
    class PlaywrightTimeoutError(Exception):
        pass

try:
    from anticaptchaofficial.recaptchav2proxyless import recaptchaV2Proxyless
except Exception:
    # Provide a dummy solver so code can run lint/static analysis without the package
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
    from helper import print_log, parse_notice
except Exception:
    def print_log(text, error=False):
        if error:
            print("ERROR:", text)
        else:
            print(text)
    def parse_notice(html):
        return {}


dev = bool(os.environ.get("DEV_MODE"))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)

_pw_instance = None  # keep playwright context alive


def init_driver():
    global _pw_instance
    _pw_instance = sync_playwright().start()
    browser = _pw_instance.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1300, "height": 1000},
    )
    page = context.new_page()
    return browser, page


def wait_loader(page):
    loader_id = "ctl00_ContentPlaceHolder1_UpdateProgress1"
    print_log("Loading...")
    waits = True
    while waits:
        ms = random.randint(2, 5) * 1000
        try:
            page.wait_for_selector(
                f'#{loader_id}[aria-hidden="false"]', timeout=ms
            )
        except PlaywrightTimeoutError:
            pass
        try:
            page.wait_for_selector(
                f'#{loader_id}[aria-hidden="true"]', timeout=ms
            )
            waits = False
        except PlaywrightTimeoutError:
            waits = True


def select_site_filters(page):
    filter_county = False

    keyword_field = page.wait_for_selector(
        "#ctl00_ContentPlaceHolder1_as1_txtSearch", timeout=30000
    )
    keyword_field.fill("")
    keyword_field.type("fore")
    time.sleep(random.randint(2, 5))

    tt = "closure" if filter_county else "closure\n"
    keyword_field.type(tt)

    if filter_county:
        county_holder = page.wait_for_selector(
            "#ctl00_ContentPlaceHolder1_as1_divCounty", timeout=30000
        )
        time.sleep(1)
        county_holder.locator("label a").click()
        time.sleep(random.randint(2, 5))

        li_tags = county_holder.locator(
            "#ctl00_ContentPlaceHolder1_as1_lstCounty li"
        ).all()
        for li in li_tags:
            li_label = li.locator("label")
            if li_label.inner_text().strip() == "Douglas":
                li_label.scroll_into_view_if_needed()
                time.sleep(random.randint(2, 3))
                li_label.click()
                break

        page.wait_for_selector(
            "#ctl00_ContentPlaceHolder1_as1_btnGo", timeout=30000
        ).click()

    wait_loader(page)


def select_filters_again(page):
    select_site_filters(page)

    ddl = "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_ddlPerPage"
    page.wait_for_selector(ddl, state="visible", timeout=30000)
    options = page.eval_on_selector_all(
        f"{ddl} option", "opts => opts.map(o => o.value)"
    )
    num_str = options[-1]
    time.sleep(random.randint(1, 3))
    page.select_option(ddl, value=num_str)


def evaluate_pages_to_work(page):
    pages = []
    print_log("Page Loaded...")
    select_site_filters(page)

    ddl = "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_ddlPerPage"
    page.wait_for_selector(ddl, state="visible", timeout=30000)
    options = page.eval_on_selector_all(
        f"{ddl} option", "opts => opts.map(o => o.value)"
    )
    num_str = options[-1]
    time.sleep(random.randint(1, 3))
    page.select_option(ddl, value=num_str)

    try:
        wait_loader(page)
        print_log("\nWaiting for Search Grid")
        search_grid = page.wait_for_selector(
            "#ctl00_ContentPlaceHolder1_upSearch", timeout=30000
        )
    except Exception:
        search_grid = None

    if search_grid:
        page_current = 0
        try:
            lbl = page.wait_for_selector(
                "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_lblTotalPages",
                timeout=15000,
            )
            page_last = int(lbl.inner_text().strip().split()[1])
        except Exception:
            page_last = 1
        print_log("There are {} Total Search Pages...\n".format(page_last))

        while page_current != page_last:
            page.wait_for_selector(
                "#ctl00_ContentPlaceHolder1_upSearch", timeout=15000
            )
            try:
                curr = page.wait_for_selector(
                    "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_lblCurrentPage",
                    timeout=15000,
                )
                page_current = int(curr.inner_text())
            except Exception:
                page_current = 1

            print_log("-" * 80)
            print_log("Working on Page # {}".format(page_current))

            page.wait_for_selector(
                "input.viewButton[onclick^='javascript']", timeout=30000
            )
            button_count = page.locator(
                "input.viewButton[onclick^='javascript']"
            ).count()

            for x in range(1, button_count + 1):
                row_id = 2 + x
                id_str = f"0{row_id}" if row_id < 10 else str(row_id)
                pages.append("{}_{}".format(page_current, id_str))

            if page_current == page_last:
                break

            print_log("Click Next Page...")
            page.wait_for_selector(
                "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_btnNext",
                timeout=30000,
            ).click()
            wait_loader(page)
            page.wait_for_selector(
                "#ctl00_ContentPlaceHolder1_upSearch", timeout=30000
            )
            w = random.randint(1, 3)
            print_log("Waiting {} seconds for Search Grid...".format(w))
            time.sleep(w)

    return pages


def get_data(page, database, state_name):
    url = page.url
    move = False
    captcha = True

    try:
        while captcha:
            print_log("Starting capture")
            ms = random.randint(8, 15) * 1000
            em = page.wait_for_selector(
                '[name="ctl00$ContentPlaceHolder1$PublicNoticeDetailsBody1$btnViewNotice"]',
                timeout=ms,
            )
            captcha = bool(em)
            print_log("Button Exist = {}".format(captcha))

            recaptcha_elem = None
            try:
                recaptcha_elem = page.wait_for_selector("#recaptcha", timeout=ms)
            except PlaywrightTimeoutError:
                pass

            if recaptcha_elem:
                sitekey_clean = recaptcha_elem.get_attribute("data-sitekey")
                solver = recaptchaV2Proxyless()
                solver.set_key(os.environ.get("CAPTCHA_SOLVER_KEY"))
                solver.set_website_url(url)
                solver.set_website_key(sitekey_clean)
                g_response = solver.solve_and_return_solution()
                if dev:
                    if g_response != 0:
                        print_log("Captcha Solved >>>")
                    else:
                        print_log(
                            "Task finished with error: {}".format(solver.error_code),
                            True,
                        )

                w = random.randint(3, 5)
                print_log("Waiting {} seconds before solving...".format(w))
                page.evaluate(
                    'document.getElementById("g-recaptcha-response").style.display=""'
                )
                page.evaluate(
                    f'document.getElementById("g-recaptcha-response").innerHTML = "{g_response}"'
                )
                page.evaluate(
                    'document.getElementById("g-recaptcha-response").style.display="none"'
                )
                page.locator(
                    "#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_btnViewNotice"
                ).click()
            move = True
    except Exception:
        move = True

    web_scrape = {}
    if move:
        print_log("\nLoading Notice...")
        page.wait_for_selector("#content-sub", timeout=10000)

        page.wait_for_selector(
            "#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_PublicNoticeDetails1_lblPubName",
            timeout=30000,
        )
        publisher = page.locator(
            "#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_PublicNoticeDetails1_lblPubName"
        ).inner_text().strip()

        date_pub = page.locator(
            "#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_lblPublicationDAte"
        ).inner_text().strip()
        date_format = "%A, %B %d, %Y"
        sql_date_format = "%Y-%m-%d"
        date_object = datetime.strptime(date_pub, date_format).date()
        sql_date_string = date_object.strftime(sql_date_format)

        county_name = page.wait_for_selector(
            "#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_PublicNoticeDetails1_lblCounty",
            timeout=30000,
        ).inner_text().strip()

        page.wait_for_selector(
            "#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_pnlNoticeContent",
            timeout=30000,
        )
        notice = page.locator(
            "#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_lblContentText"
        ).inner_text().strip()
        api_data = notice

        try:
            print_log("Looking for PDF link")
            ms = random.randint(2, 3) * 1000
            pdf_tag = page.wait_for_selector(
                "#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_spanFileLink",
                timeout=ms,
            )
            if pdf_tag:
                pdf_url = pdf_tag.locator("a").get_attribute("href")
                print_log("PDF File: '{}'".format(pdf_url))
                api_data = pdf_url.strip()
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
                has_address = True
        except Exception:
            pass

        info = {
            "State": state_name,
            "Id": url.split("=")[-1],
            "Notice": notice.replace("'", ""),
            "Publisher": publisher,
            "Date_Published": sql_date_string,
            "county": county_name,
            "page_url": url,
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

        if has_address:
            try:
                table_name = "NcPub" if state_name == "NC" else "GaPub"
                database.pub_data(web_scrape, table_name)
            except Exception:
                print_log("Unable to save in database: {}".format(url), True)
        else:
            print_log("Address Information is missing")

    return page


def get_all_pages(page, pagers, database, state):
    print_log("Page Loaded...")
    select_site_filters(page)

    ddl = "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_ddlPerPage"
    page.wait_for_selector(ddl, state="visible", timeout=30000)
    options = page.eval_on_selector_all(
        f"{ddl} option", "opts => opts.map(o => o.value)"
    )
    num_str = options[-1]
    time.sleep(random.randint(1, 3))
    page.select_option(ddl, value=num_str)

    try:
        wait_loader(page)
        print_log("\nWaiting for Search Grid")
        search_grid = page.wait_for_selector(
            "#ctl00_ContentPlaceHolder1_upSearch", timeout=30000
        )
    except Exception:
        search_grid = None

    if search_grid:
        page_current = 0
        try:
            lbl = page.wait_for_selector(
                "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_lblTotalPages",
                timeout=15000,
            )
            page_last = int(lbl.inner_text().strip().split()[1])
        except Exception:
            page_last = 1
        print_log("There are {} Total Search Pages...\n".format(page_last))

        page_map = {}
        for p in pagers:
            p_num, p_id = p.split("_")
            if int(p_num) not in page_map:
                page_map[int(p_num)] = []
            page_map[int(p_num)].append(p_id)

        pages_to_do = list(page_map.keys())
        inc = 1

        while page_current != page_last:
            wait_loader(page)
            page_number = pages_to_do[0]
            page.wait_for_selector(
                "#ctl00_ContentPlaceHolder1_upSearch", timeout=30000
            )

            try:
                curr = page.wait_for_selector(
                    "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_lblCurrentPage",
                    timeout=15000,
                )
                page_current = int(curr.inner_text())
            except Exception:
                page_current = 1

            print_log("-" * 80)
            print_log("Working on Page # {}".format(page_current))

            if page_number == page_current:
                list_id = page_map[page_number]

                while list_id:
                    page_url = page.url
                    id_val = list_id[0]
                    msg = "Working on Notice # {}".format(inc)
                    print_log(msg + "-" * (60 - len(msg)))

                    try:
                        btn_sel = (
                            f"#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_"
                            f"GridView1_ctl{id_val}_btnView2"
                        )
                        button = page.wait_for_selector(
                            btn_sel, state="visible", timeout=30000
                        )
                        button.scroll_into_view_if_needed()
                        button.click()

                        try:
                            page = get_data(page, database, state)
                            list_id.remove(id_val)
                            inc += 1
                        except Exception:
                            print_log(
                                "Unable to Get Data: {}".format(page_url), True
                            )

                        w = random.randint(3, 5)
                        print_log("Waiting {} to click back...".format(w))
                        time.sleep(w)

                        back = page.wait_for_selector(
                            "#ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_hlBackFromBodyTop",
                            state="visible",
                            timeout=30000,
                        )
                        print_log("\nClicking Back")
                        ahref = back.get_attribute("href")
                        page.goto(ahref)

                        try:
                            page.wait_for_selector(
                                "#ctl00_ContentPlaceHolder1_upSearch", timeout=15000
                            )
                        except PlaywrightTimeoutError:
                            page.wait_for_selector("#capitol", timeout=30000)
                            print_log("\tSearching Again...")
                            select_filters_again(page)
                            page.wait_for_selector(
                                "#ctl00_ContentPlaceHolder1_upSearch", timeout=15000
                            )
                    except Exception:
                        pass

                pages_to_do.remove(page_number)

            if page_current == page_last:
                break

            if not pages_to_do:
                break

            print_log("Click Next Page...")
            page.wait_for_selector(
                "#ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_btnNext",
                timeout=30000,
            ).click()
            wait_loader(page)
            page.wait_for_selector(
                "#ctl00_ContentPlaceHolder1_upSearch", timeout=30000
            )
            w = random.randint(3, 5)
            print_log("Waiting {} seconds for Search Grid...".format(w))
            time.sleep(w)

    return page
