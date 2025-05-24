# -*- coding: utf-8 -*-
"""
Unit tests for the TEDAPI class
"""

import json
import pytest
import time
from unittest.mock import Mock, patch, MagicMock, call
from http import HTTPStatus
import requests
import threading

# Import the module to test
from pypowerwall.tedapi import TEDAPI, lookup, uses_api_lock


@pytest.fixture
def mock_tedapi():
    """Create a TEDAPI instance with mocked connection"""
    with patch('pypowerwall.tedapi.TEDAPI.connect', return_value="TEST_DIN"):
        api = TEDAPI("test_password", pwcacheexpire=50)
    return api


@pytest.fixture
def mock_tedapi_with_cache():
    """Create a TEDAPI instance with pre-populated cache"""
    with patch('pypowerwall.tedapi.TEDAPI.connect', return_value="TEST_DIN"):
        api = TEDAPI("test_password")

    # Pre-populate cache with test data
    api.pwcache = {
        "din": "TEST_DIN",
        "config": {
            "vin": "1232100-00-E--TG11234567890",
            "battery_blocks": []
        },
        "status": {
            "control": {
                "systemStatus": {
                    "nominalEnergyRemainingWh": 10000,
                    "nominalFullPackEnergyWh": 13500
                }
            }
        }
    }
    api.pwcachetime = {
        "din": time.time(),
        "config": time.time(),
        "status": time.time()
    }
    return api


class TestUtilityFunctions:
    """Test utility functions"""

    def test_lookup_simple(self):
        """Test lookup function with simple dictionary"""
        data = {"key1": {"key2": "value"}}
        assert lookup(data, ["key1", "key2"]) == "value"

    def test_lookup_missing_key(self):
        """Test lookup with missing key"""
        data = {"key1": {"key2": "value"}}
        assert lookup(data, ["key1", "missing"]) is None

    def test_lookup_non_dict(self):
        """Test lookup when intermediate value is not a dict"""
        data = {"key1": "not_a_dict"}
        assert lookup(data, ["key1", "key2"]) is None

    def test_lookup_empty_keylist(self):
        """Test lookup with empty key list"""
        data = {"key1": "value"}
        assert lookup(data, []) == {"key1": "value"}

    def test_uses_api_lock_decorator(self):
        """Test the uses_api_lock decorator"""
        @uses_api_lock
        def test_func(self_function=None):
            return self_function

        # Should create a lock attribute
        assert hasattr(test_func, 'api_lock')
        assert isinstance(test_func.api_lock, type(threading.Lock())) # type: ignore

        # Should inject self_function
        result = test_func()
        assert result == test_func.__wrapped__


class TestTEDAPIInit:
    """Test TEDAPI initialization"""

    @patch('pypowerwall.tedapi.TEDAPI.connect')
    def test_init_success(self, mock_connect):
        """Test successful initialization"""
        mock_connect.return_value = "TEST_DIN"

        api = TEDAPI("test_password")

        assert api.gw_pwd == "test_password"
        assert api.debug is False
        assert api.pwcacheexpire == 5
        assert api.timeout == 5
        assert api.pwconfigexpire == 5
        assert api.gw_ip == "192.168.91.1"
        assert api.din == "TEST_DIN"
        assert api.pw3 is False
        mock_connect.assert_called_once()

    def test_init_missing_password(self):
        """Test initialization with missing password"""
        with pytest.raises(ValueError, match="Missing gw_pwd"):
            TEDAPI("")

    @patch('pypowerwall.tedapi.TEDAPI.connect')
    def test_init_custom_params(self, mock_connect):
        """Test initialization with custom parameters"""
        mock_connect.return_value = "TEST_DIN"

        api = TEDAPI(
            "test_password",
            debug=True,
            pwcacheexpire=10,
            timeout=15,
            pwconfigexpire=20,
            host="192.168.1.100"
        )

        assert api.debug is True
        assert api.pwcacheexpire == 10
        assert api.timeout == 15
        assert api.pwconfigexpire == 20
        assert api.gw_ip == "192.168.1.100"


