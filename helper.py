# -*- coding: utf-8 -*-
"""
Created on Mon August 19, 2025 - 18:39:20

@author: Asad Mehmood
"""

import os
from dotenv import load_dotenv
import json
from openai import OpenAI
import random
import logging
import time
from datetime import datetime
import stat
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC

from anticaptchaofficial.recaptchav2proxyless import *

load_dotenv()
import tempfile
import shutil
dev = bool(os.environ.get("DEV_MODE"))
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36'

def print_log(text, error=False):
    if dev:
        print(text)
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

# def init_driver():
#     # driver_dir = os.path.join(os.getcwd(), 'drivers')
#     options = Options()
#     if not dev:
#         options.add_argument("start-maximized")
#     options.add_experimental_option("excludeSwitches", ["enable-automation"])
#     options.add_experimental_option('useAutomationExtension', False)
#     options.add_argument('--disable-notifications')
#     # options.add_argument("--headless")  # Run in headless mode if needed
#     options.add_argument("--no-sandbox")
#     options.add_argument("--disable-dev-shm-usage")
#     options.add_argument("--disable-gpu")

#     driver = webdriver.Chrome(options=options)
#     if dev:
#         driver.set_window_size(1300, 1000)
#     return driver

def lock_file(filename, lock=True):
    permissions = stat.S_IREAD
    if not lock:
        permissions += stat.S_IWRITE
    if os.path.exists(filename):
        os.chmod(filename, permissions)

def init_driver(patcher=False):
    # Create isolated temporary profile to avoid locked profiles or AV termination
    tmp_profile = os.path.join(tempfile.gettempdir(), f"chrome_tmp_{os.getpid()}")
    os.makedirs(tmp_profile, exist_ok=True)

    options = Options()
    if not dev:
        options.add_argument("start-maximized")
    options.add_argument(f"--user-data-dir={tmp_profile}")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")

    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--disable-notifications')
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"--user-agent={USER_AGENT}")

    service = Service(ChromeDriverManager().install())
    driver_instance = webdriver.Chrome(service=service, options=options)

    # attach tmp profile path for cleanup
    try:
        driver_instance._tmp_profile = tmp_profile
    except Exception:
        pass

    if dev:
        driver_instance.set_window_size(1300, 1000)
    return driver_instance

def call_chatgpt(text):
    prompt = """
    Extract the address information (Street, City, Zip_Code) from any foreclosure details provided or PDF Url. Output only a JSON object containing these fields. Do not include any additional text, notes, or formatting, as your response will be directly parsed by a script.

    - When a foreclosure listing or description is shared, carefully identify and extract:
    - Street: (full street address)
    - City: (name of the city)
    - Zip_Code: (5-digit postal code)

    - Output only the following JSON structure:

    {
    "Street": "[Extracted street address]",
    "City": "[Extracted city name]",
    "Zip_Code": "[Extracted zip code]"
    }

    - If any element cannot be confidently determined, leave its value an empty string ("").
    - If there are any shortcut words in "Street" like "Road", "Street", "Avenue", or "Drive" then correct

    - Produce only the JSONâ€”no markdown formatting, headers, code blocks, or explanatory text.

    Example Input:
    123 Main St, Springfield, IL 62704 â€“ This beautiful foreclosure is priced to sell!

    Example Output:
    {
    "Street": "123 Main St",
    "City": "Springfield",
    "Zip_Code": "62704"
    }

    (For real examples, the fields should be fully completed wherever information is available. Remember: output only valid JSON, and never prepend or append extra text.)

    Objective Reminder: Extract only Street, City, and Zip_Code from foreclosure text and output in exact plain JSONâ€”no extra text, markdown, code blocks, or comments.

    So, in the JSON format which I have discussed earlier, please add "owner_name" and put the owner names in it. If there are multiple names then seperate the name with ":::" seperator. If owner name is not present then make it null.

    Similarly, if City or Zip_Code are null then please find zip code and city for its address.

    Please add "parcel_number" and add or find Parcel Number of the address and return it along with the other information. In case, there is no parcel number then make it null. If Street or City or Zip_Code are null then please try figure them out with the help Parcel number.
    """

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    response = client.responses.create(
        model="gpt-4.1",
        instructions=prompt,
        input=text,
    )
    return response.output_text

def parse_notice(notice):
    arr_response = dict()
    try:
        print_log("Parsing Notice with ChatGPT...")
        result = call_chatgpt(notice)
        try:
            arr_response = json.loads(result)
        except json.JSONDecodeError:
            fix_notice = notice.replace("\"", '').strip()
            print_log("Parsing Notice again...")
            result_new = call_chatgpt(fix_notice)
            arr_response = json.loads(result_new)
        except Exception as e:
            error_str = "\n{}: {}".format(str(type(e).__name__), str(e))
            print_log(error_str, True)

        if bool(arr_response):
            arr_response.update({'Address': str(True)})
            if not all(bool(arr_response[key]) for key in ['Street', 'City']):
                arr_response = dict()

            if any(value is None for value in arr_response.values()):
                for key, value in arr_response.items():
                    if value is None:
                        arr_response[key] = ''
    except Exception as e:
        error_str = "\n{}: {}".format(str(type(e).__name__), str(e))
        print_log(error_str, True)

    return arr_response

