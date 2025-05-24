# import pytest
# from unittest.mock import MagicMock, patch, call

# @pytest.fixture(autouse=True)
# def patch_all(monkeypatch):
#     # Patch log, lookup, and all external globals
#     log = MagicMock()
#     monkeypatch.setattr("your_module.log", log)
#     # General fallback lookup, but also allows for TypeError cases
#     def lookup(obj, path):
#         try:
#             for k in path:
#                 if isinstance(obj, dict):
#                     obj = obj.get(k)
#                 else:
#                     return None
#             return obj
#         except Exception:
#             return None
#     monkeypatch.setattr("your_module.lookup", lookup)
#     monkeypatch.setattr("your_module.compute_LL_voltage", lambda *a, **k: 241)
#     monkeypatch.setattr("your_module.API_METERS_AGGREGATES_STUB", {
#         'site': {}, 'battery': {}, 'load': {}, 'solar': {}
#     })
#     monkeypatch.setattr("your_module.API_SYSTEM_STATUS_STUB", {})

# @pytest.fixture
# def mock_tedapi():
#     tedapi = MagicMock()
#     tedapi.connect.return_value = True
#     tedapi.get_config.return_value = {
#         'vin': 'VIN1234',
#         'site_info': {
#             'battery_commission_date': '2021-01-01',
#             'site_name': 'MockSite',
#             'timezone': 'America/New_York',
#             'backup_reserve_percent': 42,
#             'country': 'USA',
#             'state': 'Ohio',
#             'utility': 'MOCKPOWER',
#         },
#         'firmware_version': '2025.1.1',
#         'default_real_mode': 'self_consumption',
#         'grid_code': '60Hz_240V_s_UL1741SA',
#         'max_site_meter_power_ac': 99999,
#         'min_site_meter_power_ac': -99999,
#         'nominal_system_energy_ac': 88.8,
#         'nominal_system_power_ac': 11.1,
#         'panel_max_current': 101,
#         'tariff_content': {},
#         "country": "USA",
#         "state": "Ohio",
#         "utility": "MOCKPOWER",
#         "site_name": "MockSite",
#         "timezone": "America/New_York",
#         "control": {"batteryBlocks": [{}]},
#     }
#     tedapi.get_firmware_version.return_value = "2025.1.1"
#     tedapi.get_status.return_value = {
#         "control": {"alerts": {"active": ["SystemConnectedToGrid"]}, "systemStatus": {
#             "nominalFullPackEnergyWh": 41000, "nominalEnergyRemainingWh": 23500
#         }},
#         "system": {"time": 111111},
#         "esCan": {
#             "bus": {
#                 "ISLANDER": {
#                     "ISLAND_AcMeasurements": {
#                         "ISLAND_VL1N_Main": 120,
#                         "ISLAND_VL2N_Main": 120,
#                         "ISLAND_VL3N_Main": 0
#                     },
#                     "ISLAND_GridConnection": {
#                         "ISLAND_GridConnected": "ISLAND_GridConnected_Connected"
#                     }
#                 },
#                 "SYNC": {
#                     "METER_X_AcMeasurements": {
#                         "METER_X_CTA_I": 3,
#                         "METER_X_CTB_I": 2,
#                         "METER_X_CTC_I": 1
#                     },
#                     "METER_Y_AcMeasurements": {
#                         "METER_Y_CTA_I": 6,
#                         "METER_Y_CTB_I": 7,
#                         "METER_Y_CTC_I": 8
#                     }
#                 }
#             }
#         },
#         "PVS": [{"PVS_Status": {"PVS_vLL": 450}}],
#         "PINV": [{"PINV_Status": {"PINV_Vout": 370}}]
#     }
#     # Provide full mapping for each current_power location
#     tedapi.current_power.side_effect = lambda force=False, location=None: {
#         'solar': 10000, 'battery': -1500, 'load': 8000, 'site': 500
#     }[location]
#     tedapi.battery_level.return_value = 85.4
#     tedapi.backup_time_remaining.return_value = 2.3
#     tedapi.get_blocks.return_value = {'block1': {'bkinfo': 'foo'}}
#     tedapi.vitals.return_value = {'vital_info': 'ok'}
#     return tedapi

# @pytest.fixture
# def cls(monkeypatch, mock_tedapi):
#     monkeypatch.setattr("your_module.TEDAPI", lambda *a, **k: mock_tedapi)
#     from your_module import PyPowerwallTEDAPI
#     return PyPowerwallTEDAPI

