import json
import os
import smtplib
import ssl

from django.conf import settings
from django.core.management.base import BaseCommand


def _path_status(path, is_directory, include_path=True):
    if not path:
        status = {"exists": False, "readable": False}
        if include_path:
            status["path"] = path
        return status

    exists = os.path.isdir(path) if is_directory else os.path.isfile(path)
    status = {
        "exists": exists,
        "readable": exists and os.access(path, os.R_OK),
    }
    if include_path:
        status["path"] = path
    return status


def _environment_path_status(variable_name, is_directory):
    path = os.environ.get(variable_name) if variable_name else None
    return {
        "configured": bool(path),
        **_path_status(path, is_directory, include_path=False),
    }


class Command(BaseCommand):
    help = "Report CA trust configuration and probe Gmail STARTTLS without logging in."

    def handle(self, *args, **options):
        verify_paths = ssl.get_default_verify_paths()
        context = ssl.create_default_context()
        self.stdout.write(
            json.dumps(
                {
                    "default_verify_paths": verify_paths._asdict(),
                    "ca_file": {
                        "effective": _path_status(verify_paths.cafile, False),
                        "environment_override": _environment_path_status(
                            verify_paths.openssl_cafile_env,
                            False,
                        ),
                        "compiled_default": _path_status(
                            verify_paths.openssl_cafile,
                            False,
                        ),
                    },
                    "ca_directory": {
                        "effective": _path_status(verify_paths.capath, True),
                        "environment_override": _environment_path_status(
                            verify_paths.openssl_capath_env,
                            True,
                        ),
                        "compiled_default": _path_status(
                            verify_paths.openssl_capath,
                            True,
                        ),
                    },
                    "cert_store_stats": context.cert_store_stats(),
                },
                sort_keys=True,
            )
        )

        smtp = None
        try:
            smtp = smtplib.SMTP(
                settings.EMAIL_HOST,
                settings.EMAIL_PORT,
                timeout=15,
            )
            smtp.ehlo()
            smtp.starttls(context=context)
        except ssl.SSLCertVerificationError as error:
            self.stderr.write(
                json.dumps(
                    {
                        "gmail_starttls": "certificate_verification_failed",
                        "verify_code": error.verify_code,
                        "verify_message": error.verify_message,
                    },
                    sort_keys=True,
                )
            )
        except (OSError, smtplib.SMTPException) as error:
            self.stderr.write(
                json.dumps(
                    {
                        "gmail_starttls": "failed",
                        "error_type": type(error).__name__,
                    },
                    sort_keys=True,
                )
            )
        else:
            self.stdout.write(json.dumps({"gmail_starttls": "verified"}))
        finally:
            if smtp is not None:
                smtp.close()
