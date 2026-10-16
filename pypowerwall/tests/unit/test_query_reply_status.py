"""TEDAPI query replies are read the way the Tesla One app reads them.

A GraphQL query reply (GraphQLAPIQueryResponse) carries a status (field 1), its
data (field 2) and errors (field 3), and a reply envelope can carry
common.errorResponse (a google.rpc.Status) instead. The app's query fetcher
(Tesla One 26.20.0) treats GRAPH_QL_STATUS_ERROR_FULL as "no data" and
otherwise parses the data with the errors kept alongside; its RPC client raises
an errorResponse as the request's error.

Replies are built byte by byte in Tesla's layout rather than with our generated
classes, so a wrong field number in a .proto can't make these tests agree with
the code. Layout (energy_device.v1, confirmed against the 26.20.0 bundle):
  MessageEnvelope: common = 4, filestore = 15, graphql = 16
  GraphQLMessages: queryResponse = 2
  GraphQLAPIQueryResponse: status = 1, data = 2, errors = 3
  GraphQLError: path = 1, code = 2, message = 3
  CommonMessages: errorResponse = 1;  ErrorResponse: status = 1
  google.rpc.Status: code = 1, message = 2
"""
import logging
from unittest.mock import patch

import pytest

from pypowerwall.tedapi import TEDAPI, V2026_06_REJECTED_HINT

# The V2026_06 pb2 requires protobuf>=6.33.6; the default path stays on the
# 4.25.1 floor, so skip the V2026_06 tests on an older runtime.
try:
    from pypowerwall.tedapi.protobuf.V2026_06 import \
        tedapi_v2_energy_device_pb2 as ed
    HAVE_V2026 = True
except Exception:  # pylint: disable=broad-except
    ed = None
    HAVE_V2026 = False

v2026_only = pytest.mark.skipif(not HAVE_V2026, reason="V2026_06 protos require protobuf>=6.33.6")
LOGGER = "pypowerwall.tedapi"

# GraphQLStatus and GraphQLErrorCode values (Tesla's numbering)
INVALID, SUCCESS, ERROR_PARTIAL, ERROR_FULL = 0, 1, 2, 3
FIELD_NOT_FOUND, RESOLVER_PROCESS_UNRESPONSIVE = 1, 3


