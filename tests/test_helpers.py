import unittest
from unittest.mock import patch, MagicMock
from app.modules.helpers import Helpers


class TestHelpers(unittest.TestCase):
    @patch("app.modules.helpers.InitNornir")
    def test_nornir_driver_sql(self, mock_init_nornir):
        mock_nr = MagicMock()
        mock_init_nornir.return_value = mock_nr
        helpers = Helpers(conn_timeout=30)
        nr = helpers.nornir_driver_sql()
        self.assertEqual(nr, mock_nr)
        # Проверяем, что в inventory передан SQLInventoryCrypto
        call_args = mock_init_nornir.call_args[1]
        self.assertEqual(call_args["inventory"]["plugin"], "SQLInventoryCrypto")
