import os
import runpy
from pathlib import Path
from unittest.mock import patch

import certifi
from django.test import SimpleTestCase


SETTINGS_PATH = Path(__file__).resolve().parents[2] / "config" / "settings.py"


class SslCertificateConfigurationTests(SimpleTestCase):
    def run_settings_with_environment(self, environment):
        with patch.dict(
            os.environ,
            {"DJANGO_SECRET_KEY": "test-secret-key", **environment},
            clear=True,
        ):
            with patch("dotenv.load_dotenv"):
                runpy.run_path(str(SETTINGS_PATH))
            return os.environ["SSL_CERT_FILE"]

    def test_defaults_ssl_cert_file_to_certifi_bundle(self):
        configured_path = self.run_settings_with_environment({})

        self.assertEqual(configured_path, certifi.where())

    def test_respects_existing_ssl_cert_file_override(self):
        custom_path = "C:\\custom\\certificates.pem"

        configured_path = self.run_settings_with_environment(
            {"SSL_CERT_FILE": custom_path}
        )

        self.assertEqual(configured_path, custom_path)
