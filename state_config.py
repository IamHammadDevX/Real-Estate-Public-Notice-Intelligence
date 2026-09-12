"""Central configuration for every supported public-notice state."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StateConfig:
    code: str
    notice_table: str
    propstream_table: str
    source_url: str
    adapter: str


STATE_CONFIGS = {
    "GA": StateConfig("GA", "GaPub", "propstream_ga", "https://www.georgiapublicnotice.com/", "legacy_asp"),
    "NC": StateConfig("NC", "NcPub", "propstream_nc", "https://www.ncnotices.com/", "legacy_asp"),
    "FL": StateConfig("FL", "FlPub", "propstream_fl", "https://floridapublicnotices.com/", "florida_api"),
    "NY": StateConfig("NY", "NyPub", "propstream_ny", "https://newyork.column.us/", "column_api"),
    "NJ": StateConfig("NJ", "NjPub", "propstream_nj", "https://www.njpublicnotices.com/", "legacy_asp"),
    "MD": StateConfig("MD", "MdPub", "propstream_md", "https://www.mddcpublicnotices.com/", "legacy_asp"),
    "TX": StateConfig("TX", "TxPub", "propstream_tx", "https://www.texaspublicnotices.com/", "legacy_asp"),
}

ALL_STATE_CODES = tuple(STATE_CONFIGS)
NEW_STATE_CODES = ("FL", "NY", "NJ", "MD", "TX")
NOTICE_TABLES = frozenset(config.notice_table for config in STATE_CONFIGS.values())
PROPSTREAM_TABLES = frozenset(config.propstream_table for config in STATE_CONFIGS.values())


def get_state_config(state):
    code = str(state).upper()
    try:
        return STATE_CONFIGS[code]
    except KeyError as error:
        raise ValueError("Unsupported state: {}".format(state)) from error


def notice_table_for_state(state):
    return get_state_config(state).notice_table


def propstream_table_for_state(state):
    return get_state_config(state).propstream_table