class TestTEDAPIConnection:
    """Test TEDAPI connection methods"""

    @patch('requests.get')
    @patch('pypowerwall.tedapi.TEDAPI.get_din')
    def test_connect_success(self, mock_get_din, mock_requests_get):
        """Test successful connection"""
        mock_requests_get.return_value.status_code = HTTPStatus.OK
        mock_get_din.return_value = "TEST_DIN"

        # Create instance with mocked connect
        with patch('pypowerwall.tedapi.TEDAPI.connect', return_value="TEST_DIN"):
            api = TEDAPI("test_password")

        # Now test the connect method directly
        api.din = None  # Reset for testing
        result = api.connect()

        assert result == "TEST_DIN"
        assert api.din == "TEST_DIN"
        mock_requests_get.assert_called_once_with(
            "https://192.168.91.1",
            verify=False,
            timeout=5
        )

    @patch('requests.get')
    @patch('pypowerwall.tedapi.TEDAPI.get_din')
    def test_connect_powerwall3(self, mock_get_din, mock_requests_get):
        """Test connection to Powerwall 3"""
        mock_requests_get.return_value.status_code = HTTPStatus.FORBIDDEN
        mock_get_din.return_value = "TEST_DIN"

        api = TEDAPI.__new__(TEDAPI)
        api.gw_ip = "192.168.91.1"
        api.gw_pwd = "test_password"
        api.timeout = 5
        api.pwcooldown = 0
        api.pwcache = {}
        api.pwcachetime = {}
        api.din = None
        api.pw3 = False

        result = api.connect()

        assert result == "TEST_DIN"
        assert api.pw3 is True

    @patch('requests.get')
    def test_connect_failure(self, mock_requests_get):
        """Test connection failure"""
        mock_requests_get.side_effect = Exception("Connection error")

        api = TEDAPI.__new__(TEDAPI)
        api.gw_ip = "192.168.91.1"
        api.gw_pwd = "test_password"
        api.timeout = 5
        api.pwcooldown = 0
        api.pwcache = {}
        api.pwcachetime = {}
        api.din = None
        api.pw3 = False

        result = api.connect()

        assert result is None
        assert api.din is None


class TestTEDAPIGetDIN:
    """Test get_din method"""

    @patch('requests.get')
    def test_get_din_success(self, mock_requests_get, mock_tedapi):
        """Test successful DIN retrieval"""
        mock_requests_get.return_value.status_code = HTTPStatus.OK
        mock_requests_get.return_value.text = "TEST_DIN_12345"

        # Clear cache to force API call
        mock_tedapi.pwcache.pop("din", None)
        mock_tedapi.pwcachetime.pop("din", None)

        result = mock_tedapi.get_din()

        assert result == "TEST_DIN_12345"
        assert mock_tedapi.pwcache["din"] == "TEST_DIN_12345"
        assert "din" in mock_tedapi.pwcachetime

    def test_get_din_cached(self, mock_tedapi_with_cache):
        """Test DIN retrieval from cache"""
        result = mock_tedapi_with_cache.get_din()

        assert result == "TEST_DIN"

    @patch('requests.get')
    def test_get_din_rate_limited(self, mock_requests_get, mock_tedapi):
        """Test DIN retrieval when rate limited"""
        mock_requests_get.return_value.status_code = HTTPStatus.TOO_MANY_REQUESTS

        # Clear cache to force API call
        mock_tedapi.pwcache.pop("din", None)
        mock_tedapi.pwcachetime.pop("din", None)

        result = mock_tedapi.get_din()

        assert result is None
        assert mock_tedapi.pwcooldown > time.perf_counter()

    @patch('requests.get')
    def test_get_din_forbidden(self, mock_requests_get, mock_tedapi):
        """Test DIN retrieval with forbidden response"""
        mock_requests_get.return_value.status_code = HTTPStatus.FORBIDDEN

        # Clear cache to force API call
        mock_tedapi.pwcache.pop("din", None)
        mock_tedapi.pwcachetime.pop("din", None)

        result = mock_tedapi.get_din()

        assert result is None