def wait_loader(driver):
    loader_id = "ctl00_ContentPlaceHolder1_UpdateProgress1"
    waits = True
    print_log("Loading...")
    while waits:
        ww = random.randint(2, 5)
        waiters = WebDriverWait(driver, ww)
        try:
            waiters.until(EC.presence_of_element_located((By.XPATH, '//div[@id="{}" and @aria-hidden="false"]'.format(loader_id))))
        except:
            pass
        try:
            waiters.until(EC.presence_of_element_located((By.XPATH, '//div[@id="{}" and @aria-hidden="true"]'.format(loader_id))))
            waits = False
        except:
            waits = True

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
        info = dict(Data_Source=source, Run_Time=date_now,Next_Starts=str(r_starts),Next_Finish=str(r_finish))
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

def select_site_filters(driver):
    # wait_loader(driver)

    filter_county = False

    keyword_field = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_as1_txtSearch")))
    keyword_field.clear()
    keyword_field.send_keys('fore')
    w = random.randint(2, 5)
    time.sleep(w)
    # keyword_field = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_as1_txtSearch")))
    tt = 'closure' if filter_county else 'closure\n'
    keyword_field.send_keys(tt)

    if filter_county:
        county_holder = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_as1_divCounty")))
        time.sleep(1)
        county_holder.find_element(By.TAG_NAME, "label").find_element(By.TAG_NAME, "a").click()
        w = random.randint(2, 5)
        time.sleep(w)

        ul_tag = county_holder.find_element(By.ID, "ctl00_ContentPlaceHolder1_as1_lstCounty")
        li_tags = ul_tag.find_elements(By.TAG_NAME, 'li')
        for li in li_tags:
            li_label = li.find_element(By.TAG_NAME, 'label')
            li_text = li_label.text.strip()
            if li_text == 'Douglas':
                driver.execute_script("arguments[0].scrollIntoView();", li_label)
                w = random.randint(2, 3)
                time.sleep(w)
                li_label.click()
                break

        # ctl00_ContentPlaceHolder1_as1_btnGo
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_as1_btnGo"))).click()

    wait_loader(driver)

def select_filters_again(driver_inst):
    select_site_filters(driver_inst)

    select_tag = WebDriverWait(driver_inst, 30).until(EC.element_to_be_clickable((By.ID, "ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_ddlPerPage")))
    select_PerPage = Select(select_tag)

    options = select_tag.find_elements(By.TAG_NAME,"option")
    all_options = [opt.get_property("value") for opt in options]
    num_str = all_options[-1]
    w = random.randint(1, 3)
    time.sleep(w)
    select_PerPage.select_by_value(num_str)

def evaluate_pages_to_work(driver):
    pages = list()
    print_log("Page Loaded...")

    select_site_filters(driver)

    select_tag = WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.ID, "ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_ddlPerPage")))
    select_PerPage = Select(select_tag)

    options = select_tag.find_elements(By.TAG_NAME,"option")
    all_options = [opt.get_property("value") for opt in options]
    num_str = all_options[-1]
    w = random.randint(1, 3)
    time.sleep(w)
    select_PerPage.select_by_value(num_str)

    try:
        wait_loader(driver)
        print_log("\nWaiting for Search Grid")
        search_grid = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_upSearch")))
    except:
        search_grid = None

    if bool(search_grid):
        page_current = 0
        try:
            curr_tot_tag = WebDriverWait(search_grid, 15).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_lblTotalPages")))
            current_total_str = curr_tot_tag.text.strip()
            page_last = int(current_total_str.split()[1])
        except:
            page_last = 1
        print_log("There are {} Total Search Pages...\n".format(page_last))

        while not page_current == page_last:
            # wait_loader(driver)
            search_grid = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_upSearch")))

            try:
                curr_tag = WebDriverWait(search_grid, 15).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_lblCurrentPage")))
                page_current = int(curr_tag.text)
            except:
                page_current = 1
            print_log("-" * 80)
            print_log("Working on Page # {}".format(page_current))

            WebDriverWait(search_grid, 30).until(EC.presence_of_element_located((By.XPATH, "//input[@class='viewButton' and starts-with(@onclick, 'javascript')]")))
            button_list = search_grid.find_elements(By.XPATH,"//input[@class='viewButton' and starts-with(@onclick, 'javascript')]")

            for x in range(1, len(button_list) + 1):
                id = 2 + x
                if id < 10:
                    id = f'0{id}'

                ad_ref = "{}_{}".format(page_current, id)
                pages.append(ad_ref)

            if page_current == page_last:
                break

            print_log("Click Next Page...")
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_btnNext"))).click()
            wait_loader(driver)
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_upSearch")))

            w = random.randint(1, 3)
            print_log("Waiting {} seconds for Search Grid...".format(w))
            time.sleep(w)
    return pages

