# -*- coding: utf-8 -*-
"""
Simple utility to enrich exports/GaPub.csv and exports/NcPub.csv with computed columns.
Run from project root inside venv:
    venv\\Scripts\\python.exe enrich_pubs.py
"""
import os
import glob
import helper_consolidated as util

if __name__ == '__main__':
    exports_dir = os.path.join(os.getcwd(), 'exports')
    ga_files = glob.glob(os.path.join(exports_dir, 'GaPub*.csv'))
    nc_files = glob.glob(os.path.join(exports_dir, 'NcPub*.csv'))

    for f in ga_files + nc_files:
        try:
            print(f'Enriching {f}...')
            out = util.enrich_pubs_csv(f)
            print('Wrote:', out)
        except Exception as e:
            print('Failed to enrich', f, e)