class TestTEDAPIGetConfig:
    """Test get_config method"""

    @patch('requests.post')
    def test_get_config_success(self, mock_requests_post):
        """Test successful config retrieval"""
        # Create mock response
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK

        # Create protobuf mock
        config_data = {
            "auto_meter_update": True,
            "battery_blocks": [],
            "vin": "1232100-00-E--TG11234567890"
        }

        # Mock the protobuf parsing
        with patch('pypowerwall.tedapi.tedapi_pb2.Message') as mock_pb:
            mock_pb_instance = Mock()
            mock_pb_instance.message.config.recv.file.text = json.dumps(config_data)
            mock_pb.return_value = mock_pb_instance
            mock_requests_post.return_value = mock_response

            api = TEDAPI.__new__(TEDAPI)
            api.gw_ip = "192.168.91.1"
            api.gw_pwd = "test_password"
            api.timeout = 5
            api.pwcooldown = 0
            api.pwcache = {}
            api.pwcachetime = {}
            api.din = "TEST_DIN"
            api.pwconfigexpire = 5

            result = api.get_config()

            assert result == config_data
            assert api.pwcache["config"] == config_data
            assert "config" in api.pwcachetime

    def test_get_config_cached(self):
        """Test config retrieval from cache"""
        cached_config = {"cached": True}

        api = TEDAPI.__new__(TEDAPI)
        api.pwcache = {"config": cached_config}
        api.pwcachetime = {"config": time.time()}
        api.pwconfigexpire = 5
        api.pwcooldown = 0
        api.timeout = 5

        result = api.get_config()

        assert result == cached_config

    @patch('pypowerwall.tedapi.TEDAPI.connect')
    def test_get_config_no_din(self, mock_connect):
        """Test config retrieval with no DIN"""
        mock_connect.return_value = None

        api = TEDAPI.__new__(TEDAPI)
        api.din = None
        api.pwcache = {}
        api.pwcachetime = {}
        api.pwcooldown = 0
        api.timeout = 5

        result = api.get_config()

        assert result is None


class TestTEDAPIGetStatus:
    """Test get_status method"""

    @patch('requests.post')
    def test_get_status_success(self, mock_requests_post):
        """Test successful status retrieval"""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK

        status_data = {
            "control": {
                "alerts": {},
                "batteryBlocks": [],
                "systemStatus": {
                    "nominalFullPackEnergyWh": 13500,
                    "nominalEnergyRemainingWh": 10000
                }
            }
        }

        with patch('pypowerwall.tedapi.tedapi_pb2.Message') as mock_pb:
            mock_pb_instance = Mock()
            mock_pb_instance.message.payload.recv.text = json.dumps(status_data)
            mock_pb.return_value = mock_pb_instance
            mock_requests_post.return_value = mock_response

            api = TEDAPI.__new__(TEDAPI)
            api.gw_ip = "192.168.91.1"
            api.gw_pwd = "test_password"
            api.timeout = 5
            api.pwcooldown = 0
            api.pwcache = {}
            api.pwcachetime = {}
            api.din = "TEST_DIN"
            api.pwcacheexpire = 5

            result = api.get_status()

            assert result == status_data
            assert api.pwcache["status"] == status_data

    @patch('requests.post')
    def test_get_status_json_error(self, mock_requests_post):
        """Test status retrieval with JSON decode error"""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK

        with patch('pypowerwall.tedapi.tedapi_pb2.Message') as mock_pb:
            mock_pb_instance = Mock()
            mock_pb_instance.message.payload.recv.text = "invalid json"
            mock_pb.return_value = mock_pb_instance
            mock_requests_post.return_value = mock_response

            api = TEDAPI.__new__(TEDAPI)
            api.gw_ip = "192.168.91.1"
            api.gw_pwd = "test_password"
            api.timeout = 5
            api.pwcooldown = 0
            api.pwcache = {}
            api.pwcachetime = {}
            api.din = "TEST_DIN"
            api.pwcacheexpire = 5

            result = api.get_status()

            assert result == {}