def get_data(driver, database, state_name):
    url = driver.current_url
    web_data = dict()
    move = False
    captcha = True

    try:
        while captcha:
            print_log("Starting capture")
            w = random.randint(8, 15)
            em = WebDriverWait(driver, w).until(EC.presence_of_element_located((By.NAME, "ctl00$ContentPlaceHolder1$PublicNoticeDetailsBody1$btnViewNotice")))
            captcha = bool(em)
            print_log("Button Exist = {}".format(captcha))
            # Resolving recapture
            recaptcha_elem = WebDriverWait(driver, w).until(EC.presence_of_element_located((By.ID, "recaptcha")))
            if bool(recaptcha_elem):
                # recaptcha_elem = driver.find_element(By.ID, "recaptcha")
                sitekey_clean = recaptcha_elem.get_attribute("data-sitekey")

                solver = recaptchaV2Proxyless()
                # solver.set_verbose(1)
                solver.set_key(os.environ.get("CAPTCHA_SOLVER_KEY"))
                solver.set_website_url(url)
                solver.set_website_key(sitekey_clean)
                g_response = solver.solve_and_return_solution()
                if dev:
                    if g_response != 0:
                        print_log("Captcha Solved >>>")
                    else:
                        print_log("Task finished with error: {}".format(solver.error_code), True)

                w = random.randint(3, 5)
                print_log("Waiting {} seconds before solving...".format(w))

                driver.execute_script('var element=document.getElementById("g-recaptcha-response"); element.style.display="";')
                driver.execute_script('document.getElementById("g-recaptcha-response").innerHTML = arguments[0]', g_response)
                driver.execute_script('var element=document.getElementById("g-recaptcha-response"); element.style.display="none";')

                driver.find_element(By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_btnViewNotice"]').click()
            move = True
    except:
        move = True

    web_scrape = dict()
    if move:
        print_log("\nLoading Notice...")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "content-sub")))

        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_PublicNoticeDetails1_lblPubName")))
        pub_tag = driver.find_element(By.ID,"ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_PublicNoticeDetails1_lblPubName")
        publisher = pub_tag.text.strip()

        date_pub = driver.find_element(By.ID,"ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_lblPublicationDAte")
        date_pub = date_pub.text.strip()
        date_format = "%A, %B %d, %Y"
        sql_date_format = "%Y-%m-%d"

        date_object = datetime.strptime(date_pub, date_format).date()
        sql_date_string = date_object.strftime(sql_date_format)

        county_tag = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_PublicNoticeDetails1_lblCounty")))
        county_name = county_tag.text.strip()

        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_pnlNoticeContent")))
        pub_notice_tag = driver.find_element(By.ID,"ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_pnlNoticeContent")
        text_tag = pub_notice_tag.find_element(By.ID,"ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_lblContentText")
        notice = text_tag.text.strip()
        web_data['Notice'] = notice
        api_data = notice.strip()

        try:
            print_log("Looking for PDF link")
            tim = random.randint(2, 3)
            pdf_file_tag = WebDriverWait(driver, tim).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_spanFileLink")))
            has_pdf = bool(pdf_file_tag)
            if has_pdf:
                a_tag = pdf_file_tag.find_element(By.TAG_NAME, 'a')
                pdf_url = a_tag.get_attribute('href')
                print_log("PDF File: '{}'".format(pdf_url))
                api_data = pdf_url.strip()
        except:
            print_log("No PDF File")

        web_scrape = {
            'Street': '',
            'City': '',
            'Zip_Code': '',
            'owner_name': '',
            'parcel_number': '',
            'Address': str(False)
        }
        has_address = False
        try:
            api_result = parse_notice(api_data)
            if bool(api_result):
                web_scrape.update(api_result)
                has_address = True
        except:
            pass

        info = {
            'State': state_name,
            'Id': url.split('=')[-1],
            'Notice': notice.replace('\'', ''),
            'Publisher': publisher,
            'Date_Published': sql_date_string,
            'county': county_name,
            'page_url': url
        }

        web_scrape.update(info)
        if dev:
            print_log("-" * 20)
            for k, val in web_scrape.copy().items():
                if k == 'Notice':
                    continue
                if isinstance(val, str):
                    web_scrape[k] = val.strip()
                    print_log("'{}': '{}'".format(k, val.strip()))
                else:
                    print_log("'{}': {}".format(k, val))

        if has_address:
            try:
                table_name = "GaPub"
                if state_name == 'NC':
                    table_name = "NcPub"
                database.pub_data(web_scrape, table_name)
            except:
                print_log("Unable to save in database: {}".format(url), True)
        else:
            print_log("Address Information is missing")
    return driver

