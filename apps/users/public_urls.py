from django.urls import path

from .views import PublicProfileDetailView, PublicProfileListView

urlpatterns = [
    path("", PublicProfileListView.as_view(), name="public-profile-list"),
    path("<int:pk>/", PublicProfileDetailView.as_view(), name="public-profile-detail"),
]