# @pytest.fixture
# def obj(cls):
#     return cls("pw", debug=True, pwcacheexpire=2, timeout=3, pwconfigexpire=4, host="test.host")

# def test_init_all_fields(cls, mock_tedapi):
#     o = cls("pw", host="1.2.3.4", debug=False)
#     assert o.tedapi is mock_tedapi
#     assert o.host == "1.2.3.4"
#     assert o.gw_pwd == "pw"
#     assert o.debug is False
#     assert isinstance(o.poll_api_map, dict)
#     assert isinstance(o.post_api_map, dict)
#     assert o.auth == {'AuthCookie': 'local', 'UserRecord': 'local'}

# def test_init_fails(monkeypatch):
#     fake = MagicMock()
#     fake.connect.return_value = False
#     monkeypatch.setattr("your_module.TEDAPI", lambda *a, **k: fake)
#     from your_module import PyPowerwallTEDAPI
#     with pytest.raises(ConnectionError):
#         PyPowerwallTEDAPI("bad", host="fail")

# def test_init_poll_api_map(obj):
#     m = obj.init_poll_api_map()
#     assert "/api/status" in m
#     assert "/api/devices/vitals" in m
#     assert callable(m["/api/status"])

# def test_init_post_api_map(obj):
#     m = obj.init_post_api_map()
#     assert "/api/operation" in m
#     assert callable(m["/api/operation"])

# def test_authenticate_success(obj):
#     with patch.object(obj, "connect", return_value=True):
#         obj.authenticate()  # Should not raise

# def test_authenticate_failure(obj):
#     with patch.object(obj, "connect", return_value=False):
#         with pytest.raises(ConnectionError):
#             obj.authenticate()

# def test_connect(obj):
#     with patch.object(obj.tedapi, "connect", return_value="mockret") as c:
#         assert obj.connect() == "mockret"
#         c.assert_called_once()

# def test_poll_known_and_unknown(obj):
#     obj.poll_api_map["/api/test"] = MagicMock(return_value="pass")
#     assert obj.poll("/api/test", force=True, recursive=True, raw=True) == "pass"
#     err = obj.poll("/api/doesnotexist")
#     assert "Unknown API" in err["ERROR"]

# def test_post_known_and_unknown(obj):
#     obj.post_api_map["/api/test"] = MagicMock(return_value="resp")
#     with patch.object(obj.__class__, "_invalidate_cache") as inv:
#         assert obj.post("/api/test", {"foo": 1}, None) == "resp"
#         inv.assert_called_once()
#     # Not present
#     ret = obj.post("/api/missing", {"x": 2}, None)
#     assert "Unknown API" in ret["ERROR"]

# def test_getsites_and_change_site(obj):
#     assert obj.getsites() is None
#     assert obj.change_site("mysiteid") is False

# def test_get_site_info(obj):
#     assert isinstance(obj.get_site_info(), dict)

# def test_get_live_status(obj):
#     assert obj.get_live_status() == obj.tedapi.get_status()

# def test_get_time_remaining(obj):
#     assert obj.get_time_remaining() == obj.tedapi.backup_time_remaining()

# def test_get_api_system_status_soe(obj):
#     ret = obj.get_api_system_status_soe()
#     assert ret["percentage"] == 85.4
#     # test no percentage (returns None)
#     obj.tedapi.battery_level.return_value = None
#     assert obj.get_api_system_status_soe() is None

# def test_get_api_status_and_extract_grid_status(obj):
#     val = obj.get_api_status()
#     assert val["din"] == 'VIN1234'
#     # test None config
#     obj.tedapi.get_config.return_value = None
#     assert obj.get_api_status() is None
#     # grid status
#     s = {"control": {"alerts": {"active": ["SystemConnectedToGrid"]}}}
#     assert obj.extract_grid_status(s) == "SystemGridConnected"
#     # grid_state branch
#     stat = {
#         "control": {"alerts": {"active": []}},
#         "esCan": {"bus": {"ISLANDER": {"ISLAND_GridConnection": {"ISLAND_GridConnected": "ISLAND_GridConnected_Connected"}}}}
#     }
#     assert obj.extract_grid_status(stat) == "SystemGridConnected"
#     # None branch
#     s = {"control": {"alerts": {"active": []}}}
#     assert obj.extract_grid_status(s) is None
#     # unknown value
#     stat["esCan"]["bus"]["ISLANDER"]["ISLAND_GridConnection"]["ISLAND_GridConnected"] = "other"
#     assert obj.extract_grid_status(stat) == "SystemIslandedActive"