def get_all_pages(driver, pagers, database, state):
    print_log("Page Loaded...")

    select_site_filters(driver)

    select_tag = WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.ID, "ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_ddlPerPage")))
    select_PerPage = Select(select_tag)

    options = select_tag.find_elements(By.TAG_NAME,"option")
    all_options = [opt.get_property("value") for opt in options]
    num_str = all_options[-1]
    w = random.randint(1, 3)
    time.sleep(w)
    select_PerPage.select_by_value(num_str)

    try:
        wait_loader(driver)
        print_log("\nWaiting for Search Grid")
        search_grid = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_upSearch")))
    except:
        search_grid = None

    if bool(search_grid):
        page_current = 0

        try:
            curr_tot_tag = WebDriverWait(search_grid, 15).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_lblTotalPages")))
            current_total_str = curr_tot_tag.text.strip()
            page_last = int(current_total_str.split()[1])
        except:
            page_last = 1
        print_log("There are {} Total Search Pages...\n".format(page_last))

        page_map = dict()
        for p in pagers:
            p_num, p_id = p.split("_")
            if int(p_num) not in page_map.keys():
                page_map[int(p_num)] = list()
            page_map[int(p_num)].append(p_id)

        pages = list(page_map.keys())
        inc = 1
        while not page_current == page_last:
            wait_loader(driver)
            page_number = pages[0]
            search_grid = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_upSearch")))

            try:
                curr_tag = WebDriverWait(search_grid, 15).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_lblCurrentPage")))
                page_current = int(curr_tag.text)
            except:
                page_current = 1

            print_log("-" * 80)
            print_log("Working on Page # {}".format(page_current))
            if page_number == page_current:
                list_id = page_map[page_number]

                while bool(list_id):
                    page_url = driver.current_url
                    id = list_id[0]

                    msg = "Working on Notice # {}".format(inc)
                    print_log(msg + "-" * (60 - len(msg)))
                    try:
                        button = WebDriverWait(driver, 30).until(EC.element_to_be_clickable(
                                (By.XPATH,f'//*[@id="ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl{id}_btnView2"]')
                            )
                        )
                        driver.execute_script("arguments[0].scrollIntoView();", button)
                        button.click()

                        try:
                            driver = get_data(driver, database, state)
                            list_id.remove(id)
                            inc += 1
                        except:
                            print_log("Unable to Get Data: {}".format(page_url), True)

                        w = random.randint(3, 5)
                        print_log("Waiting {} to click back...".format(w))
                        time.sleep(w)

                        back = WebDriverWait(driver, 30).until(
                            EC.element_to_be_clickable((By.ID, 'ctl00_ContentPlaceHolder1_PublicNoticeDetailsBody1_hlBackFromBodyTop'),)
                        )
                        print_log("\nClicking Back")
                        ahref = back.get_attribute('href')
                        driver.get(ahref)
                        # back.click()
                        try:
                            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_upSearch")))
                        except:
                            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "capitol")))
                            print_log("\tSearching Again...")
                            select_filters_again(driver)
                            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_upSearch")))
                    except:
                        pass

                pages.remove(page_number)

            if page_current == page_last:
                break

            if not bool(pages):
                break

            print_log("Click Next Page...")
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1_ctl01_btnNext"))).click()
            wait_loader(driver)
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_upSearch")))

            w = random.randint(3, 5)
            print_log("Waiting {} seconds for Search Grid...".format(w))
            time.sleep(w)
    return driver

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

def wait_loader_truthfinder(a_driver):
    try:
        WebDriverWait(a_driver, 15).until(EC.presence_of_element_located((By.XPATH, "//div[contains(@class, '_loader')]")))
        print_log("Loading...")
    except:
        pass

    i = random.randint(2, 3)
    time.sleep(i)

    try:
        WebDriverWait(a_driver, 15).until_not(EC.presence_of_element_located((By.XPATH, "//div[contains(@class, '_loader')]")))
        print_log("LoadeD!")
    except:
        pass

def make_address_db(array):
    return '{Street}, {City}, {State} {Zip_Code}'.format_map(array)

