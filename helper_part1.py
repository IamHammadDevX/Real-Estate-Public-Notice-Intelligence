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
try:
    import undetected_chromedriver as uc
except Exception:
    uc = None  # fallback: undetected_chromedriver not available

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.chrome.options import Options
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

    if uc and getattr(uc, "IS_POSIX", False):
        filename = os.path.dirname(filename)
    if os.path.exists(filename):
        os.chmod(filename, permissions)

def init_driver(patcher=False):
    # If undetected_chromedriver is available, use it; otherwise fall back to Selenium
    if uc:
        patcher = uc.Patcher()
        # unlock chromdriver.exe and patch it
        if patcher:
            lock_file(patcher.executable_path, lock=False)
            patcher.auto()

        # lock chromedriver.exe & monkey patch Patcher
        # to prevent the patcher from reading or writing it
        lock_file(patcher.executable_path)
        uc.Patcher.is_binary_patched = lambda self: True

        driver_instance = uc.Chrome()
        if dev:
            driver_instance.set_window_size(1300, 1000)
        return driver_instance
    else:
        # fallback to selenium's Chrome if available
        try:
            options = Options()
            if not dev:
                options.add_argument("start-maximized")
            driver = webdriver.Chrome(options=options)
            if dev:
                driver.set_window_size(1300, 1000)
            return driver
        except Exception as e:
            raise RuntimeError("undetected_chromedriver not available and Selenium fallback failed: {}".format(e))

