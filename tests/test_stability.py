import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import db_file
import helper_consolidated as util


class DisconnectError(Exception):
    errno = 4031


class FakeCursor:
    def __init__(self, fail_once=False, one=(1,)):
        self.fail_once = fail_once
        self.one = one
        self.rowcount = 1
        self.column_names = ("value",)
        self.executions = []
        self.closed = False

    def execute(self, query, params=()):
        self.executions.append((query, params))
        if self.fail_once:
            self.fail_once = False
            raise DisconnectError("idle timeout")

    def fetchone(self):
        return self.one

    def fetchall(self):
        return [self.one]

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.connected = True
        self.commits = 0

    def is_connected(self):
        return self.connected

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def close(self):
        self.connected = False


class DatabaseStabilityTests(unittest.TestCase):
    def make_database(self, connection):
        database = db_file.Mysql.__new__(db_file.Mysql)
        database.dev = True
        database.config = {"host": "unused"}
        database.connection = connection
        database.cursor = connection.cursor()
        database.print_log = Mock()
        return database

    def test_execute_reconnects_and_retries_once_on_idle_disconnect(self):
        old_cursor = FakeCursor(fail_once=True)
        new_cursor = FakeCursor(one=(7,))
        database = self.make_database(FakeConnection(old_cursor))
        replacement = FakeConnection(new_cursor)

        with patch("db_file.mysql.connector.connect", return_value=replacement) as connect:
            result = database._execute("SELECT 7", fetch="one")

        self.assertEqual((7,), result)
        connect.assert_called_once_with(**database.config)
        self.assertEqual(1, len(old_cursor.executions))
        self.assertEqual(1, len(new_cursor.executions))

    def test_blank_address_notice_is_inserted_with_null_status(self):
        database = db_file.Mysql.__new__(db_file.Mysql)
        database._execute = Mock(return_value=(0,))
        database.run_query = Mock(return_value=1)
        database.print_log = Mock()
        record = {
            "Id": "notice-1",
            "Street": "",
            "City": "",
            "Notice": "Estate of O'Brien",
            "propstream_info": None,
        }

        self.assertTrue(database.pub_data(record, "GaPub"))
        query, params = database.run_query.call_args.args
        self.assertTrue(query.startswith("INSERT INTO `GaPub`"))
        self.assertIn("Estate of O'Brien", params)
        self.assertIsNone(params[-1])

    def test_propstream_tag_is_not_written_when_source_row_is_missing(self):
        database = db_file.Mysql.__new__(db_file.Mysql)
        database._execute = Mock(return_value=(0,))
        database.run_query = Mock()
        database.print_log = Mock()

        self.assertFalse(database.set_propstream_info("GaPub", "missing", "N"))
        database.run_query.assert_not_called()


