import json
import unittest
from unittest.mock import patch

import multistate_scraper as scraper
from state_config import NEW_STATE_CODES, get_state_config, notice_table_for_state


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json, timeout))
        return FakeResponse(self.responses.pop(0))


class FakeDb:
    def __init__(self, checkpoint=None):
        self.checkpoint = checkpoint
        self.queued = {}
        self.saved_checkpoints = []

    def get_scrape_checkpoint(self, state):
        return self.checkpoint

    def enqueue_notice(self, state, notice_id, source_url, payload=None):
        key = (state, str(notice_id))
        inserted = key not in self.queued
        self.queued[key] = (source_url, payload)
        return int(inserted)

    def save_scrape_checkpoint(
        self, state, adapter, cursor, discovery_complete=False, total_discovered=0
    ):
        self.saved_checkpoints.append(
            (state, adapter, cursor, discovery_complete, total_discovered)
        )


class QueueDb:
    def __init__(self, tasks, existing=None, insert_error=False):
        self.tasks = tasks
        self.existing = existing or {}
        self.insert_error = insert_error
        self.completed = []
        self.failed = []
        self.inserted = []

    def reset_processing_notices(self, state):
        return 0

    def pending_notices(self, state, limit=None):
        return self.tasks[:limit] if limit else list(self.tasks)

    def mark_notice_processing(self, state, notice_id):
        return 1

    def get_pub_record(self, table, notice_id):
        return self.existing.get(str(notice_id))

    def pub_data(self, record, table):
        if self.insert_error:
            raise RuntimeError("database unavailable")
        self.inserted.append((table, record))
        self.existing[str(record["Id"])] = record
        return True

    def mark_notice_complete(self, state, notice_id):
        self.completed.append(str(notice_id))

    def mark_notice_failed(self, state, notice_id, error):
        self.failed.append((str(notice_id), str(error)))


class StateConfigTests(unittest.TestCase):
    def test_all_new_states_have_distinct_tables_and_adapters(self):
        tables = {notice_table_for_state(code) for code in NEW_STATE_CODES}
        self.assertEqual(len(tables), 5)
        self.assertEqual(get_state_config("fl").adapter, "florida_api")
        self.assertEqual(get_state_config("NY").adapter, "column_api")
        self.assertEqual(get_state_config("NJ").adapter, "legacy_asp")


