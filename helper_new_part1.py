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
import requests

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support import expected_conditions as EC

from anticaptchaofficial.recaptchav2proxyless import *

load_dotenv()
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

def init_driver(user_agent=None, headless=False):
    """
    Create and return a standard selenium webdriver.Chrome() instance.
    WSL-safe version using standard chromedriver.

    Returns: driver
    """
    global USER_AGENT

    if user_agent:
        USER_AGENT = user_agent
    else:
        USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36'

    options = Options()
    if not dev:
        options.add_argument("start-maximized")
    else:
        options.add_argument("--window-size=1300,1000")

    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--disable-notifications')
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=" + USER_AGENT)

    if headless or os.environ.get("HEADLESS") == "1":
        options.add_argument("--headless=new")

    service = Service(log_path=os.devnull)
    driver = webdriver.Chrome(options=options, service=service)

    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
    except Exception:
        pass

    if dev:
        try:
            driver.set_window_size(1300, 1000)
        except Exception:
            pass

    return driver

