from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from config.views import HealthCheckView
from apps.users.urls import urlpatterns as user_urlpatterns
from apps.users.views import (
    AvailableInterestListView,
    AvailableMajorListView,
    AvailableSkillListView,
    PortfolioItemTypeListView,
)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include(user_urlpatterns)),
    path("api/account/", include("apps.users.account_urls")),
    path("api/profile/", include("apps.users.profile_urls")),
    path("api/users/", include("apps.users.public_urls")),
    path("api/skills/", AvailableSkillListView.as_view(), name="available-skills"),
    path("api/interests/", AvailableInterestListView.as_view(), name="available-interests"),
    path("api/majors/", AvailableMajorListView.as_view(), name="available-majors"),
    path(
        "api/portfolio-item-types/",
        PortfolioItemTypeListView.as_view(),
        name="portfolio-item-types",
    ),
    path("api/health/", HealthCheckView.as_view(), name="health"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
]