def get_truthfinder_data(browser, db_info, database, table_name):
    address_db = make_address_db(db_info)
    try:
        print_log("Fetching data from Truthfinder...")
        name_words = db_info['owner_name']
        print_log("Searching for address: '{}'".format(address_db))
        try:
            street, city, rem = [a.strip() for a in address_db.split(',')]
            state, zip_code = rem.split()
        except Exception as e:
            error_str = "{}: {}".format(str(type(e).__name__), str(e))
            print_log(error_str, True)
            print_log("Unable to split address: '{}'".format(address_db), True)

        try:
            search_tag = WebDriverWait(browser, 30).until(EC.visibility_of_element_located((By.XPATH, "//div[contains(@class, '_fauxSearchInput')]")))
            i = random.randint(2, 3)
            print_log("clicking Search in {} seconds...".format(i))
            time.sleep(i)
            search_tag.click()

            ul_tag = WebDriverWait(browser, 30).until(EC.visibility_of_element_located((By.XPATH, "//ul[contains(@class, '_searchIcons')]")))
            li_tags = ul_tag.find_elements(By.TAG_NAME, 'li')
            last_tag = li_tags[-1]
            i = random.randint(1, 2)
            time.sleep(i)
            last_tag.click()

            form_tag = WebDriverWait(browser, 30).until(EC.visibility_of_element_located((By.XPATH, "//form[contains(@class, '_desktopSearchTabsHeader')]")))
            input_street = form_tag.find_element(By.NAME, 'street')
            time.sleep(1)
            input_street.send_keys(street)

            input_city = form_tag.find_element(By.NAME, 'city')
            time.sleep(1)
            input_city.send_keys(city)

            input_zip = form_tag.find_element(By.NAME, 'zip')
            time.sleep(1)
            input_zip.send_keys(zip_code)

            state_tag = form_tag.find_element(By.NAME, 'state')
            select_PerPage = Select(state_tag)
            time.sleep(1)
            select_PerPage.select_by_value(state)

            btn_submit = form_tag.find_element(By.TAG_NAME, 'button')
            time.sleep(1)
            btn_submit.click()
        except Exception as e:
            error_str = "{}: {}".format(str(type(e).__name__), str(e))
            print_log(error_str, True)
            print_log("Unable to Search address: '{}'".format(address_db), True)

        try:
            n = 60 * 5
            the_waiter = WebDriverWait(browser, n)
            print_log("Getting address details")

            wait_loader_truthfinder(browser)

            io = random.randint(2, 5)
            print_log("Waiting {} seconds...".format(io))
            time.sleep(io)

            try:
                view_report = the_waiter.until(EC.visibility_of_element_located((By.XPATH, "//a[contains(@class, '_reportLink')]")))
                time.sleep(1)
                view_report.click()

                wait_loader_truthfinder(browser)

                view_detail = the_waiter.until(EC.visibility_of_element_located((By.XPATH, "//button[contains(@class, 'viewDetailedReportBtn')]")))
                time.sleep(1)
                view_detail.click()
            except:
                browser.refresh()

            navs = WebDriverWait(browser, 30).until(EC.visibility_of_element_located((By.XPATH, "//div[contains(@class, '_scrollContainer')]")))
            resident_tag = navs.find_element(By.CLASS_NAME, 'residents')
            time.sleep(1)
            resident_tag.click()

            resident_tag = WebDriverWait(browser, 30).until(EC.visibility_of_element_located((By.ID, "residents")))
            name_content = WebDriverWait(resident_tag, 30).until(EC.visibility_of_element_located((By.XPATH, "//div[contains(@class, '_recordSubsectionCardContainer')]")))
            nametag_list = name_content.find_elements(By.XPATH, "//div[contains(@class, '_residentsSubsectionItem')]")

            profile_data = list()
            for name_tag in nametag_list:
                try:
                    h3_tag = name_tag.find_element(By.TAG_NAME, 'h3')
                    name_str = h3_tag.text.strip()
                    profile = {'name': name_str, 'is_match': 'False'}
                    try:
                        name_raw = [n.strip() for n in name_str.split(',')]
                        name, age_value = name_raw
                        age = int(age_value.split()[0])
                        profile['name'] = name
                        profile['age'] = age
                    except:
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
                    a_tag = name_tag.find_element(By.TAG_NAME, 'a')
                    profile_link = a_tag.get_attribute('href')

                    profile['link'] = profile_link
                    profile['address_db'] = address_db
                    profile_data.append(profile)
                except Exception as e:
                    error_str = "{}: {}".format(str(type(e).__name__), str(e))
                    print_log("Unable to read profile name of an address: '{}'".format(address_db), True)

            print_log("Parsing {:,} profiles...".format(len(profile_data)))
            for profile in profile_data:
                try:
                    prof_link = profile['link']
                    prof_name = profile['name']
                    print_log("\tWorking on Profile: '{}'".format(prof_name))
                    try:
                        browser.get(prof_link)
                        the_waiter = WebDriverWait(browser, n)
                        wait_loader_truthfinder(browser)

                        view_prof = the_waiter.until(EC.visibility_of_element_located((By.XPATH, "//button[contains(@class, 'viewDetailedReportBtn')]")))
                        print_log("\tProfile Loaded: '{}'".format(prof_name))
                        view_prof.click()

                        navs = WebDriverWait(browser, 30).until(EC.visibility_of_element_located((By.XPATH, "//div[contains(@class, '_scrollContainer')]")))
                        contact_tag = navs.find_element(By.CLASS_NAME, 'contact')
                        contact_tag.click()

                        contact_div = WebDriverWait(browser, 30).until(EC.visibility_of_element_located((By.ID, "contact")))
                        h_tags = contact_div.find_elements(By.TAG_NAME, 'h2')
                    except Exception as e:
                        error_str = "{}: {}".format(str(type(e).__name__), str(e))
                        print_log("Unable to load profile '{}': '{}'".format(prof_name, prof_link), True)
                        print_log(error_str, True)
                        continue

                    phones = list()
                    emails = list()
                    for h2_tag in h_tags:
                        head_name = h2_tag.text.strip().lower()
                        class_name = '_phonesSubsectionItem' if head_name == 'phone numbers' else '_emailsSubsectionItem'
                        div_contact = h2_tag.find_element(By.XPATH, "following-sibling::*[1]")
                        infos = div_contact.find_elements(By.XPATH, "//div[contains(@class, '{}')]".format(class_name))
                        for info in infos:
                            m_tag = info.find_element(By.TAG_NAME, 'p')
                            if head_name == 'phone numbers':
                                info_div = m_tag.find_element(By.XPATH, "following-sibling::*[1]")
                                phone = info_div.text.strip()
                                phones.append(phone)
                            else:
                                email = m_tag.text.strip()
                                emails.append(email)

                    profile['phone'] = ",".join(phones) if bool(phones) else ''
                    profile['email'] = ",".join(emails) if bool(emails) else ''
                except Exception as e:
                    error_str = "{}: {}".format(str(type(e).__name__), str(e))
                    print_log("Unable to parse emails and phones", True)
                    print_log(error_str, True)

                io = random.randint(2, 5)
                print_log("\tWaiting {} seconds...".format(io))
                time.sleep(io)

            if bool(profile_data):
                try:
                    database.truthfinder(table_name, profile_data)
                except Exception as e:
                    error_str = "{}: {}".format(str(type(e).__name__), str(e))
                    print_log(error_str, True)
                    print_log("Unable to save Truthfinder data in database: '{}'".format(address_db), True)

        except Exception as e:
            error_str = "{}: {}".format(str(type(e).__name__), str(e))
            print_log(error_str, True)
            print_log("Unable to work for Truthfinder: '{}'".format(address_db), True)

    except Exception as e:
        error_str = "{}: {}".format(str(type(e).__name__), str(e))
        print_log(error_str, True)
        print_log("Cannot Parse Address: '{}'".format(address_db), True)
    return browser

