from unittest.mock import call, patch

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase


class MigrateAndDiagnoseTests(SimpleTestCase):
    @patch("apps.users.management.commands.migrate_and_diagnose.call_command")
    def test_runs_migrations_before_diagnostic(self, mocked_call_command):
        call_command("migrate_and_diagnose")

        self.assertEqual(
            mocked_call_command.call_args_list,
            [
                call("migrate", interactive=False),
                call("diagnose_smtp_tls"),
            ],
        )

    @patch("apps.users.management.commands.migrate_and_diagnose.call_command")
    def test_skips_diagnostic_when_migrations_fail(self, mocked_call_command):
        mocked_call_command.side_effect = CommandError("migration failed")

        with self.assertRaisesMessage(CommandError, "migration failed"):
            call_command("migrate_and_diagnose")

        mocked_call_command.assert_called_once_with("migrate", interactive=False)