class TestTEDAPIBatteryMethods:
    """Test battery-related methods"""

    def test_battery_level_success(self, mock_tedapi_with_cache):
        """Test battery level calculation"""
        result = mock_tedapi_with_cache.battery_level()
        assert result == pytest.approx(74.07, rel=0.01)

    def test_battery_level_missing_data(self, mock_tedapi):
        """Test battery level with missing data"""
        mock_tedapi.pwcache = {"status": {}}
        mock_tedapi.pwcachetime = {"status": time.time()}

        result = mock_tedapi.battery_level()
        assert result is None

    def test_backup_time_remaining_success(self, mock_tedapi):
        """Test backup time remaining calculation"""
        mock_tedapi.pwcache = {
            "status": {
                "control": {
                    "systemStatus": {
                        "nominalEnergyRemainingWh": 10000
                    },
                    "meterAggregates": [
                        {"location": "LOAD", "realPowerW": 1000}
                    ]
                }
            }
        }
        mock_tedapi.pwcachetime = {"status": time.time()}

        result = mock_tedapi.backup_time_remaining()
        assert result == 10.0

    def test_current_power_single_location(self, mock_tedapi):
        """Test current power for single location"""
        mock_tedapi.pwcache = {
            "status": {
                "control": {
                    "meterAggregates": [
                        {"location": "LOAD", "realPowerW": 1500},
                        {"location": "SOLAR", "realPowerW": 3000},
                        {"location": "BATTERY", "realPowerW": -500}
                    ]
                }
            }
        }
        mock_tedapi.pwcachetime = {"status": time.time()}

        assert mock_tedapi.current_power("LOAD") == 1500
        assert mock_tedapi.current_power("SOLAR") == 3000
        assert mock_tedapi.current_power("BATTERY") == -500

    def test_current_power_all_locations(self, mock_tedapi):
        """Test current power for all locations"""
        mock_tedapi.pwcache = {
            "status": {
                "control": {
                    "meterAggregates": [
                        {"location": "LOAD", "realPowerW": 1500},
                        {"location": "SOLAR", "realPowerW": 3000}
                    ]
                }
            }
        }
        mock_tedapi.pwcachetime = {"status": time.time()}

        result = mock_tedapi.current_power()
        assert result == {"LOAD": 1500, "SOLAR": 3000}


class TestTEDAPIFirmwareVersion:
    """Test firmware version methods"""

    @patch('requests.post')
    def test_get_firmware_version_simple(self, mock_requests_post):
        """Test simple firmware version retrieval"""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK

        with patch('pypowerwall.tedapi.tedapi_pb2.Message') as mock_pb:
            mock_pb_instance = Mock()
            mock_pb_instance.message.firmware.system.version.text = "1.2.3"
            mock_pb.return_value = mock_pb_instance
            mock_requests_post.return_value = mock_response

            api = TEDAPI.__new__(TEDAPI)
            api.gw_ip = "192.168.91.1"
            api.gw_pwd = "test_password"
            api.timeout = 5
            api.pwcooldown = 0
            api.pwcache = {}
            api.pwcachetime = {}
            api.din = "TEST_DIN"
            api.pwcacheexpire = 5

            result = api.get_firmware_version()

            assert result == "1.2.3"

    @patch('requests.post')
    def test_get_firmware_version_details(self, mock_requests_post):
        """Test detailed firmware version retrieval"""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK

        with patch('pypowerwall.tedapi.tedapi_pb2.Message') as mock_pb:
            mock_pb_instance = Mock()
            tedapi_msg = mock_pb_instance.message.firmware.system
            tedapi_msg.version.text = "1.2.3"
            tedapi_msg.version.githash = "abc123"
            tedapi_msg.gateway.partNumber = "PART123"
            tedapi_msg.gateway.serialNumber = "SERIAL123"
            tedapi_msg.din = "TEST_DIN"
            tedapi_msg.five = "five_value"
            tedapi_msg.six = "six_value"

            # Mock wireless devices
            device = Mock()
            device.company.value = "Tesla"
            device.model.value = "Model X"
            device.fcc_id.value = "FCC123"
            device.ic.value = "IC123"
            tedapi_msg.wireless.device = [device]

            mock_pb.return_value = mock_pb_instance
            mock_requests_post.return_value = mock_response

            api = TEDAPI.__new__(TEDAPI)
            api.gw_ip = "192.168.91.1"
            api.gw_pwd = "test_password"
            api.timeout = 5
            api.pwcooldown = 0
            api.pwcache = {}
            api.pwcachetime = {}
            api.din = "TEST_DIN"
            api.pwcacheexpire = 5

            result = api.get_firmware_version(details=True)

            assert result["system"]["version"]["text"] == "1.2.3"
            assert result["system"]["gateway"]["partNumber"] == "PART123"
            assert len(result["system"]["wireless"]["device"]) == 1