def click_mail_to_verify(browser):
    WebDriverWait(browser, 30).until(
        EC.element_to_be_clickable(
            (By.ID, 'messagelist'),
        )
    )

    i = random.randint(10, 15)
    print_log("Waiting {} seconds before refresh".format(i))
    time.sleep(i)

    nn = 60 * 5
    waiters = WebDriverWait(browser, nn)
    waiters.until(EC.visibility_of_element_located((By.ID, "rcmbtn115")))
    for i in range(10):
        waiters.until(EC.visibility_of_element_located((By.ID, "rcmbtn115"))).click()
        time.sleep(1)

    WebDriverWait(browser, 30).until(
        EC.element_to_be_clickable(
            (By.ID, 'messagelist'),
        )
    )

    msg = waiters.until(EC.visibility_of_element_located((By.XPATH, '//*[@id]/td[2]/span[4]/a/span')))
    i = random.randint(1, 2)
    time.sleep(i)
    msg.click()

    browser.switch_to.frame("messagecontframe")

    verify_account = waiters.until(EC.visibility_of_element_located((By.XPATH, '//*[@id="message-htmlpart1"]/div/center/div/table/tbody/tr[2]/td/table/tbody/tr/td/table/tbody/tr/td[2]/a')))
    i = random.randint(1, 2)
    time.sleep(i)
    verify_account.click()

    browser.switch_to.default_content()

    i = random.randint(1, 2)
    time.sleep(i)

    switch_tabs_webmail(browser, 2)
    try:
        iii = WebDriverWait(browser, 60).until(EC.presence_of_element_located((By.ID, 'verification-token')))
        h3_tag = WebDriverWait(iii, nn).until(EC.presence_of_element_located((By.TAG_NAME, 'h3')))
        complete_str = h3_tag.text.strip()
        print_log(complete_str)
    except Exception as e:
        browser.close()
        time.sleep(1)
        switch_tabs_webmail(browser, 1)
        error_str = "{}: {}".format(str(type(e).__name__), str(e))
        print_log(error_str, True)
        print_log("Click mail to verify has issue", True)
        complete_str = click_mail_to_verify(browser)
    return complete_str

def switch_tabs_webmail(driver, no):
    driver.switch_to.window(driver.window_handles[no])

def login_to_email(browser, email, password):
    # By passing Your connection is not private
    try:
        WebDriverWait(browser, 30).until(
            EC.element_to_be_clickable(
                (By.ID, 'details-button'),
            )
        )

        advanced_btn = browser.find_element(By.ID, 'details-button')
        advanced_btn.click()

        proceed_link = browser.find_element(By.ID, 'proceed-link')
        proceed_link.click()
    except Exception as e:
        error_str = "{}: {}".format(str(type(e).__name__), str(e))
        print_log(error_str, True)
        print_log("Login to Email for verification: All clear", True)

    WebDriverWait(browser, 10).until(
        EC.element_to_be_clickable(
            (By.ID, 'user'),
        )
    )

    email_input = browser.find_element(By.ID, 'user')
    i = random.randint(1, 2)
    time.sleep(i)
    email_input.send_keys(email)

    pswd_input = browser.find_element(By.ID, 'pass')
    i = random.randint(1, 2)
    time.sleep(i)
    pswd_input.send_keys(password)

    login_btn = browser.find_element(By.ID, 'login_submit')
    i = random.randint(1, 2)
    time.sleep(i)
    login_btn.click()

