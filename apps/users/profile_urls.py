from django.urls import path

from .views import (
    PortfolioItemDetailView,
    PortfolioItemListCreateView,
    ProfileView,
    UserInterestDetailView,
    UserInterestListCreateView,
    UserSkillDetailView,
    UserSkillListCreateView,
)

urlpatterns = [
    path("", ProfileView.as_view(), name="profile"),
    path("skills/", UserSkillListCreateView.as_view(), name="profile-skills"),
    path("skills/<int:skill_id>/", UserSkillDetailView.as_view(), name="profile-skill-detail"),
    path("interests/", UserInterestListCreateView.as_view(), name="profile-interests"),
    path(
        "interests/<int:interest_id>/",
        UserInterestDetailView.as_view(),
        name="profile-interest-detail",
    ),
    path("portfolio/", PortfolioItemListCreateView.as_view(), name="profile-portfolio"),
    path(
        "portfolio/<int:pk>/",
        PortfolioItemDetailView.as_view(),
        name="profile-portfolio-detail",
    ),
]
