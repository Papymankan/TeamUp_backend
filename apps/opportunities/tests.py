from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.users.models import Interest, PortfolioItem, Skill, User
from .models import Opportunity


class OpportunityModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="opportunity-owner@example.com",
            password="secure-test-password",
        )

    def test_creation_defaults_to_draft_and_stores_html_description(self):
        description = (
            "<h2>About the project</h2><p><strong>Build</strong> an app.</p>"
            "<ol><li>Design</li></ol><a href=\"https://example.com\">Details</a>"
        )
        opportunity = Opportunity.objects.create(
            owner=self.owner,
            title="Project opportunity",
            description=description,
            category=PortfolioItem.ItemType.PROJECT,
            weekly_time_commitment_hours=Decimal("4.50"),
        )

        self.assertEqual(opportunity.status, Opportunity.Status.DRAFT)
        self.assertEqual(opportunity.description, description)
        self.assertIsNone(opportunity.published_at)
        self.assertIsNone(opportunity.closed_at)

    def test_category_choices_are_reused_from_portfolio_item(self):
        category_field = Opportunity._meta.get_field("category")

        self.assertEqual(category_field.choices, PortfolioItem.ItemType.choices)

    def test_weekly_commitment_must_be_nonnegative(self):
        opportunity = Opportunity(
            owner=self.owner,
            title="Project opportunity",
            category=PortfolioItem.ItemType.PROJECT,
            weekly_time_commitment_hours=Decimal("-0.01"),
        )

        with self.assertRaises(ValidationError) as error:
            opportunity.full_clean()
        self.assertIn("weekly_time_commitment_hours", error.exception.error_dict)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Opportunity.objects.create(
                    owner=self.owner,
                    title="Invalid opportunity",
                    category=PortfolioItem.ItemType.PROJECT,
                    weekly_time_commitment_hours=Decimal("-0.01"),
                )

    def test_opportunity_uses_existing_skill_and_interest_models(self):
        opportunity = Opportunity.objects.create(
            owner=self.owner,
            title="Project opportunity",
            category=PortfolioItem.ItemType.PROJECT,
            weekly_time_commitment_hours=Decimal("2.00"),
        )
        skill = Skill.objects.create(name="React.js")
        interest = Interest.objects.create(name="Frontend Development")

        opportunity.skills.add(skill)
        opportunity.interests.add(interest)

        self.assertEqual(list(opportunity.skills.all()), [skill])
        self.assertEqual(list(opportunity.interests.all()), [interest])
        self.assertIn(opportunity, skill.opportunities.all())
        self.assertIn(opportunity, interest.opportunities.all())