# def test_get_api_system_status_grid_status(obj):
#     val = obj.get_api_system_status_grid_status()
#     assert val["grid_status"] in ("SystemGridConnected", "SystemIslandedActive", None)

# def test_get_api_site_info_site_name(obj):
#     r = obj.get_api_site_info_site_name()
#     assert r["site_name"] == "MockSite"
#     assert "timezone" in r

# def test_get_api_site_info(obj):
#     r = obj.get_api_site_info()
#     assert r["site_name"] == "MockSite"
#     assert r["max_system_energy_kWh"] == 88.8
#     # Test not dict
#     obj.tedapi.get_config.return_value = "notadict"
#     assert obj.get_api_site_info() is None

# def test_get_api_devices_vitals(obj):
#     with patch("your_module.log.warning") as warn:
#         assert obj.get_api_devices_vitals(force=True) is None
#         warn.assert_called()

# def test_get_vitals(obj):
#     assert obj.get_vitals(force=True) == {'vital_info': 'ok'}

# def test_get_api_meters_aggregates(obj):
#     val = obj.get_api_meters_aggregates(force=True)
#     assert "site" in val and "battery" in val and "solar" in val and "load" in val
#     # test config or status is not dict (returns None)
#     obj.tedapi.get_config.return_value = "nodict"
#     assert obj.get_api_meters_aggregates() is None
#     obj.tedapi.get_config.return_value = {'vin': 'VIN1234', 'site_info': {}}
#     obj.tedapi.get_status.return_value = "nope"
#     assert obj.get_api_meters_aggregates() is None

# def test_get_api_operation(obj):
#     out = obj.get_api_operation(force=True)
#     assert out["real_mode"] == "self_consumption"
#     assert out["backup_reserve_percent"] == 42
#     # not dict config
#     obj.tedapi.get_config.return_value = []
#     assert obj.get_api_operation() is None

# def test_get_api_system_status(obj):
#     r = obj.get_api_system_status(force=True)
#     assert isinstance(r, dict)
#     assert "nominal_full_pack_energy" in r
#     # status or config not dict
#     obj.tedapi.get_status.return_value = []
#     assert obj.get_api_system_status() is None
#     obj.tedapi.get_status.return_value = {"control": {"alerts": {"active": ["SystemConnectedToGrid"]}}}
#     obj.tedapi.get_config.return_value = []
#     assert obj.get_api_system_status() is None

# def test_api_maps_call_all(obj):
#     # Ensure each map entry is callable
#     for k, func in obj.init_poll_api_map().items():
#         if "unimplemented" in func.__name__ or "timeout" in func.__name__:
#             continue
#         try:
#             func()
#         except Exception:
#             pass
#     for k, func in obj.init_post_api_map().items():
#         try:
#             func(payload={}, din=None)
#         except Exception:
#             pass

# def test_all_unimplemented_endpoints(obj):
#     # Add dummy implementations for all "unimplemented" style endpoints
#     if hasattr(obj, "get_api_unimplemented_timeout"):
#         with pytest.raises(Exception):
#             obj.get_api_unimplemented_timeout()
#     if hasattr(obj, "get_unimplemented_api"):
#         with pytest.raises(Exception):
#             obj.get_unimplemented_api()

# def test_post_invalidate_cache(obj):
#     obj.post_api_map["/api/op"] = MagicMock(return_value=True)
#     with patch.object(obj.__class__, "_invalidate_cache") as inv:
#         assert obj.post("/api/op", {}, None)
#         inv.assert_called_once()

# def test_post_no_result(obj):
#     # post returns None from func
#     obj.post_api_map["/api/operation"] = MagicMock(return_value=None)
#     with patch.object(obj.__class__, "_invalidate_cache") as inv:
#         assert obj.post("/api/operation", {}, None) is None
#         inv.assert_not_called()

# def test_poll_kwargs(obj):
#     # test poll with all kwargs
#     f = MagicMock(return_value="rv")
#     obj.poll_api_map["/api/withkwargs"] = f
#     assert obj.poll("/api/withkwargs", force=True, recursive=True, raw=True) == "rv"
#     f.assert_called_with(force=True, recursive=True, raw=True)
