
import json
import unittest
from contextlib import contextmanager
from io import BytesIO
from unittest.mock import Mock, patch

from proxy.server import Handler

class UnittestHandler(Handler):
    """A testable version of Handler that doesn't auto-handle requests"""

    def __init__(self):
        # Skip the parent __init__ to avoid automatic handling
        # Instead, set up the minimal attributes needed for testing
        self.path = ""
        self.send_response = Mock()
        self.send_header = Mock()
        self.end_headers = Mock()
        self.wfile = BytesIO()
        self.rfile = BytesIO()
        self.headers = {}
        self.client_address = ('127.0.0.1', 12345)
        self.server = Mock()
        self.request_version = 'HTTP/1.1'
        self.command = 'GET'


def common_patches(func):
    """Decorator to apply common patches to test methods"""
    @patch('proxy.server.api_base_url', '')
    @patch('proxy.server.proxystats', {
        'gets': 0, 'posts': 0, 'errors': 0, 'timeout': 0,
        'uri': {}, 'start': 1000, 'clear': 0
    })
    @patch('proxy.server.proxystats_lock')
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


@contextmanager
def standard_test_patches():
    """Context manager for standard test patches"""
    with patch('proxy.server.proxystats_lock'), \
         patch('proxy.server.proxystats', {
             'gets': 0, 'posts': 0, 'errors': 0, 'timeout': 0,
             'uri': {}, 'start': 1000, 'clear': 0
         }), \
         patch('proxy.server.api_base_url', ''):
        yield

class BaseDoGetTest(unittest.TestCase):
    """Base test class with common setup and helper methods"""

    def setUp(self):
        """Common setup for all test cases"""
        # Use our testable handler
        self.handler = UnittestHandler()

        # Mock wfile.write for easier testing
        self.handler.wfile = Mock()
        self.handler.wfile.write = Mock()

    def get_written_json(self):
        """Helper to extract and parse JSON from written response"""
        written_data = self.handler.wfile.write.call_args[0][0]
        return json.loads(written_data.decode('utf8'))

    def get_written_text(self):
        """Helper to extract text from written response"""
        written_data = self.handler.wfile.write.call_args[0][0]
        return written_data.decode('utf8')

    def assert_json_response(self, expected_key, expected_value):
        """Helper to assert JSON response contains expected key-value"""
        result = self.get_written_json()
        self.assertIn(expected_key, result)
        self.assertEqual(result[expected_key], expected_value)

class TestDoGetStatsEndpoints(BaseDoGetTest):
    """Test cases for stats-related endpoints"""

    def test_stats_endpoint(self):
        """Test /stats endpoint - using context manager approach"""
        with standard_test_patches(), \
             patch('proxy.server.safe_pw_call') as mock_safe_call, \
             patch('proxy.server.resource') as mock_resource, \
             patch('proxy.server.time') as mock_time, \
             patch('proxy.server.pw') as mock_pw, \
             patch('proxy.server.health_check_enabled', False):

            self.handler.path = "/stats"
            mock_time.time.return_value = 2000
            mock_resource.getrusage.return_value = Mock(ru_maxrss=1024)
            mock_safe_call.return_value = "Test Site"
            mock_pw.cloudmode = False
            mock_pw.fleetapi = False

            self.handler.do_GET()

            result = self.get_written_json()
            self.assertEqual(result["ts"], 2000)
            self.assertEqual(result["mem"], 1024)

    def test_stats_clear_endpoint(self):
        """Test /stats/clear endpoint - using context manager with custom proxystats"""
        with patch('proxy.server.proxystats_lock'), \
             patch('proxy.server.proxystats', {'gets': 10, 'errors': 2, 'uri': {'/test': 5}, 'clear': 0}) as mock_stats, \
             patch('proxy.server.api_base_url', ''), \
             patch('proxy.server.time') as mock_time:

            self.handler.path = "/stats/clear"
            mock_time.time.return_value = 3000

            self.handler.do_GET()

            # Check that stats were cleared
            self.assertEqual(mock_stats["gets"], 1)
            self.assertEqual(mock_stats["errors"], 0)
            self.assertEqual(mock_stats["uri"], {'/stats/clear': 1})
            self.assertEqual(mock_stats["clear"], 3000)