def login_truthfinder(browser):
    logged_in = True
    website = 'https://www.truthfinder.com/'
    truth_email = os.environ.get("TRUTHFINDER_EMAIL")
    truth_pwd = os.environ.get("TRUTHFINDER_PASSWORD")
    try:
        browser.get(website)
        browser.maximize_window()
        print_log("Page Loaded...")

        policy_cotent = WebDriverWait(browser, 30).until(EC.presence_of_element_located((By.ID, 'warning-modal')))
        btn_agree = policy_cotent.find_element(By.TAG_NAME, 'button')
        print_log("Clicking Agree")
        time.sleep(1)
        btn_agree.click()

        login_tag = WebDriverWait(browser, 30).until(EC.presence_of_element_located((By.ID, 'header-login')))
        print_log("Clicking login link")
        time.sleep(1)
        login_tag.click()

        email_input = WebDriverWait(browser, 30).until(EC.presence_of_element_located((By.XPATH, '//*[@id="login"]/div/div[2]/form/div[1]/input')))
        # email_input = browser.find_element(By.XPATH,'//*[@id="login"]/div/div[2]/form/div[1]/input')
        time.sleep(1)
        email_input.send_keys(truth_email)

        password_input = WebDriverWait(browser, 30).until(EC.presence_of_element_located((By.XPATH, '//*[@id="login"]/div/div[2]/form/div[2]/input')))
        # password_input = browser.find_element(By.XPATH, '//*[@id="login"]/div/div[2]/form/div[2]/input')
        time.sleep(1)
        password_input.send_keys(truth_pwd)

        login_btn = WebDriverWait(browser, 30).until(EC.presence_of_element_located((By.XPATH, '//*[@id="login"]/div/div[2]/form/div[3]/button')))
        time.sleep(1)
        login_btn.click()

        WebDriverWait(browser, 60).until(
            EC.element_to_be_clickable(
                (By.XPATH, '//*[@id="verification"]/div/div[2]/button'),  # Element filtration
            )
        )
        verification_btn = browser.find_element(By.XPATH, '//*[@id="verification"]/div/div[2]/button')
        time.sleep(1)
        verification_btn.click()

        i = random.randint(3, 5)
        print_log("Waiting {} seconds...".format(i))
        time.sleep(i)

        browser.execute_script("window.open('http://client1.jewelercart.com:2096/');")
        i = random.randint(3, 5)
        print_log("Waiting {} seconds to switch window".format(i))
        time.sleep(i)
        switch_tabs_webmail(browser, 1)

        web_email = os.environ.get("WEB_EMAIL")
        web_password = os.environ.get("WEB_PASSWORD")
        login_to_email(browser, web_email, web_password)
        try:
            verify = click_mail_to_verify(browser)
            if verify.lower() == "verification complete":
                print_log("Logging in successfully ...")
            else:
                print_log("Unable to login")
                logged_in = False
        except Exception as e:
            error_str = "{}: {}".format(str(type(e).__name__), str(e))
            print_log(error_str, True)
            print_log("Error: Unable to login: click_mail_to_verify()", True)

        switch_tabs_webmail(browser, 2)
        i = random.randint(2, 3)
        time.sleep(i)
        browser.close()

        switch_tabs_webmail(browser, 1)
        i = random.randint(2, 3)
        time.sleep(i)
        browser.close()

        time.sleep(i)
        switch_tabs_webmail(browser, 0)
    except Exception as e:
        error_str = "{}: {}".format(str(type(e).__name__), str(e))
        print_log(error_str, True)
        logged_in = False
        print_log("There was an issue: Login to truth finder", True)
    return logged_in

def login_propstream(driver):
    request_session = requests.Session()
    logged_in = True
    website = 'https://login.propstream.com/'
    propstream_email = os.environ.get("PROPSTREAM_EMAIL")
    propstream_pwd = os.environ.get("PROPSTREAM_PASSWORD")
    try:
        driver.get(website)
        WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.ID, "form-content")))
        print_log("Login Page loaded")

        # id = form-content
        # Explicit Wait until username is visible
        email_input = WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.XPATH, "//input[@name='username']")))
        print_log("Web")
        email_input.clear()
        time.sleep(1)
        print_log("Email:")
        email_input.send_keys(propstream_email)

        # Explicit Wait until password input is visible
        password_input = WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.XPATH, "//input[@name='password']")))
        time.sleep(1)
        print_log("Password:")
        password_input.send_keys(propstream_pwd)

        try:
            cookie_div = WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.CLASS_NAME, 'ot-sdk-container')))
            print_log("Cookies Popped up")
            accept_btn = WebDriverWait(cookie_div, 60).until(EC.presence_of_element_located((By.ID, 'onetrust-accept-btn-handler')))
            time.sleep(1)
            print_log("Accept All Cookies")
            accept_btn.click()
        except Exception as e:
            error_str = "{}: {}".format(str(type(e).__name__), str(e))
            print_log(error_str)
            print_log("Cannot Load cookies")

        login_btn = WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.XPATH, '//*[@id="form-content"]/form/button')))
        # login_btn = driver.find_element(By.XPATH, '//*[@id="form-content"]/form/button')
        time.sleep(1)
        print_log("Submit")
        login_btn.click()
        driver.maximize_window()

        # Wait until the element is visible
        n = 60 * 10
        WebDriverWait(driver, n).until(EC.visibility_of_element_located((By.CLASS_NAME, 'src-app-Search-Header-style__OvptX__appHeader')))
        # Get the cookies
        cookies = driver.get_cookies()

        # Print the cookies
        for cookie in cookies:
            request_session.cookies.set(cookie['name'], cookie['value'])

        print_log("Logging in successfully ...")
    except Exception as e:
        error_str = "{}: {}".format(str(type(e).__name__), str(e))
        print_log(error_str, True)
        logged_in = False
        print_log("Unable to Login...", True)

    return logged_in, request_session

