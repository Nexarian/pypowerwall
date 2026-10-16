"""Unit tests for v1r key-auth warning behavior.

Covers two new code paths added in fix/v1r-pending-verification-warning:
  1. TEDAPI._connect_v1r() probes key state at init and logs an error if
     PENDING_VERIFICATION is detected.
  2. TEDAPIv1r.post_v1r() emits a warnings.warn() exactly once when the
     gateway returns an "authorization not verified" inner payload.
  3. TEDAPIv1r.post_v1r() reads the reply's MessageStatus in Tesla's layout
     (field 1 operation_status, field 2 signed_message_fault), pinned with raw
     wire bytes in TestMessageStatusWireFormat.
"""
import logging
import threading
import warnings
from unittest.mock import MagicMock, patch

import pytest

from pypowerwall.tedapi.protobuf.V2024_06 import tedapi_combined_pb2 as combined_pb2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_routable_message(
    fault=combined_pb2.MESSAGEFAULT_ERROR_NONE,
    inner_bytes: bytes = b"",
    operation_status=None,
) -> bytes:
    """Return serialized RoutableMessage bytes for use as a mock HTTP response.

    A fault goes where Tesla's schema carries it, MessageStatus field 2
    (signed_message_fault), with field 1 (operation_status) set to ERROR unless
    the caller passes operation_status."""
    if operation_status is None:
        operation_status = (combined_pb2.OPERATIONSTATUS_OK
                            if fault == combined_pb2.MESSAGEFAULT_ERROR_NONE
                            else combined_pb2.OPERATIONSTATUS_ERROR)
    msg = combined_pb2.RoutableMessage()
    msg.signed_message_status.operation_status = operation_status
    msg.signed_message_status.signed_message_fault = fault
    msg.protobuf_message_as_bytes = inner_bytes
    return msg.SerializeToString()


