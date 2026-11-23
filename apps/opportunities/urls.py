from django.urls import path

from .views import (
    OpportunityCloseView,
    OpportunityDetailView,
    OpportunityListCreateView,
    OpportunityMineView,
    OpportunityPublishView,
)
from apps.applications.views import ApplyToOpportunityView, OpportunityApplicantListView


urlpatterns = [
    path("", OpportunityListCreateView.as_view(), name="opportunity-list"),
    path("mine/", OpportunityMineView.as_view(), name="opportunity-mine"),
    path(
        "<int:pk>/apply/",
        ApplyToOpportunityView.as_view(),
        name="opportunity-apply",
    ),
    path(
        "<int:pk>/applications/",
        OpportunityApplicantListView.as_view(),
        name="opportunity-applications",
    ),
    path("<int:pk>/", OpportunityDetailView.as_view(), name="opportunity-detail"),
    path("<int:pk>/publish/", OpportunityPublishView.as_view(), name="opportunity-publish"),
    path("<int:pk>/close/", OpportunityCloseView.as_view(), name="opportunity-close"),
]
