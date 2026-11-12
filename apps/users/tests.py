from decimal import Decimal

from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .forms import UserCreationForm
from .models import (
    Interest,
    PortfolioItem,
    Profile,
    Skill,
    UserInterest,
    UserSkill,
)


User = get_user_model()


class UserAndProfileTests(TestCase):
    def test_admin_user_creation_form_uses_email_instead_of_username(self):
        form = UserCreationForm(
            data={
                "email": "admin-form@example.com",
                "first_name": "Team",
                "last_name": "Member",
                "password1": "secure-test-password",
                "password2": "secure-test-password",
            }
        )

        self.assertNotIn("username", form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.email, "admin-form@example.com")
        self.assertTrue(user.check_password("secure-test-password"))

    def test_user_uses_email_and_django_password_hashing(self):
        user = User.objects.create_user(
            email="student@example.com",
            password="secure-test-password",
        )

        self.assertNotIn("username", [field.name for field in User._meta.fields])
        self.assertEqual(User.USERNAME_FIELD, "email")
        self.assertTrue(user.check_password("secure-test-password"))
        self.assertEqual(
            authenticate(username="student@example.com", password="secure-test-password"),
            user,
        )

    def test_user_creation_creates_one_profile(self):
        user = User.objects.create_user(
            email="profile@example.com",
            password="secure-test-password",
        )

        self.assertIsInstance(user.profile, Profile)
        self.assertEqual(Profile.objects.filter(user=user).count(), 1)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Profile.objects.create(user=user)

    def test_weekly_availability_has_validators_and_database_constraint(self):
        user = User.objects.create_user(
            email="hours@example.com",
            password="secure-test-password",
        )
        profile = user.profile

        for hours in (Decimal("-0.01"), Decimal("168.01")):
            profile.weekly_available_hours = hours
            with self.assertRaises(ValidationError) as error:
                profile.full_clean()
            self.assertIn("weekly_available_hours", error.exception.error_dict)

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Profile.objects.filter(pk=profile.pk).update(
                        weekly_available_hours=hours
                    )

        profile.weekly_available_hours = Decimal("168.00")
        profile.full_clean()


class SkillAndInterestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="relationships@example.com",
            password="secure-test-password",
        )

    def test_skill_names_are_trimmed_and_case_insensitively_unique(self):
        skill = Skill.objects.create(name="  Python   Programming ")

        self.assertEqual(skill.name, "Python Programming")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Skill.objects.create(name="python programming")

    def test_interest_names_are_trimmed_and_case_insensitively_unique(self):
        interest = Interest.objects.create(name="  Machine   Learning ")

        self.assertEqual(interest.name, "Machine Learning")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Interest.objects.create(name="machine learning")

    def test_user_skill_pair_is_unique(self):
        skill = Skill.objects.create(name="Research")
        UserSkill.objects.create(
            user=self.user,
            skill=skill,
            proficiency_level=UserSkill.Proficiency.INTERMEDIATE,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserSkill.objects.create(user=self.user, skill=skill)

    def test_user_interest_pair_is_unique(self):
        interest = Interest.objects.create(name="Robotics")
        UserInterest.objects.create(user=self.user, interest=interest)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserInterest.objects.create(user=self.user, interest=interest)

    def test_profile_can_have_multiple_portfolio_items(self):
        profile = self.user.profile
        first = PortfolioItem.objects.create(profile=profile, title="Team project")
        second = PortfolioItem.objects.create(
            profile=profile,
            title="Research assistant",
            item_type=PortfolioItem.ItemType.WORK_EXPERIENCE,
        )

        self.assertCountEqual(profile.portfolio_items.all(), [first, second])


class StageThreeProfileAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="profile-api@example.com",
            password="secure-test-password",
        )
        self.other_user = User.objects.create_user(
            email="other-profile@example.com",
            password="secure-test-password",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.other_client = APIClient()
        self.other_client.force_authenticate(user=self.other_user)

    def test_profile_can_be_retrieved_and_updated(self):
        response = self.client.get("/api/profile/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.patch(
            "/api/profile/",
            {
                "bio": "Researching academic opportunities.",
                "university": "University of Tehran",
                "major": "Computer Engineering",
                "study_year": 3,
                "graduation_year": 2028,
                "weekly_available_hours": "15.50",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.bio, "Researching academic opportunities.")
        self.assertEqual(self.user.profile.major, "Computer Engineering")
        self.assertEqual(self.user.profile.weekly_available_hours, Decimal("15.50"))

    def test_profile_missing_profile_is_created_safely(self):
        self.user.profile.delete()

        response = self.client.get("/api/profile/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Profile.objects.filter(user=self.user).count(), 1)

    def test_profile_rejects_unknown_user_field(self):
        response = self.client.patch("/api/profile/", {"user": self.other_user.pk})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_profile_requires_authentication(self):
        unauthenticated_client = APIClient()
        response = unauthenticated_client.get("/api/profile/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_weekly_availability_supports_valid_values_and_rejects_invalid(self):
        valid_response = self.client.patch(
            "/api/profile/",
            {"weekly_available_hours": "15.50"},
        )
        self.assertEqual(valid_response.status_code, status.HTTP_200_OK)

        invalid_responses = (
            ("-1", status.HTTP_400_BAD_REQUEST),
            ("168.01", status.HTTP_400_BAD_REQUEST),
            ("abc", status.HTTP_400_BAD_REQUEST),
        )
        for value, code in invalid_responses:
            with self.subTest(value=value):
                response = self.client.patch(
                    "/api/profile/",
                    {"weekly_available_hours": value},
                )
                self.assertEqual(response.status_code, code)

    def test_skill_list_and_user_skill_management(self):
        available = self.client.get("/api/skills/")
        self.assertEqual(available.status_code, status.HTTP_200_OK)

        create_response = self.client.post(
            "/api/profile/skills/",
            {"name": "  React  ", "proficiency_level": "intermediate"},
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.user.user_skills.count(), 1)

        duplicate_response = self.client.post(
            "/api/profile/skills/",
            {"name": "react", "proficiency_level": "advanced"},
        )
        self.assertEqual(duplicate_response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.user.user_skills.count(), 1)

        skill = Skill.objects.get(name="React")
        list_response = self.client.get("/api/profile/skills/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            any(item["skill"]["name"] == "React" for item in list_response.json())
        )

        delete_response = self.client.delete(f"/api/profile/skills/{skill.pk}/")
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.user.user_skills.count(), 0)
        self.assertEqual(Skill.objects.filter(name__iexact="react").count(), 1)

    def test_other_user_cannot_delete_another_users_skill(self):
        skill = Skill.objects.create(name="Django")
        UserSkill.objects.create(
            user=self.other_user,
            skill=skill,
            proficiency_level=UserSkill.Proficiency.ADVANCED,
        )

        response = self.client.delete(f"/api/profile/skills/{skill.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_interest_list_and_user_interest_management(self):
        available = self.client.get("/api/interests/")
        self.assertEqual(available.status_code, status.HTTP_200_OK)

        create_response = self.client.post(
            "/api/profile/interests/",
            {"name": "  GIS  "},
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.user.user_interests.count(), 1)

        duplicate_response = self.client.post(
            "/api/profile/interests/",
            {"name": "gis"},
        )
        self.assertEqual(duplicate_response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.user.user_interests.count(), 1)

        interest = Interest.objects.get(name="GIS")
        delete_response = self.client.delete(f"/api/profile/interests/{interest.pk}/")
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.user.user_interests.count(), 0)
        self.assertEqual(Interest.objects.filter(name__iexact="gis").count(), 1)

    def test_other_user_cannot_delete_another_users_interest(self):
        interest = Interest.objects.create(name="Robotics")
        UserInterest.objects.create(user=self.other_user, interest=interest)

        response = self.client.delete(f"/api/profile/interests/{interest.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_portfolio_item_crud_and_permission_checks(self):
        create_response = self.client.post(
            "/api/profile/portfolio/",
            {
                "title": "TeamUp University Project",
                "description": "Academic collaboration platform.",
                "url": "https://github.com/example/teamup",
                "item_type": "project",
            },
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        item_id = create_response.json()["id"]

        list_response = self.client.get("/api/profile/portfolio/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.json()), 1)

        patch_response = self.client.patch(
            f"/api/profile/portfolio/{item_id}/",
            {"title": "Updated TeamUp Project", "description": "Updated description."},
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.json()["title"], "Updated TeamUp Project")

        invalid_response = self.client.post(
            "/api/profile/portfolio/",
            {"title": "Broken URL", "url": "not-a-valid-url"},
        )
        self.assertEqual(invalid_response.status_code, status.HTTP_400_BAD_REQUEST)

        other_response = self.other_client.get(f"/api/profile/portfolio/{item_id}/")
        self.assertEqual(other_response.status_code, status.HTTP_404_NOT_FOUND)

        delete_response = self.client.delete(f"/api/profile/portfolio/{item_id}/")
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(PortfolioItem.objects.filter(profile__user=self.user).count(), 0)


class ExistingEndpointTests(TestCase):
    def test_health_documentation_and_admin_routes_remain_available(self):
        routes = (
            "/api/health/",
            "/api/schema/",
            "/api/docs/",
            "/api/redoc/",
            "/admin/login/",
        )

        for route in routes:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 200)

        self.assertEqual(
            self.client.get("/api/health/").json(),
            {"status": "ok", "message": "TeamUp API is running"},
        )
