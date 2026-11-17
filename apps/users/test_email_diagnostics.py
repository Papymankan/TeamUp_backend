import json
import os
import ssl
import tempfile
from io import StringIO
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


@override_settings(
    EMAIL_HOST_USER="diagnostic-user-secret",
    EMAIL_HOST_PASSWORD="diagnostic-password-secret",
)
class SmtpTlsDiagnosticTests(SimpleTestCase):
    def test_reports_ca_paths_and_probes_starttls_without_authentication(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ca_file = os.path.join(temp_dir, "ca.pem")
            with open(ca_file, "w", encoding="ascii") as bundle:
                bundle.write("test bundle")

            ca_directory = os.path.join(temp_dir, "certs")
            os.mkdir(ca_directory)
            verify_paths = ssl.DefaultVerifyPaths(
                cafile=ca_file,
                capath=ca_directory,
                openssl_cafile_env="SSL_CERT_FILE",
                openssl_cafile=ca_file,
                openssl_capath_env="SSL_CERT_DIR",
                openssl_capath=ca_directory,
            )
            context = MagicMock()
            context.cert_store_stats.return_value = {"x509_ca": 12}
            smtp = MagicMock()

            with (
                patch(
                    "apps.users.management.commands.diagnose_smtp_tls.ssl.get_default_verify_paths",
                    return_value=verify_paths,
                ),
                patch(
                    "apps.users.management.commands.diagnose_smtp_tls.ssl.create_default_context",
                    return_value=context,
                ),
                patch(
                    "apps.users.management.commands.diagnose_smtp_tls.smtplib.SMTP",
                    return_value=smtp,
                ) as smtp_constructor,
            ):
                with patch.dict(
                    os.environ,
                    {
                        "SSL_CERT_FILE": ca_file,
                        "SSL_CERT_DIR": ca_directory,
                    },
                ):
                    stdout = StringIO()
                    call_command("diagnose_smtp_tls", stdout=stdout)

        report, result = [
            json.loads(line) for line in stdout.getvalue().splitlines()
        ]
        self.assertTrue(report["ca_file"]["effective"]["exists"])
        self.assertTrue(report["ca_file"]["effective"]["readable"])
        self.assertTrue(report["ca_directory"]["effective"]["exists"])
        self.assertTrue(report["ca_directory"]["effective"]["readable"])
        self.assertEqual(
            report["ca_file"]["environment_override"],
            {"configured": True, "exists": True, "readable": True},
        )
        self.assertEqual(
            report["ca_directory"]["environment_override"],
            {"configured": True, "exists": True, "readable": True},
        )
        self.assertEqual(report["cert_store_stats"], {"x509_ca": 12})
        self.assertEqual(result, {"gmail_starttls": "verified"})
        smtp_constructor.assert_called_once_with(
            settings.EMAIL_HOST,
            settings.EMAIL_PORT,
            timeout=15,
        )
        smtp.ehlo.assert_called_once_with()
        smtp.starttls.assert_called_once_with(context=context)
        smtp.close.assert_called_once_with()
        smtp.login.assert_not_called()
        self.assertNotIn("diagnostic-user-secret", stdout.getvalue())
        self.assertNotIn("diagnostic-password-secret", stdout.getvalue())

    def test_reports_exact_certificate_verification_error_without_secrets(self):
        verification_error = ssl.SSLCertVerificationError(
            20,
            "unable to get local issuer certificate",
        )
        verification_error.verify_code = 20
        verification_error.verify_message = "unable to get local issuer certificate"
        smtp = MagicMock()
        smtp.starttls.side_effect = verification_error
        context = MagicMock()
        context.cert_store_stats.return_value = {"x509_ca": 0}

        with (
            patch(
                "apps.users.management.commands.diagnose_smtp_tls.ssl.create_default_context",
                return_value=context,
            ),
            patch(
                "apps.users.management.commands.diagnose_smtp_tls.smtplib.SMTP",
                return_value=smtp,
            ),
        ):
            stdout = StringIO()
            stderr = StringIO()
            call_command(
                "diagnose_smtp_tls",
                stdout=stdout,
                stderr=stderr,
            )
        result = json.loads(stderr.getvalue())
        self.assertEqual(
            result,
            {
                "gmail_starttls": "certificate_verification_failed",
                "verify_code": verification_error.verify_code,
                "verify_message": verification_error.verify_message,
            },
        )
        self.assertNotIn(
            "diagnostic-user-secret",
            stdout.getvalue() + stderr.getvalue(),
        )
        self.assertNotIn(
            "diagnostic-password-secret",
            stdout.getvalue() + stderr.getvalue(),
        )
        smtp.login.assert_not_called()
        smtp.close.assert_called_once_with()