def _raw_response(content: bytes, status_code: int = 200):
    """Mock HTTP response whose body is exactly ``content``."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    return resp


def _make_v1r_transport():
    """Build a TEDAPIv1r with all I/O mocked (no real socket, no real RSA key)."""
    from pypowerwall.tedapi.tedapi_v1r import TEDAPIv1r

    with patch.object(TEDAPIv1r, "__init__", lambda self, *a, **kw: None):
        transport = TEDAPIv1r.__new__(TEDAPIv1r)
    # Minimal attribute setup matching the real __init__
    transport.pending_verification = False
    transport.key_unknown = False
    transport._flag_lock = threading.Lock()
    transport.host = "10.42.1.1"
    transport.timeout = 5
    transport.token = "fake-token"
    transport.din = "TEST_DIN"
    transport.key_fingerprint = "f" * 64  # fake SHA256 hex
    # Stub out RSA signing so we don't need a real key
    transport._private_key = MagicMock()
    transport._private_key.sign.return_value = b"\x00" * 64
    transport._public_key_der = b"\x00" * 32

    # Mock the session so we can control the HTTP response
    transport.session = MagicMock()
    return transport


# ---------------------------------------------------------------------------
# Tests: TEDAPI._connect_v1r() — connect-time probe
# ---------------------------------------------------------------------------

class TestConnectV1rProbe:
    """TEDAPI._connect_v1r() probes key state and logs an error on PENDING_VERIFICATION."""

    def _make_tedapi(self):
        """Build a TEDAPI instance with all network I/O mocked out."""
        with patch("pypowerwall.tedapi.TEDAPI.connect", return_value="TEST_DIN"):
            from pypowerwall.tedapi import TEDAPI
            ted = TEDAPI(gw_pwd="testpassword")
        ted.gw_ip = "10.42.1.1"
        ted.v1r = True
        ted.wifi_session = None
        return ted

    def test_connect_v1r_logs_error_when_pending_verification(self, caplog):
        """When probe returns None and pending_verification is True, an error is logged."""
        ted = self._make_tedapi()

        mock_transport = MagicMock()
        mock_transport.login.return_value = True
        mock_transport.get_din.return_value = "TEST_DIN"
        mock_transport.get_config_v1r.return_value = None
        mock_transport.pending_verification = True
        ted.v1r_transport = mock_transport

        with caplog.at_level(logging.ERROR):
            result = ted._connect_v1r()

        assert result == "TEST_DIN", "_connect_v1r() must still return the DIN"
        assert any(
            "PENDING_VERIFICATION" in record.message for record in caplog.records
        ), "Expected PENDING_VERIFICATION error to be logged"

    def test_connect_v1r_no_log_when_probe_succeeds(self, caplog):
        """When the probe returns data, no PENDING_VERIFICATION error is logged."""
        ted = self._make_tedapi()

        mock_transport = MagicMock()
        mock_transport.login.return_value = True
        mock_transport.get_din.return_value = "TEST_DIN"
        mock_transport.get_config_v1r.return_value = {"vin": "GW--123"}
        mock_transport.pending_verification = False
        ted.v1r_transport = mock_transport

        with caplog.at_level(logging.ERROR):
            result = ted._connect_v1r()

        assert result == "TEST_DIN"
        assert not any(
            "PENDING_VERIFICATION" in record.message for record in caplog.records
        )

    def test_connect_v1r_logs_error_when_key_unknown(self, caplog):
        """When probe returns None and key_unknown is True, an error is logged."""
        ted = self._make_tedapi()

        mock_transport = MagicMock()
        mock_transport.login.return_value = True
        mock_transport.get_din.return_value = "TEST_DIN"
        mock_transport.get_config_v1r.return_value = None
        mock_transport.pending_verification = False
        mock_transport.key_unknown = True
        ted.v1r_transport = mock_transport

        with caplog.at_level(logging.ERROR):
            result = ted._connect_v1r()

        assert result == "TEST_DIN"
        assert any(
            "key" in record.message.lower() and "not recognized" in record.message.lower()
            for record in caplog.records
        ), "Expected UNKNOWN_KEY_ID error to be logged"

    def test_connect_v1r_probe_seeds_config_cache(self):
        """When the probe returns config data, it is stored in the config cache."""
        ted = self._make_tedapi()

        config = {"vin": "GW--123", "site_info": {}}
        mock_transport = MagicMock()
        mock_transport.login.return_value = True
        mock_transport.get_din.return_value = "TEST_DIN"
        mock_transport.get_config_v1r.return_value = config
        mock_transport.pending_verification = False
        ted.v1r_transport = mock_transport

        result = ted._connect_v1r()

        assert result == "TEST_DIN"
        assert ted.pwcache.get("config") == config, "Probe result must seed the config cache"
        assert "config" in ted.pwcachetime

    def test_connect_v1r_no_log_when_probe_none_but_not_pending(self, caplog):
        """When probe returns None but both flags are False, no error is logged."""
        ted = self._make_tedapi()

        mock_transport = MagicMock()
        mock_transport.login.return_value = True
        mock_transport.get_din.return_value = "TEST_DIN"
        mock_transport.get_config_v1r.return_value = None
        mock_transport.pending_verification = False
        mock_transport.key_unknown = False
        ted.v1r_transport = mock_transport

        with caplog.at_level(logging.ERROR):
            result = ted._connect_v1r()

        assert result == "TEST_DIN"
        assert not any(
            "PENDING_VERIFICATION" in record.message or "not recognized" in record.message
            for record in caplog.records
        )


# ---------------------------------------------------------------------------
# Tests: TEDAPIv1r.post_v1r() — warning-once behavior
# ---------------------------------------------------------------------------

class TestPostV1rWarnings:
    """TEDAPIv1r.post_v1r() emits a UserWarning exactly once per 'authorization not verified' error."""

    def _make_transport(self):
        """Build a TEDAPIv1r with all I/O mocked (no real socket, no real RSA key)."""
        return _make_v1r_transport()

    def _mock_response(self, payload_bytes: bytes, status_code: int = 200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.content = _make_routable_message(inner_bytes=payload_bytes)
        return resp

    def test_pending_verification_emits_warning_once(self):
        """First 'authorization not verified' call emits UserWarning; second does not."""
        transport = self._make_transport()
        inner = b"v1r: client authorization not verified"
        transport.session.post.return_value = self._mock_response(inner)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result1 = transport.post_v1r(b"fake-payload", "TEST_DIN")
            result2 = transport.post_v1r(b"fake-payload", "TEST_DIN")

        assert result1 is None, "post_v1r must return None on auth failure"
        assert result2 is None

        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 1, (
            f"Expected exactly one UserWarning across two calls, got {len(user_warnings)}"
        )
        assert "PENDING_VERIFICATION" in str(user_warnings[0].message)

    def test_pending_verification_names_the_configured_key(self):
        """The recovery command must re-register the configured key, not a new one."""
        transport = self._make_transport()
        transport.rsa_key_path = "/app/.auth/tedapi_rsa_private.pem"
        transport.session.post.return_value = self._mock_response(
            b"v1r: client authorization not verified")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            transport.post_v1r(b"fake-payload", "TEST_DIN")

        message = str([w for w in caught if issubclass(w.category, UserWarning)][0].message)
        assert "python -m pypowerwall register -authpath /app/.auth" in message

    def test_pending_verification_flag_is_set(self):
        """pending_verification flag must be True after the first auth failure."""
        transport = self._make_transport()
        inner = b"authorization not verified"
        transport.session.post.return_value = self._mock_response(inner)

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            transport.post_v1r(b"fake-payload", "TEST_DIN")

        assert transport.pending_verification is True

    def test_unknown_key_emits_warning_once(self):
        """UNKNOWN_KEY_ID fault emits UserWarning exactly once across repeated calls."""
        transport = self._make_transport()
        transport.session.post.return_value = _raw_response(
            _make_routable_message(fault=combined_pb2.MESSAGEFAULT_ERROR_UNKNOWN_KEY_ID))

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result1 = transport.post_v1r(b"fake-payload", "TEST_DIN")
            result2 = transport.post_v1r(b"fake-payload", "TEST_DIN")

        assert result1 is None
        assert result2 is None
        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 1, (
            f"Expected exactly one UserWarning across two calls, got {len(user_warnings)}"
        )
        assert "UNKNOWN_KEY_ID" in str(user_warnings[0].message)
        assert transport.key_unknown is True

    def test_empty_inner_emits_warning_once(self):
        """Empty inner payload with no fault code fires UserWarning exactly once.

        This covers the unregistered-key case where the gateway returns HTTP 200
        with 101 bytes, MESSAGEFAULT_ERROR_NONE, and no protobuf_message_as_bytes.
        The response does not contain 'authorization not verified' text either —
        the error is only detectable by the empty inner payload.
        """
        transport = self._make_transport()
        # Response with no inner bytes and no fault — the unregistered-key 101-byte case
        empty_resp = MagicMock()
        empty_resp.status_code = 200
        empty_resp.content = _make_routable_message(inner_bytes=b"")
        transport.session.post.return_value = empty_resp

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result1 = transport.post_v1r(b"fake-payload", "TEST_DIN")
            result2 = transport.post_v1r(b"fake-payload", "TEST_DIN")

        assert result1 is None
        assert result2 is None
        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 1, (
            f"Expected exactly one UserWarning across two calls, got {len(user_warnings)}"
        )
        assert transport.key_unknown is True

    def test_flags_reset_on_recovery(self):
        """A successful response clears the failure flags so a later failure warns again.

        This models the real-world verification flow: key is PENDING, user
        toggles the breaker while the process is running, key becomes VERIFIED,
        and data starts flowing. If the key later breaks again (e.g., gateway
        factory reset), the warning must fire again rather than staying
        suppressed for the life of the session.
        """
        transport = self._make_transport()
        bad = self._mock_response(b"v1r: client authorization not verified")
        good = self._mock_response(b"\x08\x01\x12\x03abc")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            transport.session.post.return_value = bad
            assert transport.post_v1r(b"fake", "TEST_DIN") is None
            assert transport.pending_verification is True

            transport.session.post.return_value = good
            assert transport.post_v1r(b"fake", "TEST_DIN") == b"\x08\x01\x12\x03abc"
            assert transport.pending_verification is False, "Success must clear the flag"
            assert transport.key_unknown is False

            transport.session.post.return_value = bad
            assert transport.post_v1r(b"fake", "TEST_DIN") is None

        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 2, (
            f"Expected a warning per failure episode (2), got {len(user_warnings)}"
        )

    def test_unknown_key_warning_includes_fingerprint(self):
        """UNKNOWN_KEY_ID warning must include the local key fingerprint for comparison."""
        transport = self._make_transport()
        transport.session.post.return_value = _raw_response(
            _make_routable_message(fault=combined_pb2.MESSAGEFAULT_ERROR_UNKNOWN_KEY_ID))

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            transport.post_v1r(b"fake-payload", "TEST_DIN")

        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 1
        assert transport.key_fingerprint in str(user_warnings[0].message)

    def test_valid_response_returns_inner_bytes(self):
        """A well-formed response returns the inner bytes without a warning."""
        transport = self._make_transport()
        inner = b"\x08\x01\x12\x03abc"  # fake valid protobuf
        transport.session.post.return_value = self._mock_response(inner)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = transport.post_v1r(b"fake-payload", "TEST_DIN")

        assert result == inner
        assert not any(issubclass(w.category, UserWarning) for w in caught)
        assert transport.pending_verification is False
        assert transport.key_unknown is False


# ---------------------------------------------------------------------------
# Tests: MessageStatus wire format (Tesla's universal_message schema)
# ---------------------------------------------------------------------------

# Replies built byte by byte from Tesla's schema instead of with our generated
# classes, so a wrong field number in tedapi_combined.proto can't make these
# tests agree with the code. That is how the old bug hid: the test helper and
# post_v1r() shared the same wrong MessageStatus, field 1 read as the fault.
#   0x62 <len>  RoutableMessage.signed_message_status (field 12, length-delimited)
#   0x08 <v>    MessageStatus.operation_status (field 1): OK=0, WAIT=1, ERROR=2
#   0x10 <v>    MessageStatus.signed_message_fault (field 2): MessageFault_E
#   0x52 <len>  RoutableMessage.protobuf_message_as_bytes (field 10)
# Sources: github.com/teslamotors/vehicle-command universal_message.proto and the
# Tesla One 26.19.1/26.20.0 app's RoutableMessage decoder. These are not hardware
# captures; no gateway fault reply has been decoded against field 2 yet.
WIRE_ERROR_UNKNOWN_KEY_ID = bytes.fromhex("620408021003")  # ERROR + UNKNOWN_KEY_ID (3)
WIRE_FAULT_ONLY_UNKNOWN_KEY_ID = bytes.fromhex("62021003")  # fault with no ERROR status
WIRE_ERROR_TIMEOUT = bytes.fromhex("620408021002")         # ERROR + TIMEOUT (2)
WIRE_ERROR_NO_FAULT = bytes.fromhex("62020802")            # ERROR, no fault code
WIRE_WAIT_NO_PAYLOAD = bytes.fromhex("62020801")           # WAIT, no fault, no payload
VALID_INNER = b"\x08\x01\x12\x03abc"


def _error_reply(fault: int) -> bytes:
    """ERROR status plus ``fault``, encoded by hand (single-byte varints only)."""
    assert 0 <= fault < 128
    return bytes([0x62, 0x04, 0x08, 0x02, 0x10, fault])


class TestMessageStatusWireFormat:
    """post_v1r() reads MessageStatus as Tesla lays it out on the wire."""

    def test_schema_matches_tesla_field_layout(self):
        """Our generated classes decode and encode Tesla's bytes exactly."""
        msg = combined_pb2.RoutableMessage()
        msg.ParseFromString(WIRE_ERROR_UNKNOWN_KEY_ID)
        assert msg.signed_message_status.operation_status == combined_pb2.OPERATIONSTATUS_ERROR
        assert msg.signed_message_status.signed_message_fault == combined_pb2.MESSAGEFAULT_ERROR_UNKNOWN_KEY_ID

        out = combined_pb2.RoutableMessage()
        out.signed_message_status.operation_status = combined_pb2.OPERATIONSTATUS_ERROR
        out.signed_message_status.signed_message_fault = combined_pb2.MESSAGEFAULT_ERROR_UNKNOWN_KEY_ID
        assert out.SerializeToString() == WIRE_ERROR_UNKNOWN_KEY_ID

    def test_fault_enum_matches_tesla_schema(self):
        """Value 22 has Tesla's name and the newer values 23-29 are known."""
        name = combined_pb2.MessageFault_E.Name
        assert name(22) == "MESSAGEFAULT_ERROR_REMOTE_SERVICE_ACCESS_DISABLED"
        assert name(27) == "MESSAGEFAULT_ERROR_INVALID_KEY_HANDLE"
        assert name(29) == "MESSAGEFAULT_ERROR_COMMAND_REQUIRES_PHYSICAL_PROXIMITY"

    def test_unknown_key_id_reply_warns(self):
        """ERROR + UNKNOWN_KEY_ID raises the key warning (it used to decode as TIMEOUT)."""
        transport = _make_v1r_transport()
        transport.session.post.return_value = _raw_response(WIRE_ERROR_UNKNOWN_KEY_ID)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert transport.post_v1r(b"fake-payload", "TEST_DIN") is None

        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 1
        assert "UNKNOWN_KEY_ID" in str(user_warnings[0].message)
        assert transport.key_unknown is True

    def test_fault_without_error_status_still_fails(self):
        """A fault code alone fails the reply, as in the Tesla One app's decoder."""
        transport = _make_v1r_transport()
        transport.session.post.return_value = _raw_response(WIRE_FAULT_ONLY_UNKNOWN_KEY_ID)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert transport.post_v1r(b"fake-payload", "TEST_DIN") is None

        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 1
        assert "UNKNOWN_KEY_ID" in str(user_warnings[0].message)

    @pytest.mark.parametrize("fault, expected", [
        (5, "MESSAGEFAULT_ERROR_INVALID_SIGNATURE"),
        (22, "MESSAGEFAULT_ERROR_REMOTE_SERVICE_ACCESS_DISABLED"),
        (27, "MESSAGEFAULT_ERROR_INVALID_KEY_HANDLE"),
        (127, "v1r response fault: 127 "),  # newer than our schema: reported by number
    ])
    def test_other_faults_are_logged_by_their_real_name(self, caplog, fault, expected):
        """Other faults log at ERROR under their own name, never as TIMEOUT."""
        transport = _make_v1r_transport()
        transport.session.post.return_value = _raw_response(_error_reply(fault))

        with caplog.at_level(logging.DEBUG, logger="pypowerwall.tedapi.tedapi_v1r"):
            assert transport.post_v1r(b"fake-payload", "TEST_DIN") is None

        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert any(expected in m and "OPERATIONSTATUS_ERROR" in m for m in errors), errors
        assert not any("TIMEOUT" in r.getMessage() for r in caplog.records)
        assert not any("v1r POST error" in m for m in errors), "fault name lookup must not raise"
        assert transport.key_unknown is False

    def test_timeout_fault_stays_at_debug(self, caplog):
        """ERROR + TIMEOUT keeps its quiet debug path (sub-device routing)."""
        transport = _make_v1r_transport()
        transport.session.post.return_value = _raw_response(WIRE_ERROR_TIMEOUT)

        with caplog.at_level(logging.DEBUG, logger="pypowerwall.tedapi.tedapi_v1r"):
            assert transport.post_v1r(b"fake-payload", "TEST_DIN") is None

        assert any("MESSAGEFAULT_ERROR_TIMEOUT" in r.getMessage()
                   for r in caplog.records if r.levelno == logging.DEBUG)
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_error_status_without_fault_code_fails(self, caplog):
        """ERROR with no fault code fails the reply without blaming the key."""
        transport = _make_v1r_transport()
        transport.session.post.return_value = _raw_response(WIRE_ERROR_NO_FAULT)

        with caplog.at_level(logging.DEBUG, logger="pypowerwall.tedapi.tedapi_v1r"):
            assert transport.post_v1r(b"fake-payload", "TEST_DIN") is None

        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert any("OPERATIONSTATUS_ERROR" in m for m in errors), errors
        assert transport.key_unknown is False
        assert transport.pending_verification is False

    def test_wait_without_payload_is_not_a_key_failure(self, caplog):
        """WAIT with no payload is reported as busy, not as an unrecognized key."""
        transport = _make_v1r_transport()
        transport.session.post.return_value = _raw_response(WIRE_WAIT_NO_PAYLOAD)

        with warnings.catch_warnings(record=True) as caught, \
                caplog.at_level(logging.DEBUG, logger="pypowerwall.tedapi.tedapi_v1r"):
            warnings.simplefilter("always")
            assert transport.post_v1r(b"fake-payload", "TEST_DIN") is None

        assert not [w for w in caught if issubclass(w.category, UserWarning)]
        assert transport.key_unknown is False
        assert any("OPERATIONSTATUS_WAIT" in r.getMessage()
                   for r in caplog.records if r.levelno == logging.ERROR)

    def test_wait_with_payload_returns_payload(self):
        """WAIT is not a failure by itself: a payload is returned, as the app does."""
        transport = _make_v1r_transport()
        reply = WIRE_WAIT_NO_PAYLOAD + bytes([0x52, len(VALID_INNER)]) + VALID_INNER
        transport.session.post.return_value = _raw_response(reply)

        assert transport.post_v1r(b"fake-payload", "TEST_DIN") == VALID_INNER