class FallbackCsvTests(unittest.TestCase):
    def test_fallback_unions_schema_and_upserts_duplicate_id(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(util, "_ensure_exports_dir", return_value=directory), patch.object(
                util, "FALLBACK_RUN_ID", "test"
            ):
                path = util._save_record_to_csv({"Id": "1", "Street": "A"}, "GaPub")
                util._save_record_to_csv({"Id": "2", "City": "B"}, "GaPub")
                util._save_record_to_csv({"Id": "1", "Street": "Updated"}, "GaPub")

            with open(path, newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

            self.assertEqual(["Id", "Street", "City"], reader.fieldnames)
            self.assertEqual(2, len(rows))
            self.assertEqual("Updated", rows[0]["Street"])
            self.assertEqual("B", rows[1]["City"])

    def test_notice_falls_back_when_database_write_fails(self):
        database = Mock()
        database.pub_data.side_effect = DisconnectError("write failed")
        record = {"Id": "1", "Street": "", "City": "", "propstream_info": None}

        with patch.object(util, "_save_record_to_csv", return_value="fallback.csv") as save:
            location = util.save_notice_record(database, record, "GaPub")

        self.assertEqual("csv", location)
        save.assert_called_once_with(record, "GaPub")


class NoticeParsingTests(unittest.TestCase):
    def test_pdf_text_uses_authenticated_browser_request(self):
        page = Mock()
        page.url = "https://example.test/Details.aspx?id=1"
        response = Mock(ok=True)
        response.body.return_value = b"pdf"
        page.context.request.get.return_value = response
        pdf_reader = Mock()
        pdf_reader.pages = [Mock(extract_text=Mock(return_value="Property text"))]

        with patch.object(util, "PdfReader", return_value=pdf_reader):
            text = util.extract_pdf_text(page, "notice.pdf")

        self.assertEqual("Property text", text)
        page.context.request.get.assert_called_once_with(
            "https://example.test/notice.pdf", timeout=util.GRID_TIMEOUT_MS
        )

    def test_fallback_extracts_ga_tax_notice_address_owner_and_parcel(self):
        notice = (
            "TO: KIM L. COGAR TAMMY S. COGAR UNKNOWN HEIRS Occupant "
            "155 POLK ROAD, Newton County, Georgia. That property known as "
            "155 POLK ROAD, according to the present system of numbering homes "
            "and having tax parcel identification number 0075000000002000."
        )
        with patch.object(
            util, "call_chatgpt", side_effect=RuntimeError("API unavailable")
        ):
            result = util.parse_notice(notice)

        self.assertEqual("155 POLK ROAD", result["Street"])
        self.assertEqual(
            "KIM L. COGAR TAMMY S. COGAR UNKNOWN HEIRS", result["owner_name"]
        )
        self.assertEqual("0075000000002000", result["parcel_number"])
        self.assertEqual("True", result["Address"])

    def test_fallback_fills_fields_missing_from_api(self):
        notice = (
            "The party in possession of the property is Allen Ricks And Pauline "
            "Nelson or tenant(s); and said property is more commonly known as "
            "115 Heyman Drive, Covington, GA 30016."
        )
        with patch.object(
            util, "call_chatgpt", return_value='{"Street":"","City":""}'
        ):
            result = util.parse_notice(notice)

        self.assertEqual("115 Heyman Drive", result["Street"])
        self.assertEqual("Covington", result["City"])
        self.assertEqual("30016", result["Zip_Code"])
        self.assertEqual(
            "Allen Ricks And Pauline Nelson", result["owner_name"]
        )

    def test_non_property_deadline_notice_remains_blank(self):
        notice = (
            "Foreclosure Deadlines: send a request for a deadline calendar "
            "to the publisher email."
        )
        with patch.object(
            util, "call_chatgpt", side_effect=RuntimeError("API unavailable")
        ):
            self.assertEqual({}, util.parse_notice(notice))

    def test_incomplete_address_is_not_propstream_eligible(self):
        self.assertFalse(
            util.is_propstream_eligible(
                {"Street": "155 Polk Road", "City": "", "State": "GA"}
            )
        )
        self.assertTrue(
            util.is_propstream_eligible(
                {
                    "Street": "115 Heyman Drive",
                    "City": "Covington",
                    "State": "GA",
                }
            )
        )

    def test_fallback_extracts_judicial_defendants(self):
        notice = (
            "NEWREZ LLC Plaintiff, vs. JUSTIN A WHITMER, ALL UNKNOWN HEIRS OF "
            "TIFFANY E. WHITMER, Defendants. The property commonly known as "
            "249 PARR FARM ROAD COVINGTON, GA 30016."
        )
        fields = util._fallback_notice_fields(notice)
        self.assertEqual("JUSTIN A WHITMER", fields["owner_name"])

    def test_fallback_uses_explicit_town_for_city(self):
        notice = (
            "Occupant 193 JOHNSON ST, Newton County, Georgia. All land lying "
            "and being in the Town of Newborn, Newton County, Georgia."
        )
        fields = util._fallback_notice_fields(notice)
        self.assertEqual("Newborn", fields["City"])


class PropStreamStatusTests(unittest.TestCase):
    def record(self):
        return {
            "Id": "9367656",
            "Table_Index": 1,
            "Street": "249 Parr Farm Road",
            "City": "Covington",
            "State": "GA",
            "Zip_Code": "30016",
            "propstream_info": None,
        }

    def test_zero_suggestions_sets_n_after_completed_lookup(self):
        database = Mock()
        database.set_propstream_info.return_value = True
        record = self.record()

        with patch.object(util, "propstream_information", return_value=[]):
            result = util.get_propstream_data(database, Mock(), record, "propstream_ga")

        self.assertEqual([], result)
        self.assertEqual("N", record["propstream_info"])
        database.set_propstream_info.assert_called_once_with("GaPub", "9367656", "N")

    def test_lookup_error_leaves_status_null(self):
        database = Mock()
        record = self.record()

        with patch.object(
            util, "propstream_information", side_effect=RuntimeError("request failed")
        ):
            result = util.get_propstream_data(database, Mock(), record, "propstream_ga")

        self.assertEqual([], result)
        self.assertIsNone(record["propstream_info"])
        database.set_propstream_info.assert_not_called()

    def test_valid_saved_detail_sets_y(self):
        database = Mock()
        database.propstreams.return_value = True
        database.set_propstream_info.return_value = True
        record = self.record()

        with patch.object(util, "propstream_information", return_value=["prop-1"]), patch.object(
            util, "get_propstream_address_details", return_value={"owner_name": "Owner"}
        ):
            result = util.get_propstream_data(database, Mock(), record, "propstream_ga")

        self.assertEqual(1, len(result))
        self.assertEqual("Y", record["propstream_info"])
        database.set_propstream_info.assert_called_once_with("GaPub", "9367656", "Y")

    def test_detail_or_storage_failure_does_not_set_y_or_n(self):
        database = Mock()
        database.propstreams.side_effect = RuntimeError("DB write failed")
        record = self.record()

        with patch.object(util, "propstream_information", return_value=["prop-1"]), patch.object(
            util, "get_propstream_address_details", return_value={"owner_name": "Owner"}
        ), patch.object(util, "_save_record_to_csv", return_value="fallback.csv"):
            result = util.get_propstream_data(database, Mock(), record, "propstream_ga")

        self.assertEqual(1, len(result))
        self.assertIsNone(record["propstream_info"])
        database.set_propstream_info.assert_not_called()


class NavigationRecoveryTests(unittest.TestCase):
    def test_recovery_retries_after_interrupted_navigation(self):
        page = Mock()
        page.url = "chrome-error://chromewebdata/"

        with patch.object(
            util, "select_filters_again", side_effect=[RuntimeError("broken"), None]
        ), patch.object(util, "_current_search_page", return_value=1), patch.object(
            util.time, "sleep"
        ):
            recovered = util.recover_search_page(page, "https://example.test/", 1)

        self.assertIs(page, recovered)
        self.assertEqual(2, page.goto.call_count)


if __name__ == "__main__":
    unittest.main()
