# -*- coding: utf-8 -*-
"""
Created on Sun Sep 28 15:24:25 2025

@author: Asad Mehmood
"""

import os
import sys

if __name__ == "__main__":
    current_directory = os.getcwd()
    filename_bat = "api_call.bat"

    # scripts = ['gapubs.py', 'ncpubs.py']
    scripts = ['gapubs.py', 'ncpubs.py', 'propstreams_nc.py', 'propstreams_ga.py']
    file_items = list()
    for script_name in scripts:
        # script_name = "os.py"
        script_path = os.path.join(current_directory, script_name)
        python_exe = sys.executable
        paths = list()
        for path in [python_exe, script_path]:
            if len(path.split()) > 1:
                path = '"{}"'.format(path)
            paths.append(path)
        file_line = '{} {}'.format(*paths)
        file_items.append(file_line)

    items = ["@echo off"] + file_items +  ["pause"]
    bat_file_path = os.path.join(current_directory, filename_bat)
    with open(bat_file_path, "w") as f:
        content = "\n".join(items)
        f.write(content)
    print(content)