def request_function(url, headers, payload, a_session):
    r = dict()
    try:
        response = a_session.get(url, headers=headers, data=payload)
        if response.status_code == 200:
            r = response.json()
    except Exception as e:
        error_str = "{}: {}".format(str(type(e).__name__), str(e))
        print_log(error_str, True)
    return r

def propstream_information(db_info, propstream_session):
    address = make_address_db(db_info)
    url = f"https://app.propstream.com/eqbackend/resource/auth/ps4/property/suggestionsnew?q={address}"

    payload = {}
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
    try:
        array = request_function(url, headers, payload, propstream_session)
    except Exception as e:
        array = dict()
        error_str = "{}: {}".format(str(type(e).__name__), str(e))
        print_log("Cannot request Data from request_function", True)
        print_log(error_str, True)
    arr_data = array.pop() if bool(array) else dict()
    ID = arr_data['id'] if 'id' in arr_data.keys() else list()
    return ID

def get_propstream_address_details(id, propstream_session):
    url = f"https://app.propstream.com/eqbackend/resource/auth/ps4/property/{id}?m=F"

    payload = {}
    headers = {
        'authority': 'app.propstream.com',
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'referer': 'https://app.propstream.com/search/1743767474',
        'sec-ch-ua': '"Not/A)Brand";v="99", "Google Chrome";v="115", "Chromium";v="115"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': USER_AGENT,
    }

    r = request_function(url, headers, payload, propstream_session)
    if r:
        scrapped_data = {
            'beds': r['ownerProperty'].get('bedrooms', ''),
            'baths': r['ownerProperty'].get('bathrooms', ''),
            'sqFt': r['ownerProperty'].get('squareFeet', ''),
            'lot_size': r['ownerProperty'].get('lot_size', ''),
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
            'county': r['address'].get('countyName', ''),
            'estimated_value': r['ownerProperty'].get('estimatedValue', ''),
            'last_year': r['estimatedValueGraph']['series'][0]['points'][0].get('value', '') if 'estimatedValueGraph' in r.keys() else 0,
            'properties': r.get('propertiesOwned', ''),
            'avg_sale_price': r.get('compSaleAmount', ''),
            'days_on_market': r.get('compDaysOnMarket', ''),
            'open_mortgages': r['ownerProperty'].get('openLiens', ''),
            'est_mortgage_balance': r['ownerProperty'].get('openMortgageBalance', ''),
            'public_record': r['ownerProperty'].get('lastSaleAmount', ''),
            'est_equity': r['ownerProperty'].get('estimatedEquity', ''),
            'monthly_rent': r.get('rentAmount', ''),
            'gross_yield': r.get('grossYield', ''),
            'owner_name': r.get('owner1FullName', ''),
        }
        return scrapped_data

def get_propstream_data(database, request_session, db_info, table_name):
    propstream_data = dict()
    row_index = db_info['Table_Index']
    prop_details = {
        'ga_id': db_info['Id'],
        'address_db': make_address_db(db_info)
    }

    try:
        print_log("Getting Propstream information...")
        property_info = propstream_information(db_info, request_session)
    except Exception as e:
        error_str = "{}: {}".format(str(type(e).__name__), str(e))
        property_info = list()
        print_log(error_str, True)
        print_log("Unable to fetch Propstream information: '{}'".format(row_index), True)

    if property_info:
        print_log("Getting Propstream Address Detail...")
        try:
            propstream_data = get_propstream_address_details(property_info, request_session)
            propstream_data['url'] = "https://app.propstream.com/search/{}".format(property_info)
            prop_details.update(propstream_data)
        except Exception as e:
            error_str = "{}: {}".format(str(type(e).__name__), str(e))
            print_log(error_str, True)
            print_log("Unable to get Propstream address details: '{}'".format(row_index), True)

    try:
        database.propstreams(table_name, prop_details)
    except Exception as e:
        error_str = "{}: {}".format(str(type(e).__name__), str(e))
        print_log(error_str, True)
        print_log("Unable to save Propstreams data in database: '{}'".format(row_index), True)
    return propstream_data

