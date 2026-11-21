from datetime import date
from unittest.mock import MagicMock

from odoo.tests.common import BaseCase

from .....services.soap.nordea_corporate_access.constants.nordea_ws import FILE_TYPE_PAIN_002, FileStatus
from .....services.soap.nordea_corporate_access.nordea_ca_pis import NordeaCAPIS


class TestNordeaCAPISStatusFiles(BaseCase):
    def setUp(self):
        super().setUp()
        self.pis = NordeaCAPIS()
        self.pis._download_file_list = MagicMock()
        self.pis._download_file = MagicMock()

    def test_lists_and_downloads_new_pain002_files(self):
        descriptors = [
            {"file_reference": "REF001", "file_type": FILE_TYPE_PAIN_002},
            {"file_reference": "REF002", "file_type": FILE_TYPE_PAIN_002},
        ]
        responses = [object(), object()]
        self.pis._download_file_list.return_value = descriptors
        self.pis._download_file.side_effect = responses

        result = self.pis.download_payment_status_files(
            date(2026, 10, 1),
            date(2026, 10, 2),
        )

        self.pis._download_file_list.assert_called_once_with(
            date(2026, 10, 1),
            date(2026, 10, 2),
            file_type=FILE_TYPE_PAIN_002,
            status=FileStatus.NEW,
        )
        self.assertEqual(
            self.pis._download_file.call_args_list[0].args,
            ("REF001",),
        )
        self.assertEqual(
            self.pis._download_file.call_args_list[1].args,
            ("REF002",),
        )
        self.assertEqual(
            result,
            [
                {"descriptor": descriptors[0], "response": responses[0]},
                {"descriptor": descriptors[1], "response": responses[1]},
            ],
        )

    def test_returns_empty_list_when_no_files_are_available(self):
        self.pis._download_file_list.return_value = []

        self.assertEqual(self.pis.download_payment_status_files(), [])
        self.pis._download_file.assert_not_called()