# ---------------------------------------------------------------------------
# Wire helpers (test-only): protobuf varint and length-delimited fields
# ---------------------------------------------------------------------------

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _vint(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _len(field: int, payload: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(payload)) + payload


def query_reply(status=None, data=None, errors=()) -> bytes:
    """MessageEnvelope{graphql{queryResponse{status, data, errors}}}."""
    body = b""
    if status is not None:
        body += _vint(1, status)
    if data is not None:
        body += _len(2, data.encode())
    for path, code, message in errors:
        body += _len(3, b"".join(_len(1, p.encode()) for p in path)
                     + _vint(2, code) + _len(3, message.encode()))
    return _len(16, _len(2, body))


def error_reply(code: int, message: str = "") -> bytes:
    """MessageEnvelope{common{errorResponse{status{code, message}}}}."""
    status = _vint(1, code) + (_len(2, message.encode()) if message else b"")
    return _len(4, _len(1, _len(1, status)))


def full_message(envelope: bytes) -> bytes:
    """Transport Message{message = envelope, tail{value = 1}}, as basic mode gets."""
    return _len(1, envelope) + _len(2, _vint(1, 1))


# The shape the 2026-06-18 hardware validation observed for an unsigned query
# and for one with a bogus signature: a query response with status 0 and no data
# or errors (proto3 omits the zero status, leaving an empty queryResponse).
WIRE_REJECTED = bytes.fromhex("8201021200")


@pytest.fixture
def api():
    with patch("pypowerwall.tedapi.TEDAPI.connect", return_value="TEST_DIN"):
        a = TEDAPI("test_password", tedapi_api_version="V2026_06")
    a.din = "1538000-45-D--TESTDIN0000000"
    a.v1r = True   # a v1r LAN reply is a bare MessageEnvelope
    return a


def _records(caplog, level):
    return [r.getMessage() for r in caplog.records if r.levelno == level]


# ---------------------------------------------------------------------------
# V2026_06
# ---------------------------------------------------------------------------

@v2026_only
class TestV2026Wire:
    """The V2026_06 schema decodes Tesla's bytes field for field."""

    def test_rejected_reply_bytes(self):
        assert query_reply() == WIRE_REJECTED

    def test_query_reply_layout(self):
        env = ed.MessageEnvelope()
        env.ParseFromString(query_reply(ERROR_PARTIAL, '{"a":1}', [(["x", "y"], FIELD_NOT_FOUND, "nope")]))
        resp = env.graphql.queryResponse
        assert (resp.status, resp.data) == (ERROR_PARTIAL, '{"a":1}')
        assert (list(resp.errors[0].path), resp.errors[0].code, resp.errors[0].message) == \
            (["x", "y"], FIELD_NOT_FOUND, "nope")

    def test_error_response_layout(self):
        env = ed.MessageEnvelope()
        env.ParseFromString(error_reply(7, "denied"))
        assert env.WhichOneof("payload") == "common"
        assert env.common.WhichOneof("message") == "errorResponse"
        assert (env.common.errorResponse.status.code, env.common.errorResponse.status.message) == (7, "denied")


@v2026_only
class TestV2026Replies:
    """_parse_signed_query_response on each kind of reply."""

    def test_success_returns_data_quietly(self, api, caplog):
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            assert api._parse_signed_query_response(query_reply(SUCCESS, '{"ok":1}')) == '{"ok":1}'
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_partial_errors_keep_data_without_rotation_warning(self, api, caplog):
        """Errors next to data used to raise the key-rotation warning."""
        reply = query_reply(ERROR_PARTIAL, '{"ok":1}', [(["esCan", "bus"], FIELD_NOT_FOUND, "no such field")])
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            assert api._parse_signed_query_response(reply) == '{"ok":1}'
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        debug = " ".join(_records(caplog, logging.DEBUG))
        assert "GRAPH_QL_STATUS_ERROR_PARTIAL" in debug
        assert "GRAPH_QL_ERROR_CODE_FIELD_NOT_FOUND: no such field (at esCan.bus)" in debug

    def test_error_full_fails_without_rotation_warning(self, api, caplog):
        """ERROR_FULL has no usable data, even if some came along (as in the app)."""
        reply = query_reply(ERROR_FULL, '{"stale":1}', [([], RESOLVER_PROCESS_UNRESPONSIVE, "busy")])
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            assert api._parse_signed_query_response(reply) is None
        errors = " ".join(_records(caplog, logging.ERROR))
        assert "GRAPH_QL_STATUS_ERROR_FULL" in errors
        assert "GRAPH_QL_ERROR_CODE_RESOLVER_PROCESS_UNRESPONSIVE: busy" in errors
        assert V2026_06_REJECTED_HINT not in _records(caplog, logging.WARNING)

    def test_rejected_query_is_reported(self, api, caplog):
        """The hardware-observed rejection used to return None with nothing logged."""
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            assert api._parse_signed_query_response(WIRE_REJECTED) is None
        assert any("GRAPH_QL_STATUS_INVALID" in m and "not run by the gateway" in m
                   for m in _records(caplog, logging.ERROR))
        assert _records(caplog, logging.WARNING) == [V2026_06_REJECTED_HINT]

    @pytest.mark.parametrize("reply", [b"", _vint(1, 1)], ids=["empty-body", "no-payload"])
    def test_empty_envelope_is_reported_as_possible_rejection(self, api, caplog, reply):
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            assert api._parse_signed_query_response(reply) is None
        assert any("empty envelope" in m for m in _records(caplog, logging.ERROR))
        assert _records(caplog, logging.WARNING) == [V2026_06_REJECTED_HINT]

    def test_other_payload_is_reported(self, api, caplog):
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            assert api._parse_signed_query_response(_len(15, b"")) is None
        assert any("envelope payload: filestore" in m for m in _records(caplog, logging.ERROR))
        assert not _records(caplog, logging.WARNING)

    def test_gateway_error_response_is_reported(self, api, caplog):
        """common.errorResponse used to be dropped: a silent None."""
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            assert api._parse_signed_query_response(error_reply(7, "client not authorized")) is None
        assert any("PERMISSION_DENIED (7): client not authorized" in m
                   for m in _records(caplog, logging.ERROR))
        assert not _records(caplog, logging.WARNING)

    def test_values_newer_than_the_schema_are_reported_by_number(self, api, caplog):
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            assert api._parse_signed_query_response(query_reply(9)) is None
            assert api._parse_signed_query_response(error_reply(99)) is None
            assert api._parse_signed_query_response(
                query_reply(ERROR_PARTIAL, "{}", [([], 42, "new")])) == "{}"
        errors = _records(caplog, logging.ERROR)
        assert any("query returned no data (9)" in m for m in errors)
        assert any("the gateway answered 99 (99)" in m for m in errors)
        assert any("42: new" in m for m in _records(caplog, logging.DEBUG))

    def test_basic_mode_full_message_uses_the_same_rules(self, api, caplog):
        api.v1r = False
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            assert api._parse_signed_query_response(full_message(query_reply(SUCCESS, "{}"))) == "{}"
            assert api._parse_signed_query_response(full_message(WIRE_REJECTED)) is None
        assert _records(caplog, logging.WARNING) == [V2026_06_REJECTED_HINT]