class TestTEDAPIComponents:
    """Test component-related methods"""

    @patch('requests.post')
    def test_get_components_success(self, mock_requests_post):
        """Test successful components retrieval"""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK

        components_data = {
            "pw3Can": {"firmwareUpdate": {"isUpdating": False}},
            "components": {
                "pws": [],
                "pch": [],
                "bms": []
            }
        }

        with patch('pypowerwall.tedapi.tedapi_pb2.Message') as mock_pb:
            mock_pb_instance = Mock()
            mock_pb_instance.message.payload.recv.text = json.dumps(components_data)
            mock_pb.return_value = mock_pb_instance
            mock_requests_post.return_value = mock_response

            api = TEDAPI.__new__(TEDAPI)
            api.gw_ip = "192.168.91.1"
            api.gw_pwd = "test_password"
            api.timeout = 5
            api.pwcooldown = 0
            api.pwcache = {}
            api.pwcachetime = {}
            api.din = "TEST_DIN"
            api.pwconfigexpire = 5

            result = api.get_components()

            assert result == components_data

    def test_get_battery_blocks(self):
        """Test battery blocks retrieval"""
        api = TEDAPI.__new__(TEDAPI)
        api.pwcache = {
            "config": {
                "battery_blocks": [
                    {"vin": "BLOCK1", "type": "Powerwall3"},
                    {"vin": "BLOCK2", "type": "Powerwall2"}
                ]
            }
        }
        api.pwcachetime = {"config": time.time()}
        api.pwconfigexpire = 5
        api.pwcooldown = 0
        api.timeout = 5

        result = api.get_battery_blocks()

        assert len(result) == 2
        assert result[0]["vin"] == "BLOCK1"


class TestTEDAPIFanSpeeds:
    """Test fan speed methods"""

    def test_extract_fan_speeds(self):
        """Test fan speed extraction"""
        api = TEDAPI.__new__(TEDAPI)

        data = {
            "components": {
                "msa": [
                    {
                        "partNumber": "PART1",
                        "serialNumber": "SERIAL1",
                        "signals": [
                            {"name": "PVAC_Fan_Speed_Actual_RPM", "value": 2000},
                            {"name": "PVAC_Fan_Speed_Target_RPM", "value": 2100},
                            {"name": "OTHER_SIGNAL", "value": 123}
                        ]
                    },
                    {
                        "partNumber": "PART2",
                        "serialNumber": "SERIAL2",
                        "signals": [
                            {"name": "PVAC_Fan_Speed_Actual_RPM", "value": 1800}
                        ]
                    }
                ]
            }
        }

        result = api.extract_fan_speeds(data)

        assert "PVAC--PART1--SERIAL1" in result
        assert result["PVAC--PART1--SERIAL1"]["PVAC_Fan_Speed_Actual_RPM"] == 2000
        assert result["PVAC--PART1--SERIAL1"]["PVAC_Fan_Speed_Target_RPM"] == 2100
        assert "PVAC--PART2--SERIAL2" in result
        assert len(result["PVAC--PART2--SERIAL2"]) == 1

    def test_get_fan_speeds(self):
        """Test get_fan_speeds wrapper"""
        api = TEDAPI.__new__(TEDAPI)

        mock_controller_data = {
            "components": {
                "msa": [
                    {
                        "partNumber": "PART1",
                        "serialNumber": "SERIAL1",
                        "signals": [
                            {"name": "PVAC_Fan_Speed_Actual_RPM", "value": 2000}
                        ]
                    }
                ]
            }
        }

        with patch.object(api, 'get_device_controller', return_value=mock_controller_data):
            result = api.get_fan_speeds()

        assert "PVAC--PART1--SERIAL1" in result


