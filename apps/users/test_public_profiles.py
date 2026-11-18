from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

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
VALID_PASSWORD = "StrongPassword123!"


class PublicProfileAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.viewer = User.objects.create_user(
            email="viewer@example.com",
            password=VALID_PASSWORD,
            first_name="Current",
            last_name="Viewer",
        )
        self.client.force_authenticate(user=self.viewer)

        self.target = User.objects.create_user(
            email="target@example.com",
            password=VALID_PASSWORD,
            first_name="Ali",
            last_name="Ahmadi",
        )
        self.target.profile.bio = "Interested in academic research and teamwork."
        self.target.profile.github_url = "https://github.com/ali"
        self.target.profile.linkedin_url = "https://www.linkedin.com/in/ali"
        self.target.profile.university = "KNTU University"
        self.target.profile.major, _ = Major.objects.get_or_create(
            name="Computer Engineering"
        )
        self.target.profile.study_year = 2
        self.target.profile.start_year = 2023
        self.target.profile.graduation_year = 2028
        self.target.profile.is_currently_studying = True
        self.target.profile.weekly_available_hours = "15.50"
        self.target.profile.save()

        react, _ = Skill.objects.get_or_create(name="React")
        python, _ = Skill.objects.get_or_create(name="Python")
        UserSkill.objects.create(
            user=self.target,
            skill=react,
            proficiency_level=UserSkill.Proficiency.ADVANCED,
        )
        UserSkill.objects.create(
            user=self.target,
            skill=python,
            proficiency_level=UserSkill.Proficiency.INTERMEDIATE,
        )

        gis, _ = Interest.objects.get_or_create(name="GIS")
        robotics, _ = Interest.objects.get_or_create(name="Robotics")
        UserInterest.objects.create(user=self.target, interest=gis)
        UserInterest.objects.create(user=self.target, interest=robotics)
        PortfolioItem.objects.create(
            profile=self.target.profile,
            title="TeamUp project",
            description="Academic collaboration platform.",
            url="https://example.com/teamup",
            item_type=PortfolioItem.ItemType.PROJECT,
        )

    def test_public_detail_returns_public_profile_and_related_data_only(self):
        response = self.client.get(f"/api/users/{self.target.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data),
            {
                "id",
                "first_name",
                "last_name",
                "date_joined",
                "profile",
                "skills",
                "interests",
                "portfolio",
            },
        )
        self.assertEqual(response.data["profile"]["university"], "KNTU University")
        self.assertEqual(response.data["profile"]["major"], "Computer Engineering")
        self.assertEqual(
            response.data["profile"]["github_url"],
            "https://github.com/ali",
        )
        self.assertEqual(
            response.data["profile"]["linkedin_url"],
            "https://www.linkedin.com/in/ali",
        )
        self.assertEqual(response.data["profile"]["weekly_available_hours"], "15.50")
        self.assertEqual(response.data["profile"]["start_year"], 2023)
        self.assertEqual(response.data["profile"]["graduation_year"], 2028)
        self.assertTrue(response.data["profile"]["is_currently_studying"])
        self.assertNotIn("study_year", response.data["profile"])
        self.assertEqual(
            response.data["skills"],
            [
                {"name": "React", "proficiency_level": "advanced"},
                {"name": "Python", "proficiency_level": "intermediate"},
            ],
        )
        self.assertCountEqual(
            [interest["name"] for interest in response.data["interests"]],
            ["GIS", "Robotics"],
        )
        self.assertEqual(response.data["portfolio"][0]["title"], "TeamUp project")
        self.assertNotIn("email", response.data)
        self.assertNotIn("password", response.data)
        self.assertNotIn("is_staff", response.data)
        self.assertNotIn("is_superuser", response.data)
        self.assertNotIn("is_active", response.data)
        self.assertNotIn("access", response.data)

    def test_detail_returns_not_found_for_missing_or_inactive_users(self):
        missing_response = self.client.get("/api/users/999999/")
        self.assertEqual(missing_response.status_code, 404)

        self.target.is_active = False
        self.target.save(update_fields=("is_active",))
        inactive_response = self.client.get(f"/api/users/{self.target.pk}/")
        self.assertEqual(inactive_response.status_code, 404)

    def test_detail_handles_a_missing_profile_without_server_error(self):
        self.target.profile.delete()

        response = self.client.get(f"/api/users/{self.target.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["profile"])
        self.assertEqual(response.data["portfolio"], [])

    def test_public_endpoints_require_authentication(self):
        anonymous_client = APIClient()

        detail_response = anonymous_client.get(f"/api/users/{self.target.pk}/")
        list_response = anonymous_client.get("/api/users/")

        self.assertEqual(detail_response.status_code, 401)
        self.assertEqual(list_response.status_code, 401)


class PublicProfileSearchTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(
            email="search-viewer@example.com",
            password=VALID_PASSWORD,
            first_name="Viewer",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.viewer)

        self.alice = self._create_user(
            "alice@example.com",
            "Alice",
            "Smith",
            university="KNTU University",
            major="Computer Engineering",
            start_year=2019,
            bio="Building React tools for GIS research.",
        )
        self.bob = self._create_user(
            "bob@example.com",
            "Bob",
            "Jones",
            university="Tehran University",
            major="Biology",
            start_year=2021,
            bio="Interested in environmental studies.",
        )
        self.viewer.profile.university = "KNTU University"
        self.viewer.profile.save()

        react, _ = Skill.objects.get_or_create(name="React")
        react_native, _ = Skill.objects.get_or_create(name="React Native")
        UserSkill.objects.create(user=self.alice, skill=react)
        UserSkill.objects.create(user=self.alice, skill=react_native)

        gis, _ = Interest.objects.get_or_create(name="GIS")
        robotics, _ = Interest.objects.get_or_create(name="Robotics")
        UserInterest.objects.create(user=self.alice, interest=gis)
        UserInterest.objects.create(user=self.alice, interest=robotics)

        self.inactive = self._create_user(
            "inactive@example.com",
            "Inactive",
            "Student",
            university="KNTU",
            major="Computer Science",
            start_year=2019,
        )
        self.inactive.is_active = False
        self.inactive.save(update_fields=("is_active",))

        self.without_profile = self._create_user(
            "no-profile@example.com",
            "No",
            "Profile",
            university="KNTU",
            major="Computer Science",
            start_year=2019,
        )
        self.without_profile.profile.delete()

    @staticmethod
    def _create_user(email, first_name, last_name, **profile_fields):
        user = User.objects.create_user(
            email=email,
            password=VALID_PASSWORD,
            first_name=first_name,
            last_name=last_name,
        )
        for field, value in profile_fields.items():
            if field == "major":
                value, _ = Major.objects.get_or_create(name=value)
            setattr(user.profile, field, value)
        user.profile.save()
        return user

    def _ids(self, response):
        self.assertEqual(response.status_code, 200)
        return {result["id"] for result in response.data["results"]}

    def test_list_excludes_current_inactive_and_missing_profile_users(self):
        response = self.client.get("/api/users/")

        self.assertEqual(response.status_code, 200)
        returned_ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(returned_ids, {self.alice.pk, self.bob.pk})
        self.assertEqual(response.data["count"], 2)
        self.assertNotIn("email", response.data["results"][0])

    def test_general_search_matches_name_university_major_and_bio(self):
        for term in ("ali", "smith", "kntu", "engineering", "GIS research"):
            with self.subTest(term=term):
                response = self.client.get("/api/users/", {"search": term})
                self.assertEqual(self._ids(response), {self.alice.pk})

    def test_individual_filters_match_case_insensitively(self):
        cases = (
            ({"university": "kNtU"}, self.alice.pk),
            ({"major": "computer"}, self.alice.pk),
            ({"start_year": "2019"}, self.alice.pk),
            ({"skill": "reaCt"}, self.alice.pk),
            ({"interest": "gIs"}, self.alice.pk),
        )
        for params, expected_id in cases:
            with self.subTest(params=params):
                response = self.client.get("/api/users/", params)
                self.assertEqual(self._ids(response), {expected_id})

    def test_filters_combine_and_duplicate_matches_are_removed(self):
        response = self.client.get(
            "/api/users/",
            {
                "university": "KNTU",
                "major": "Computer",
                "start_year": "2019",
                "skill": "React",
                "interest": "o",
            },
        )

        self.assertEqual(self._ids(response), {self.alice.pk})
        self.assertEqual(response.data["count"], 1)

    def test_invalid_start_year_is_rejected(self):
        for value in ("invalid", "0", "-1", "2.5"):
            with self.subTest(value=value):
                response = self.client.get("/api/users/", {"start_year": value})
                self.assertEqual(response.status_code, 400)

    def test_pagination_defaults_to_ten_and_caps_page_size_at_fifty(self):
        for index in range(51):
            self._create_user(
                f"page-{index}@example.com",
                f"Student{index}",
                "Tester",
                university="Pagination University",
            )

        default_response = self.client.get("/api/users/")
        self.assertEqual(default_response.status_code, 200)
        self.assertEqual(len(default_response.data["results"]), 10)
        self.assertEqual(default_response.data["count"], 53)
        self.assertIsNotNone(default_response.data["next"])
        self.assertIsNone(default_response.data["previous"])

        custom_response = self.client.get("/api/users/?page=2&page_size=20")
        self.assertEqual(custom_response.status_code, 200)
        self.assertEqual(len(custom_response.data["results"]), 20)
        self.assertIsNotNone(custom_response.data["previous"])

        capped_response = self.client.get("/api/users/?page_size=100")
        self.assertEqual(capped_response.status_code, 200)
        self.assertEqual(len(capped_response.data["results"]), 50)

    def test_openapi_documents_search_and_pagination_parameters(self):
        response = self.client.get("/api/schema/")

        self.assertEqual(response.status_code, 200)
        operation = response.data["paths"]["/api/users/"]["get"]
        parameter_names = {item["name"] for item in operation["parameters"]}
        self.assertTrue(
            {
                "search",
                "university",
                "major",
                "start_year",
                "skill",
                "interest",
                "page",
                "page_size",
            }.issubset(parameter_names)
        )
        self.assertEqual(
            operation["responses"]["200"]["content"]["application/json"]["schema"][
                "$ref"
            ],
            "#/components/schemas/PaginatedPublicProfileSummaryList",
        )

        detail_properties = response.data["components"]["schemas"][
            "PublicProfileDetail"
        ]["properties"]
        self.assertTrue(
            {
                "id",
                "first_name",
                "last_name",
                "date_joined",
                "profile",
                "skills",
                "interests",
                "portfolio",
            }.issubset(detail_properties)
        )
        self.assertNotIn("email", detail_properties)
        self.assertNotIn("password", detail_properties)
