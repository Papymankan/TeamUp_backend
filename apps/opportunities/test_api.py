from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.applications.models import Application
from apps.users.models import Interest, PortfolioItem, Skill, User
from .models import Opportunity


class OpportunityAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="opportunity-api-owner@example.com",
            password="secure-test-password",
        )
        self.other = User.objects.create_user(
            email="opportunity-api-other@example.com",
            password="secure-test-password",
        )
        self.applicant = User.objects.create_user(
            email="opportunity-api-applicant@example.com",
            password="secure-test-password",
        )
        self.skill = Skill.objects.create(name="React API Test")
        self.interest = Interest.objects.create(name="Frontend API Test")

    def opportunity_payload(self, **changes):
        payload = {
            "title": "Django Collaboration",
            "description": "<h2>Details</h2><p><strong>React</strong> work</p>",
            "category": PortfolioItem.ItemType.PROJECT,
            "weekly_time_commitment_hours": "4.50",
            "skills": [self.skill.pk],
            "interests": [self.interest.pk],
        }
        payload.update(changes)
        return payload

    def create_opportunity(self, **changes):
        defaults = {
            "owner": self.owner,
            "title": "Public project",
            "description": "<p>React development</p>",
            "category": PortfolioItem.ItemType.PROJECT,
            "weekly_time_commitment_hours": Decimal("5.00"),
        }
        defaults.update(changes)
        return Opportunity.objects.create(**defaults)

    def test_anonymous_create_is_rejected(self):
        response = self.client.post(
            "/api/opportunities/",
            self.opportunity_payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_create_assigns_owner_and_draft_status(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            "/api/opportunities/",
            self.opportunity_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        opportunity = Opportunity.objects.get(pk=response.data["id"])
        self.assertEqual(opportunity.owner, self.owner)
        self.assertEqual(opportunity.status, Opportunity.Status.DRAFT)
        self.assertEqual(list(opportunity.skills.all()), [self.skill])
        self.assertEqual(list(opportunity.interests.all()), [self.interest])

    def test_create_rejects_invalid_category_hours_and_relationship_ids(self):
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            "/api/opportunities/",
            self.opportunity_payload(category="invalid"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(
            "/api/opportunities/",
            self.opportunity_payload(weekly_time_commitment_hours="-1"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(
            "/api/opportunities/",
            self.opportunity_payload(skills=[999999]),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_owner_patch_preserves_owner_and_omitted_fields(self):
        opportunity = self.create_opportunity(status=Opportunity.Status.DRAFT)
        self.client.force_authenticate(self.owner)

        response = self.client.patch(
            f"/api/opportunities/{opportunity.pk}/",
            {"title": "Updated title", "owner": self.other.pk, "status": "published"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.patch(
            f"/api/opportunities/{opportunity.pk}/",
            {"title": "Updated title"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        opportunity.refresh_from_db()
        self.assertEqual(opportunity.owner, self.owner)
        self.assertEqual(opportunity.status, Opportunity.Status.DRAFT)
        self.assertEqual(opportunity.description, "<p>React development</p>")

    def test_non_owner_cannot_update_or_delete(self):
        opportunity = self.create_opportunity()
        self.client.force_authenticate(self.other)

        update = self.client.patch(
            f"/api/opportunities/{opportunity.pk}/",
            {"title": "Unauthorized"},
            format="json",
        )
        delete = self.client.delete(f"/api/opportunities/{opportunity.pk}/")
        self.assertIn(update.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.assertIn(delete.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_owner_delete_with_application_is_blocked_and_without_application_succeeds(self):
        opportunity = self.create_opportunity()
        Application.objects.create(
            opportunity=opportunity,
            applicant=self.applicant,
        )
        self.client.force_authenticate(self.owner)

        blocked = self.client.delete(f"/api/opportunities/{opportunity.pk}/")
        self.assertEqual(blocked.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Opportunity.objects.filter(pk=opportunity.pk).exists())

        opportunity.applications.all().delete()
        deleted = self.client.delete(f"/api/opportunities/{opportunity.pk}/")
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)

    def test_publish_reopen_and_close_update_timestamps(self):
        draft = self.create_opportunity(status=Opportunity.Status.DRAFT)
        self.client.force_authenticate(self.owner)

        published = self.client.post(f"/api/opportunities/{draft.pk}/publish/")
        self.assertEqual(published.status_code, status.HTTP_200_OK)
        draft.refresh_from_db()
        self.assertEqual(draft.status, Opportunity.Status.PUBLISHED)
        self.assertIsNotNone(draft.published_at)

        closed = self.client.post(f"/api/opportunities/{draft.pk}/close/")
        self.assertEqual(closed.status_code, status.HTTP_200_OK)
        draft.refresh_from_db()
        self.assertEqual(draft.status, Opportunity.Status.CLOSED)
        self.assertIsNotNone(draft.closed_at)

        reopened = self.client.post(f"/api/opportunities/{draft.pk}/publish/")
        self.assertEqual(reopened.status_code, status.HTTP_200_OK)
        draft.refresh_from_db()
        self.assertEqual(draft.status, Opportunity.Status.PUBLISHED)
        self.assertIsNone(draft.closed_at)

        invalid = self.client.post(f"/api/opportunities/{draft.pk}/publish/")
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)

    def test_publish_and_close_require_owner(self):
        opportunity = self.create_opportunity(status=Opportunity.Status.DRAFT)
        self.client.force_authenticate(self.other)

        publish = self.client.post(f"/api/opportunities/{opportunity.pk}/publish/")
        close = self.client.post(f"/api/opportunities/{opportunity.pk}/close/")
        self.assertEqual(publish.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(close.status_code, status.HTTP_403_FORBIDDEN)

    def test_visibility_for_public_draft_and_closed_opportunities(self):
        published = self.create_opportunity(status=Opportunity.Status.PUBLISHED)
        draft = self.create_opportunity(title="Draft", status=Opportunity.Status.DRAFT)
        closed = self.create_opportunity(title="Closed", status=Opportunity.Status.CLOSED)
        Application.objects.create(opportunity=closed, applicant=self.applicant)

        public_detail = self.client.get(f"/api/opportunities/{published.pk}/")
        draft_detail = self.client.get(f"/api/opportunities/{draft.pk}/")
        closed_detail = self.client.get(f"/api/opportunities/{closed.pk}/")
        self.assertEqual(public_detail.status_code, status.HTTP_200_OK)
        self.assertEqual(draft_detail.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(closed_detail.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(self.owner)
        owner_draft = self.client.get(f"/api/opportunities/{draft.pk}/")
        owner_closed = self.client.get(f"/api/opportunities/{closed.pk}/")
        self.assertEqual(owner_draft.status_code, status.HTTP_200_OK)
        self.assertEqual(owner_closed.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(self.applicant)
        applicant_closed = self.client.get(f"/api/opportunities/{closed.pk}/")
        unrelated_closed = self.client.get(
            f"/api/opportunities/{closed.pk}/"
        )
        self.assertEqual(applicant_closed.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(self.other)
        unrelated_closed = self.client.get(f"/api/opportunities/{closed.pk}/")
        self.assertEqual(unrelated_closed.status_code, status.HTTP_404_NOT_FOUND)

    def test_detail_application_field_is_null_for_anonymous_and_non_applicant(self):
        opportunity = self.create_opportunity(status=Opportunity.Status.PUBLISHED)

        anonymous_response = self.client.get(
            f"/api/opportunities/{opportunity.pk}/"
        )
        self.assertEqual(anonymous_response.status_code, status.HTTP_200_OK)
        self.assertIsNone(anonymous_response.data["current_user_application"])

        self.client.force_authenticate(self.other)
        non_applicant_response = self.client.get(
            f"/api/opportunities/{opportunity.pk}/"
        )
        self.assertEqual(non_applicant_response.status_code, status.HTTP_200_OK)
        self.assertIsNone(non_applicant_response.data["current_user_application"])

    def test_detail_application_field_contains_only_request_users_application(self):
        opportunity = self.create_opportunity(status=Opportunity.Status.PUBLISHED)
        own_application = Application.objects.create(
            opportunity=opportunity,
            applicant=self.applicant,
            message="Private applicant message",
        )
        other_application = Application.objects.create(
            opportunity=opportunity,
            applicant=self.other,
        )

        self.client.force_authenticate(self.applicant)
        own_response = self.client.get(f"/api/opportunities/{opportunity.pk}/")
        current_application = own_response.data["current_user_application"]
        self.assertEqual(current_application["id"], own_application.pk)
        self.assertEqual(current_application["status"], "Pending")
        self.assertEqual(
            parse_datetime(current_application["created_at"]),
            own_application.applied_at,
        )
        self.assertEqual(
            set(current_application),
            {"id", "status", "created_at"},
        )
        self.assertNotIn("message", current_application)
        self.assertNotEqual(current_application["id"], other_application.pk)

        self.client.force_authenticate(self.owner)
        owner_response = self.client.get(f"/api/opportunities/{opportunity.pk}/")
        self.assertIsNone(owner_response.data["current_user_application"])

    def test_detail_application_field_reflects_each_current_status(self):
        statuses = (
            (Application.Status.PENDING, "Pending"),
            (Application.Status.ACCEPTED, "Accepted"),
            (Application.Status.REJECTED, "Rejected"),
            (Application.Status.WITHDRAWN, "Withdrawn"),
        )
        self.client.force_authenticate(self.applicant)

        for application_status, expected_label in statuses:
            opportunity = self.create_opportunity(
                title=f"{application_status} opportunity",
                status=Opportunity.Status.PUBLISHED,
            )
            application = Application.objects.create(
                opportunity=opportunity,
                applicant=self.applicant,
                status=application_status,
            )
            response = self.client.get(f"/api/opportunities/{opportunity.pk}/")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.data["current_user_application"]["id"],
                application.pk,
            )
            self.assertEqual(
                response.data["current_user_application"]["status"],
                expected_label,
            )

    def test_invalid_jwt_keeps_existing_authentication_behavior(self):
        opportunity = self.create_opportunity(status=Opportunity.Status.PUBLISHED)
        response = self.client.get(
            f"/api/opportunities/{opportunity.pk}/",
            HTTP_AUTHORIZATION="Bearer invalid-token",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_public_discovery_excludes_draft_and_closed(self):
        published = self.create_opportunity(status=Opportunity.Status.PUBLISHED)
        self.create_opportunity(title="Draft", status=Opportunity.Status.DRAFT)
        self.create_opportunity(title="Closed", status=Opportunity.Status.CLOSED)

        response = self.client.get("/api/opportunities/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data["results"]]
        self.assertIn(published.pk, ids)
        self.assertNotIn(
            Opportunity.objects.get(title="Draft").pk,
            ids,
        )
        self.assertNotIn(
            Opportunity.objects.get(title="Closed").pk,
            ids,
        )

    def test_mine_returns_only_owned_opportunities_and_supports_status_filter(self):
        owned = self.create_opportunity(status=Opportunity.Status.DRAFT)
        self.create_opportunity(
            owner=self.other,
            title="Other opportunity",
            status=Opportunity.Status.PUBLISHED,
        )
        self.client.force_authenticate(self.owner)

        response = self.client.get("/api/opportunities/mine/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data["results"]]
        self.assertIn(owned.pk, ids)
        self.assertNotIn(
            Opportunity.objects.get(title="Other opportunity").pk,
            ids,
        )

        filtered = self.client.get("/api/opportunities/mine/?status=closed")
        self.assertEqual(filtered.status_code, status.HTTP_200_OK)
        self.assertEqual(filtered.data["count"], 0)

    def test_search_category_skill_interest_and_hours_filters(self):
        opportunity = self.create_opportunity(
            title="Machine interface",
            description="<h2>Accessible React project</h2>",
            status=Opportunity.Status.PUBLISHED,
            weekly_time_commitment_hours=Decimal("8.00"),
        )
        opportunity.skills.add(self.skill)
        opportunity.interests.add(self.interest)

        cases = [
            "?search=machine",
            "?search=Accessible",
            "?category=project",
            f"?skills={self.skill.pk}",
            f"?interests={self.interest.pk}",
            "?min_hours=7",
            "?max_hours=8",
            f"?search=machine&category=project&skills={self.skill.pk}"
            f"&interests={self.interest.pk}&min_hours=7&max_hours=8",
        ]
        for query in cases:
            response = self.client.get(f"/api/opportunities/{query}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn(opportunity.pk, [item["id"] for item in response.data["results"]])

    def test_malformed_filter_values_are_rejected(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get("/api/opportunities/?skills=abc")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get("/api/opportunities/?category=unknown")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get("/api/opportunities/?min_hours=-1")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_description_sanitizes_untrusted_html(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            "/api/opportunities/",
            self.opportunity_payload(
                description=(
                    "<h2>Safe</h2><script>alert(1)</script>"
                    "<p onclick=\"bad()\"><em>Text</em></p>"
                    '<a href="javascript:alert(1)">Unsafe</a>'
                    '<a href="https://example.com" title="Safe">Safe link</a>'
                )
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        opportunity = Opportunity.objects.get(pk=response.data["id"])
        self.assertIn("<h2>Safe</h2>", opportunity.description)
        self.assertIn("<em>Text</em>", opportunity.description)
        self.assertNotIn("<script", opportunity.description)
        self.assertNotIn("onclick", opportunity.description)
        self.assertNotIn("javascript:", opportunity.description)
        self.assertIn('href="https://example.com"', opportunity.description)
