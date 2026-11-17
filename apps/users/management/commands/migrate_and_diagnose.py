from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run database migrations, then diagnose SMTP TLS."

    def handle(self, *args, **options):
        call_command("migrate", interactive=False)
        call_command("diagnose_smtp_tls")
