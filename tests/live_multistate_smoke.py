"""Manual live smoke: real source/CAPTCHA/OpenAI, memory-only storage."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import multistate_scraper as scraper
from state_config import ALL_STATE_CODES, get_state_config


class MemoryDb:
    def __init__(self):
        self.checkpoint = None
        self.queue = {}
        self.rows = {}

    def get_scrape_checkpoint(self, state):
        return self.checkpoint

    def save_scrape_checkpoint(
        self, state, adapter, cursor, discovery_complete=False, total_discovered=0
    ):
        self.checkpoint = {
            "cursor": cursor,
            "Discovery_Complete": discovery_complete,
            "Total_Discovered": total_discovered,
        }

    def enqueue_notice(self, state, notice_id, source_url, payload=None):
        key = str(notice_id)
        if key in self.queue:
            return 0
        self.queue[key] = {
            "Notice_Id": key,
            "Source_Url": source_url,
            "Payload": payload,
            "Status": "pending",
            "Attempts": 0,
        }
        return 1

    def reset_processing_notices(self, state):
        for task in self.queue.values():
            if task["Status"] == "processing":
                task["Status"] = "failed"
        return 0

    def pending_notices(self, state, limit=None):
        rows = [
            task
            for task in self.queue.values()
            if task["Status"] in ("pending", "failed")
        ]
        return rows[:limit] if limit else rows

    def mark_notice_processing(self, state, notice_id):
        self.queue[str(notice_id)]["Status"] = "processing"

    def mark_notice_complete(self, state, notice_id):
        self.queue[str(notice_id)]["Status"] = "complete"

    def mark_notice_failed(self, state, notice_id, error):
        self.queue[str(notice_id)]["Status"] = "failed"

    def get_pub_record(self, table, notice_id):
        return self.rows.get(str(notice_id))

    def pub_data(self, record, table):
        self.rows[str(record["Id"])] = dict(record)
        return True


def main(state, limit, notice_id=None):
    config = get_state_config(state)
    database = MemoryDb()
    if notice_id:
        database.enqueue_notice(
            state,
            notice_id,
            config.source_url.rstrip("/") + "/Details.aspx?ID=" + notice_id,
            {"search_page": 1},
        )
    else:
        scraper.discover(database, config, limit)
    failures = scraper.process_queue(database, config, limit)
    print("SMOKE state={} rows={} failures={}".format(state, len(database.rows), len(failures)))
    for row in database.rows.values():
        print(
            "RESULT state={} id={} address={!r} city={!r} owner={!r}".format(
                state,
                row.get("Id"),
                row.get("Street"),
                row.get("City"),
                str(row.get("owner_name") or "")[:120],
            )
        )
    return 1 if failures or len(database.rows) != limit else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("state", choices=ALL_STATE_CODES)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--notice-id")
    args = parser.parse_args()
    raise SystemExit(main(args.state, args.limit, args.notice_id))
