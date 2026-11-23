from datetime import timedelta
from decimal import Decimal
from smtplib import SMTPException
from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.opportunities.models import Opportunity
from apps.users.models import PortfolioItem, User
from .models import Application


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    FRONTEND_URL="https://teamup.example.test",
    FRONTEND_OPPORTUNITY_DETAIL_PATH="/opportunities/{id}",
    FRONTEND_OPPORTUNITIES_PATH="/opportunities",
)
class ApplicationAPITests(TestCase):
    def setUp(self):
        mail.outbox.clear()
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="application-api-owner@example.com",
            password="secure-test-password",
            first_name="Opportunity",
            last_name="Owner",
        )
        self.applicant = User.objects.create_user(
            email="application-api-applicant@example.com",
            password="secure-test-password",
            first_name="Applicant",
            last_name="One",
        )
        self.other = User.objects.create_user(
            email="application-api-other@example.com",
            password="secure-test-password",
            first_name="Other",
            last_name="User",
        )
        self.opportunity = self.make_opportunity()

    def make_opportunity(self, **changes):
        fields = {
            "owner": self.owner,
            "title": "Collaborative project",
            "category": PortfolioItem.ItemType.PROJECT,
            "weekly_time_commitment_hours": Decimal("4.00"),
            "status": Opportunity.Status.PUBLISHED,
        }
        fields.update(changes)
        return Opportunity.objects.create(**fields)

    def make_application(self, opportunity=None, applicant=None, **changes):
        fields = {
            "opportunity": opportunity or self.opportunity,
            "applicant": applicant or self.applicant,
        }
        fields.update(changes)
        return Application.objects.create(**fields)

    def make_application_in_state(self, state, title):
        opportunity = self.make_opportunity(title=title)
        return self.make_application(opportunity=opportunity, status=state)

    def test_apply_requires_authentication_and_creates_pending_application(self):
        response = self.client.post(
            f"/api/opportunities/{self.opportunity.pk}/apply/",
            {"message": "I can contribute."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.applicant)
        response = self.client.post(
            f"/api/opportunities/{self.opportunity.pk}/apply/",
            {"message": "I can contribute."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        application = Application.objects.get(pk=response.data["id"])
        self.assertEqual(application.applicant, self.applicant)
        self.assertEqual(application.status, Application.Status.PENDING)
        self.assertEqual(application.message, "I can contribute.")
        self.assertEqual(response.data["opportunity_id"], self.opportunity.pk)
        self.assertEqual(response.data["opportunity_title"], self.opportunity.title)

    def test_apply_uses_request_user_and_rejects_spoofed_identity_fields(self):
        self.client.force_authenticate(self.applicant)
        response = self.client.post(
            f"/api/opportunities/{self.opportunity.pk}/apply/",
            {"message": "Hello", "applicant": self.other.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Application.objects.exists())

        response = self.client.post(
            f"/api/opportunities/{self.opportunity.pk}/apply/",
            {"message": "Hello"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            Application.objects.get(pk=response.data["id"]).applicant,
            self.applicant,
        )

    def test_owner_and_non_published_opportunities_reject_applications(self):
        self.client.force_authenticate(self.owner)
        own_response = self.client.post(
            f"/api/opportunities/{self.opportunity.pk}/apply/",
            {},
            format="json",
        )
        self.assertEqual(own_response.status_code, status.HTTP_400_BAD_REQUEST)

        self.client.force_authenticate(self.applicant)
        for state in (Opportunity.Status.DRAFT, Opportunity.Status.CLOSED):
            opportunity = self.make_opportunity(
                title=f"{state} opportunity",
                status=state,
            )
            response = self.client.post(
                f"/api/opportunities/{opportunity.pk}/apply/",
                {},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_application_is_rejected(self):
        self.client.force_authenticate(self.applicant)
        url = f"/api/opportunities/{self.opportunity.pk}/apply/"

        first = self.client.post(url, {"message": None}, format="json")
        second = self.client.post(url, {}, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Application.objects.count(), 1)

    def test_my_applications_are_scoped_paginated_and_return_opportunity_fields(self):
        owned_application = self.make_application()
        other_opportunity = self.make_opportunity(
            title="Another project",
            status=Opportunity.Status.CLOSED,
        )
        second_application = self.make_application(opportunity=other_opportunity)
        self.make_application(
            applicant=self.other,
            opportunity=self.make_opportunity(title="Other user's opportunity"),
        )

        self.client.force_authenticate(self.applicant)
        response = self.client.get("/api/applications/mine/?page_size=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 1)
        result = response.data["results"][0]
        self.assertIn(result["id"], (owned_application.pk, second_application.pk))
        self.assertIn("opportunity_id", result)
        self.assertIn("opportunity_title", result)
        self.assertIn("opportunity_category", result)
        self.assertIn("opportunity_status", result)
        self.assertNotIn("owner_email", result)

        next_page = self.client.get("/api/applications/mine/?page=2&page_size=1")
        self.assertEqual(next_page.status_code, status.HTTP_200_OK)
        self.assertNotEqual(
            response.data["results"][0]["id"],
            next_page.data["results"][0]["id"],
        )

    def test_mine_status_filter_and_invalid_filter(self):
        self.make_application()
        self.make_application(
            applicant=self.other,
            opportunity=self.make_opportunity(title="Other applicant opportunity"),
        )
        self.client.force_authenticate(self.applicant)

        filtered = self.client.get("/api/applications/mine/?status=pending")
        self.assertEqual(filtered.status_code, status.HTTP_200_OK)
        self.assertEqual(filtered.data["count"], 1)
        invalid = self.client.get("/api/applications/mine/?status=unknown")
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_opportunity_owner_can_view_applicants(self):
        application = self.make_application()
        self.client.force_authenticate(self.owner)

        response = self.client.get(
            f"/api/opportunities/{self.opportunity.pk}/applications/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        result = response.data["results"][0]
        self.assertEqual(result["id"], application.pk)
        self.assertEqual(result["applicant"]["id"], self.applicant.pk)
        self.assertEqual(result["applicant"]["first_name"], "Applicant")
        self.assertNotIn("email", result["applicant"])
        self.assertNotIn("password", result["applicant"])

        self.client.force_authenticate(self.other)
        forbidden = self.client.get(
            f"/api/opportunities/{self.opportunity.pk}/applications/"
        )
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)

    def test_applicant_list_is_paginated(self):
        self.make_application()
        second_user = User.objects.create_user(
            email="application-api-second@example.com",
            password="secure-test-password",
        )
        self.make_application(applicant=second_user)
        self.client.force_authenticate(self.owner)

        response = self.client.get(
            f"/api/opportunities/{self.opportunity.pk}/applications/?page_size=1"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 1)

    def test_applicant_can_withdraw_pending_application_once(self):
        application = self.make_application()
        previous_update = timezone.now() - timedelta(days=1)
        Application.objects.filter(pk=application.pk).update(
            status_updated_at=previous_update
        )
        self.client.force_authenticate(self.applicant)

        response = self.client.post(
            f"/api/applications/{application.pk}/withdraw/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.WITHDRAWN)
        self.assertGreater(application.status_updated_at, previous_update)

        repeated = self.client.post(
            f"/api/applications/{application.pk}/withdraw/"
        )
        self.assertEqual(repeated.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Application.objects.filter(pk=application.pk).exists())

    def test_another_applicant_cannot_withdraw(self):
        application = self.make_application()
        self.client.force_authenticate(self.other)

        response = self.client.post(
            f"/api/applications/{application.pk}/withdraw/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.PENDING)

    def test_non_pending_applications_cannot_be_withdrawn(self):
        for state in (
            Application.Status.ACCEPTED,
            Application.Status.REJECTED,
            Application.Status.WITHDRAWN,
        ):
            application = self.make_application_in_state(
                state,
                f"Cannot withdraw {state}",
            )
            self.client.force_authenticate(self.applicant)
            response = self.client.post(
                f"/api/applications/{application.pk}/withdraw/"
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_owner_can_accept_or_reject_pending_applications(self):
        accepted = self.make_application()
        remains_pending = self.make_application(applicant=self.other)
        rejected = self.make_application(
            applicant=self.other,
            opportunity=self.make_opportunity(title="Rejectable project"),
        )
        self.client.force_authenticate(self.owner)

        accept_response = self.client.post(
            f"/api/applications/{accepted.pk}/accept/"
        )
        reject_response = self.client.post(
            f"/api/applications/{rejected.pk}/reject/"
        )
        self.assertEqual(accept_response.status_code, status.HTTP_200_OK)
        self.assertEqual(reject_response.status_code, status.HTTP_200_OK)
        accepted.refresh_from_db()
        remains_pending.refresh_from_db()
        rejected.refresh_from_db()
        self.assertEqual(accepted.status, Application.Status.ACCEPTED)
        self.assertEqual(remains_pending.status, Application.Status.PENDING)
        self.assertEqual(rejected.status, Application.Status.REJECTED)
        self.assertTrue(Application.objects.filter(pk=rejected.pk).exists())

    def test_non_owner_cannot_accept_or_reject(self):
        application = self.make_application()
        self.client.force_authenticate(self.other)

        accept = self.client.post(f"/api/applications/{application.pk}/accept/")
        reject = self.client.post(f"/api/applications/{application.pk}/reject/")
        self.assertEqual(accept.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(reject.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_pending_cannot_be_accepted_or_rejected(self):
        for state in (
            Application.Status.ACCEPTED,
            Application.Status.REJECTED,
            Application.Status.WITHDRAWN,
        ):
            application = self.make_application_in_state(
                state,
                f"Cannot transition {state}",
            )
            self.client.force_authenticate(self.owner)
            accept = self.client.post(
                f"/api/applications/{application.pk}/accept/"
            )
            reject = self.client.post(
                f"/api/applications/{application.pk}/reject/"
            )
            self.assertEqual(accept.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(reject.status_code, status.HTTP_400_BAD_REQUEST)

    def test_accept_rejected_for_draft_or_closed_opportunity(self):
        self.client.force_authenticate(self.owner)
        for state in (Opportunity.Status.DRAFT, Opportunity.Status.CLOSED):
            opportunity = self.make_opportunity(
                title=f"Cannot accept {state}",
                status=state,
            )
            application = self.make_application(
                opportunity=opportunity,
                applicant=self.other,
            )
            response = self.client.post(
                f"/api/applications/{application.pk}/accept/"
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            application.refresh_from_db()
            self.assertEqual(application.status, Application.Status.PENDING)

    def test_reject_is_allowed_when_opportunity_is_closed(self):
        opportunity = self.make_opportunity(
            status=Opportunity.Status.CLOSED,
        )
        application = self.make_application(opportunity=opportunity)
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            f"/api/applications/{application.pk}/reject/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.REJECTED)

    def test_application_status_cannot_be_changed_with_patch(self):
        application = self.make_application()
        self.client.force_authenticate(self.applicant)

        response = self.client.patch(
            f"/api/applications/{application.pk}/withdraw/",
            {"status": Application.Status.WITHDRAWN},
            format="json",
        )
        self.assertNotEqual(response.status_code, status.HTTP_200_OK)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.PENDING)

    def test_accept_sends_persian_email_to_applicant_after_commit(self):
        application = self.make_application()
        self.client.force_authenticate(self.owner)

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                f"/api/applications/{application.pk}/accept/"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(mail.outbox, [])

        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        opportunity_url = (
            f"https://teamup.example.test/opportunities/{self.opportunity.pk}"
        )
        self.assertEqual(email.to, [self.applicant.email])
        self.assertNotEqual(email.to, [self.owner.email])
        self.assertEqual(
            email.subject,
            "خبر خوب! درخواست همکاری شما پذیرفته شد 🎉",
        )
        self.assertIn("پذیرفته شده", email.body)
        self.assertIn(self.opportunity.title, email.body)
        self.assertIn(opportunity_url, email.body)
        html_body, content_type = email.alternatives[0]
        self.assertEqual(content_type, "text/html")
        self.assertIn('lang="fa" dir="rtl"', html_body)
        self.assertIn('href="{}"'.format(opportunity_url), html_body)
        self.assertIn("مشاهده فرصت و وضعیت درخواست", html_body)
        self.assertIn("#4f46e5", html_body)

    def test_reject_sends_email_with_opportunity_and_discovery_links(self):
        application = self.make_application()
        self.client.force_authenticate(self.owner)

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                f"/api/applications/{application.pk}/reject/"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        opportunity_url = (
            f"https://teamup.example.test/opportunities/{self.opportunity.pk}"
        )
        opportunities_url = "https://teamup.example.test/opportunities"
        self.assertEqual(email.to, [self.applicant.email])
        self.assertEqual(
            email.subject,
            "به‌روزرسانی وضعیت درخواست شما در TeamUp",
        )
        self.assertIn("پذیرفته نشد", email.body)
        self.assertIn(self.opportunity.title, email.body)
        self.assertIn(opportunity_url, email.body)
        self.assertIn(opportunities_url, email.body)
        html_body, content_type = email.alternatives[0]
        self.assertEqual(content_type, "text/html")
        self.assertIn('href="{}"'.format(opportunity_url), html_body)
        self.assertIn('href="{}"'.format(opportunities_url), html_body)
        self.assertIn("جست‌وجوی فرصت‌های دیگر", html_body)

    def test_apply_and_withdraw_do_not_send_status_emails(self):
        self.client.force_authenticate(self.applicant)
        applied = self.client.post(
            f"/api/opportunities/{self.opportunity.pk}/apply/",
            {"message": "Interested"},
            format="json",
        )
        self.assertEqual(applied.status_code, status.HTTP_201_CREATED)
        self.assertEqual(mail.outbox, [])

        withdrawn = self.client.post(
            f"/api/applications/{applied.data['id']}/withdraw/"
        )
        self.assertEqual(withdrawn.status_code, status.HTTP_200_OK)
        self.assertEqual(mail.outbox, [])

    def test_invalid_unauthorized_and_repeated_actions_do_not_duplicate_emails(self):
        application = self.make_application()
        self.client.force_authenticate(self.other)
        with self.captureOnCommitCallbacks(execute=True) as unauthorized_callbacks:
            unauthorized = self.client.post(
                f"/api/applications/{application.pk}/accept/"
            )
            self.assertEqual(
                unauthorized.status_code,
                status.HTTP_403_FORBIDDEN,
            )
        self.assertEqual(unauthorized_callbacks, [])
        self.assertEqual(mail.outbox, [])

        self.client.force_authenticate(self.owner)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            accepted = self.client.post(
                f"/api/applications/{application.pk}/accept/"
            )
            repeated_accept = self.client.post(
                f"/api/applications/{application.pk}/accept/"
            )
            repeated_reject = self.client.post(
                f"/api/applications/{application.pk}/reject/"
            )
        self.assertEqual(accepted.status_code, status.HTTP_200_OK)
        self.assertEqual(repeated_accept.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(repeated_reject.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_email_failure_is_logged_without_rolling_back_status(self):
        application = self.make_application()
        self.client.force_authenticate(self.owner)

        with patch(
            "apps.applications.email_utils.EmailMultiAlternatives.send",
            side_effect=SMTPException("private SMTP details"),
        ):
            with self.assertLogs(
                "apps.applications.email_utils",
                level="ERROR",
            ) as captured:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(
                        f"/api/applications/{application.pk}/accept/"
                    )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.ACCEPTED)
        self.assertIn(f"application_id={application.pk}", captured.output[0])
        self.assertIn("SMTPException", captured.output[0])
        self.assertNotIn("private SMTP details", captured.output[0])
        self.assertNotIn(self.applicant.email, captured.output[0])
