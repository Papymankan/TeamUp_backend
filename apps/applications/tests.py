from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.opportunities.models import Opportunity
from apps.users.models import PortfolioItem, User
from .models import Application


class ApplicationModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="application-owner@example.com",
            password="secure-test-password",
        )
        self.applicant = User.objects.create_user(
            email="applicant@example.com",
            password="secure-test-password",
        )
        self.opportunity = Opportunity.objects.create(
            owner=self.owner,
            title="Project opportunity",
            category=PortfolioItem.ItemType.PROJECT,
            weekly_time_commitment_hours=Decimal("3.00"),
        )

    def test_creation_defaults_to_pending_with_nullable_message(self):
        application = Application.objects.create(
            opportunity=self.opportunity,
            applicant=self.applicant,
        )

        self.assertEqual(application.status, Application.Status.PENDING)
        self.assertIsNone(application.message)
        self.assertIsNotNone(application.applied_at)
        self.assertIsNotNone(application.status_updated_at)

    def test_duplicate_applicant_opportunity_pair_is_rejected(self):
        Application.objects.create(
            opportunity=self.opportunity,
            applicant=self.applicant,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Application.objects.create(
                    opportunity=self.opportunity,
                    applicant=self.applicant,
                )