class ApiAdapterTests(unittest.TestCase):
    def test_florida_discovery_queues_stable_ids_and_completes(self):
        payload = {
            "totalCount": 3,
            "_embedded": {
                "notices": [
                    {"id": 11, "subcategoryId": 8, "notice": "first", "_links": {"self": {"href": "https://fl/notices/11"}}},
                    {"id": 12, "notice": "NOTICE OF FORECLOSURE SALE", "_links": {"self": {"href": "https://fl/notices/12"}}},
                    {"id": 13, "subcategoryId": 17, "notice": "incidental foreclosure keyword", "_links": {"self": {"href": "https://fl/notices/13"}}},
                ]
            },
        }
        db = FakeDb()
        session = FakeSession([payload])
        count = scraper.discover_florida(
            db, get_state_config("FL"), session=session
        )
        self.assertEqual(count, 2)
        self.assertEqual(set(db.queued), {("FL", "11"), ("FL", "12")})
        self.assertTrue(db.saved_checkpoints[-1][3])

    def test_new_york_discovery_uses_date_window_and_stable_url(self):
        payload = {
            "success": True,
            "page": {"current": 1, "total_pages": 1},
            "results": [{"id": "abc-123", "text": "notice"}],
        }
        month_start = scraper.date.today().replace(day=1).isoformat()
        db = FakeDb(
            {
                "cursor": {"window_start": month_start, "page": 1},
                "Total_Discovered": 0,
                "Discovery_Complete": 0,
            }
        )
        session = FakeSession([payload])
        count = scraper.discover_new_york(
            db, get_state_config("NY"), session=session
        )
        self.assertEqual(count, 1)
        self.assertIn(("NY", "abc-123"), db.queued)
        self.assertIn("activeNotice=abc-123", db.queued[("NY", "abc-123")][0])
        filters = session.calls[0][1]["allFilters"]
        self.assertIn("publishedtimestamp", filters[1])
        self.assertTrue(db.saved_checkpoints[-1][3])

    def test_normalizer_saves_blank_address_when_parser_fails(self):
        item = {
            "id": "n1",
            "text": "<p>Legal notice without a usable property address</p>",
            "newspapername": "Test Paper",
            "publishedtimestamp": 1789171200000,
            "county": "Kings",
        }
        with patch.object(scraper.util, "parse_notice", side_effect=RuntimeError("offline")):
            record = scraper.normalize_api_notice(
                "NY", item, "https://newyork.column.us/?activeNotice=n1"
            )
        self.assertEqual(record["Id"], "n1")
        self.assertEqual(record["Street"], "")
        self.assertEqual(record["Address"], "False")
        self.assertIsNone(record["propstream_info"])
        self.assertIn("Legal notice", record["Notice"])

    def test_parser_rejects_word_only_parcel_value(self):
        parsed = {
            "Street": "57 Hilton Road",
            "City": "Phoenix",
            "Zip_Code": "13135",
            "owner_name": "Rising Hope Church",
            "parcel_number": "being",
        }
        with patch.object(scraper.util, "call_chatgpt", return_value=json.dumps(parsed)):
            result = scraper.util.parse_notice("Property at 57 Hilton Road, Phoenix NY 13135")
        self.assertEqual(result["parcel_number"], "")


class QueuePayloadTests(unittest.TestCase):
    def test_payload_dict_accepts_database_json(self):
        self.assertEqual(scraper._payload_dict(json.dumps({"id": 7})), {"id": 7})
        self.assertEqual(scraper._payload_dict({"id": 8}), {"id": 8})

    def test_legacy_discovery_payload_keeps_search_page(self):
        self.assertEqual(
            scraper._payload_dict(json.dumps({"search_page": 7}))["search_page"],
            7,
        )

    def test_restart_processes_only_pending_tasks_and_skips_saved_row(self):
        tasks = [
            {"Notice_Id": "done", "Source_Url": "https://fl/done", "Payload": "{}"},
            {
                "Notice_Id": "missed",
                "Source_Url": "https://fl/missed",
                "Payload": json.dumps({"id": "missed", "notice": "notice"}),
            },
        ]
        db = QueueDb(tasks, {"done": {"Id": "done", "Notice": "already saved"}})
        parsed = {
            "Street": "1 Main St",
            "City": "Miami",
            "Zip_Code": "33101",
            "owner_name": "Owner",
            "parcel_number": "",
        }
        with patch.object(scraper.util, "parse_notice", return_value=parsed):
            failures = scraper.process_queue(db, get_state_config("FL"))
        self.assertEqual(failures, [])
        self.assertEqual(db.completed, ["done", "missed"])
        self.assertEqual(len(db.inserted), 1)
        self.assertEqual(db.inserted[0][1]["Id"], "missed")

    def test_failed_database_insert_remains_retryable(self):
        tasks = [
            {
                "Notice_Id": "retry-me",
                "Source_Url": "https://fl/retry-me",
                "Payload": json.dumps({"id": "retry-me", "notice": "notice"}),
            }
        ]
        db = QueueDb(tasks, insert_error=True)
        with patch.object(scraper.util, "parse_notice", return_value={}):
            failures = scraper.process_queue(db, get_state_config("FL"))
        self.assertEqual(failures, ["retry-me"])
        self.assertEqual(db.completed, [])
        self.assertEqual(db.failed[0][0], "retry-me")


if __name__ == "__main__":
    unittest.main()
