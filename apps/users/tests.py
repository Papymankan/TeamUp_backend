from decimal import Decimal

from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

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