class TestTEDAPIVitals:
    """Test vitals method"""

    def test_vitals_basic(self):
        """Test basic vitals generation"""
        api = TEDAPI.__new__(TEDAPI)
        api.gw_ip = "192.168.91.1"
        api.pw3 = False

        # Mock data
        config_data = {
            "vin": "1232100-00-E--TG11234567890",
            "meters": [],
            "solars": []
        }

        status_data = {
            "control": {
                "alerts": {"active": []},
                "systemStatus": {}
            },
            "esCan": {
                "bus": {
                    "PVAC": [],
                    "PVS": [],
                    "THC": [],
                    "POD": [],
                    "PINV": [],
                    "SYNC": {},
                    "ISLANDER": {}
                }
            },
            "components": {"msa": []},
            "neurio": {"readings": []}
        }

        with patch.object(api, 'get_config', return_value=config_data):
            with patch.object(api, 'get_device_controller', return_value=status_data):
                with patch.object(api, 'get_pw3_vitals', return_value={}):
                    result = api.vitals()

        assert "VITALS" in result
        assert result["VITALS"]["gateway"] == "192.168.91.1"
        assert f"STSTSM--{config_data['vin']}" in result


class TestTEDAPIRateLimiting:
    """Test rate limiting functionality"""

    def test_cooldown_prevents_api_calls(self):
        """Test that cooldown prevents API calls"""
        api = TEDAPI.__new__(TEDAPI)
        api.pwcooldown = time.perf_counter() + 300  # 5 minutes in future
        api.pwcache = {}
        api.pwcachetime = {}
        api.timeout = 5

        result = api.get_din()
        assert result is None

        result = api.get_config()
        assert result is None

        result = api.get_status()
        assert result is None


class TestTEDAPIEdgeCases:
    """Test edge cases and error handling"""

    def test_set_debug_color(self):
        """Test debug mode with color"""
        api = TEDAPI.__new__(TEDAPI)

        with patch('logging.basicConfig') as mock_basic_config:
            api.set_debug(True, color=True)
            mock_basic_config.assert_called_once()

    def test_set_debug_no_color(self):
        """Test debug mode without color"""
        api = TEDAPI.__new__(TEDAPI)

        with patch('logging.basicConfig') as mock_basic_config:
            api.set_debug(True, color=False)
            mock_basic_config.assert_called_once()

    def test_set_debug_off(self):
        """Test turning debug mode off"""
        api = TEDAPI.__new__(TEDAPI)

        with patch('pypowerwall.tedapi.log.setLevel') as mock_set_level:
            api.set_debug(False)
            mock_set_level.assert_called_once()

    @patch('requests.post')
    def test_network_timeout(self, mock_requests_post):
        """Test network timeout handling"""
        mock_requests_post.side_effect = requests.Timeout()

        api = TEDAPI.__new__(TEDAPI)
        api.gw_ip = "192.168.91.1"
        api.gw_pwd = "test_password"
        api.timeout = 5
        api.pwcooldown = 0
        api.pwcache = {}
        api.pwcachetime = {}
        api.din = "TEST_DIN"

        result = api.get_status()
        assert result is None


class TestTEDAPIPowerwall3:
    """Test Powerwall 3 specific methods"""

    @patch('requests.post')
    def test_get_pw3_vitals_success(self, mock_requests_post):
        """Test successful PW3 vitals retrieval"""
        mock_response = Mock()
        mock_response.status_code = HTTPStatus.OK

        # Mock config data
        config_data = {
            "battery_blocks": [
                {
                    "vin": "1707000-11-J--TG12xxxxxx3A8Z",
                    "type": "Powerwall3"
                }
            ]
        }
