from decimal import Decimal

from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient, APIRequestFactory

from config.exceptions import api_exception_handler
from .forms import UserCreationForm
from .models import (
    Interest,
    Major,
    PortfolioItem,
    Profile,
    Skill,
    UserInterest,
    UserSkill,
)


User = get_user_model()


class APIExceptionHandlerTests(TestCase):
    def test_unhandled_api_error_is_logged_and_returns_safe_persian_message(self):
        request = APIRequestFactory().post("/api/example/")

        try:
            raise RuntimeError("internal failure details")
        except RuntimeError as error:
            with self.assertLogs("config.exceptions", level="ERROR") as captured:
                response = api_exception_handler(error, {"request": request})

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(
            response.data,
            {"detail": "خطای غیرمنتظره‌ای رخ داد. لطفاً کمی بعد دوباره تلاش کنید."},
        )
        self.assertIn(
            "method=POST path=/api/example/ user_id=None exception_type=RuntimeError",
            captured.output[0],
        )
        self.assertIn("internal failure details", captured.output[0])


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
        self.user.profile.study_year = 3
        self.user.profile.save(update_fields=["study_year"])
        Major.objects.create(name="Computer Engineering")

        response = self.client.get("/api/profile/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("study_year", response.data)
        self.assertEqual(response.data["headline"], "")
        self.assertIsNone(response.data["start_year"])
        self.assertFalse(response.data["is_currently_studying"])

        response = self.client.patch(
            "/api/profile/",
            {
                "headline": "Building useful tools for research teams.",
                "bio": "Researching academic opportunities.",
                "github_url": "https://github.com/example",
                "linkedin_url": "https://www.linkedin.com/in/example",
                "university": "University of Tehran",
                "major": "Computer Engineering",
                "start_year": 2022,
                "graduation_year": 2028,
                "is_currently_studying": True,
                "weekly_available_hours": "15.50",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.profile.refresh_from_db()
        self.assertEqual(
            response.data["headline"],
            "Building useful tools for research teams.",
        )
        self.assertEqual(
            self.user.profile.headline,
            "Building useful tools for research teams.",
        )
        self.assertEqual(self.user.profile.bio, "Researching academic opportunities.")
        self.assertEqual(self.user.profile.github_url, "https://github.com/example")
        self.assertEqual(
            self.user.profile.linkedin_url,
            "https://www.linkedin.com/in/example",
        )
        self.assertEqual(self.user.profile.major.name, "Computer Engineering")
        self.assertEqual(self.user.profile.start_year, 2022)
        self.assertEqual(self.user.profile.graduation_year, 2028)
        self.assertTrue(self.user.profile.is_currently_studying)
        self.assertEqual(self.user.profile.study_year, 3)
        self.assertEqual(self.user.profile.weekly_available_hours, Decimal("15.50"))

    def test_profile_missing_profile_is_created_safely(self):
        self.user.profile.delete()

        response = self.client.get("/api/profile/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Profile.objects.filter(user=self.user).count(), 1)

    def test_profile_rejects_unknown_user_field(self):
        response = self.client.patch("/api/profile/", {"user": self.other_user.pk})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_profile_rejects_legacy_study_year_field(self):
        response = self.client.patch("/api/profile/", {"study_year": 3})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_profile_rejects_major_not_in_catalog(self):
        response = self.client.patch(
            "/api/profile/",
            {"major": "Unlisted Major"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNone(self.user.profile.major)

    def test_major_options_are_public(self):
        Major.objects.create(name="Computer Engineering")

        response = APIClient().get("/api/majors/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [{"name": "Computer Engineering"}])

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

    def test_profile_rejects_invalid_social_urls(self):
        response = self.client.patch(
            "/api/profile/",
            {"github_url": "not-a-url"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_profile_rejects_graduation_year_before_start_year(self):
        response = self.client.patch(
            "/api/profile/",
            {"start_year": 2024, "graduation_year": 2023},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("graduation_year", response.data)

    def test_skill_list_and_user_skill_management(self):
        Skill.objects.create(name="React")
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
        skill = Skill.objects.get(name="Django")
        UserSkill.objects.create(
            user=self.other_user,
            skill=skill,
            proficiency_level=UserSkill.Proficiency.ADVANCED,
        )

        response = self.client.delete(f"/api/profile/skills/{skill.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_new_skill_name_is_rejected_without_creating_catalog_record(self):
        response = self.client.post(
            "/api/profile/skills/",
            {"name": "Never-seen-before"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Skill.objects.filter(name="Never-seen-before").exists())

    def test_user_cannot_add_more_than_ten_skills(self):
        skill_names = [f"Skill Limit Test {index}" for index in range(11)]
        Skill.objects.bulk_create([Skill(name=name) for name in skill_names])

        for name in skill_names[:10]:
            response = self.client.post("/api/profile/skills/", {"name": name})
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        duplicate_response = self.client.post(
            "/api/profile/skills/",
            {"name": skill_names[0]},
        )
        self.assertEqual(duplicate_response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.user.user_skills.count(), 10)

        over_limit_response = self.client.post(
            "/api/profile/skills/",
            {"name": skill_names[10]},
        )
        self.assertEqual(over_limit_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            over_limit_response.data["name"],
            "حداکثر می‌توانید ۱۰ مهارت به پروفایل خود اضافه کنید.",
        )
        self.assertEqual(self.user.user_skills.count(), 10)

    def test_interest_list_and_user_interest_management(self):
        Interest.objects.create(name="GIS")
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

    def test_new_interest_name_is_rejected_without_creating_catalog_record(self):
        response = self.client.post(
            "/api/profile/interests/",
            {"name": "Never-seen-before"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Interest.objects.filter(name="Never-seen-before").exists())

    def test_user_cannot_add_more_than_three_interests(self):
        interest_names = [f"Interest Limit Test {index}" for index in range(4)]
        Interest.objects.bulk_create([Interest(name=name) for name in interest_names])

        for name in interest_names[:3]:
            response = self.client.post("/api/profile/interests/", {"name": name})
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        duplicate_response = self.client.post(
            "/api/profile/interests/",
            {"name": interest_names[0]},
        )
        self.assertEqual(duplicate_response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.user.user_interests.count(), 3)

        over_limit_response = self.client.post(
            "/api/profile/interests/",
            {"name": interest_names[3]},
        )
        self.assertEqual(over_limit_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            over_limit_response.data["name"],
            "حداکثر می‌توانید ۳ علاقه‌مندی به پروفایل خود اضافه کنید.",
        )
        self.assertEqual(self.user.user_interests.count(), 3)

    def test_portfolio_item_crud_and_permission_checks(self):
        create_response = self.client.post(
            "/api/profile/portfolio/",
            {
                "title": "TeamUp University Project",
                "description": "Academic collaboration platform.",
                "url": "https://github.com/example/teamup",
                "item_type": "teaching_assistant",
            },
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.json()["item_type"], "teaching_assistant")
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

    def test_portfolio_item_type_list_is_public_and_contains_bilingual_choices(self):
        response = APIClient().get("/api/portfolio-item-types/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            [
                {
                    "value": "project",
                    "english_name": "Project",
                    "persian_name": "پروژه",
                },
                {
                    "value": "article",
                    "english_name": "Article",
                    "persian_name": "مقاله",
                },
                {
                    "value": "teaching_assistant",
                    "english_name": "Teaching Assistant",
                    "persian_name": "حل تمرین",
                },
                {
                    "value": "work_experience",
                    "english_name": "Work Experience",
                    "persian_name": "تجربه کاری",
                },
                {
                    "value": "laboratory_activity",
                    "english_name": "Laboratory Activity",
                    "persian_name": "فعالیت آزمایشگاهی",
                },
                {
                    "value": "other",
                    "english_name": "Other",
                    "persian_name": "سایر",
                },
            ],
        )

    def test_portfolio_item_rejects_unknown_type(self):
        response = self.client.post(
            "/api/profile/portfolio/",
            {"title": "Unsupported type", "item_type": "internship"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
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
            {"status": "ok", "message": "سرویس TeamUp فعال است."},
        )
