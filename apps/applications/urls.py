from django.urls import path

from .views import (
    ApplicationAcceptView,
    ApplicationRejectView,
    ApplicationWithdrawView,
    MyApplicationListView,
)


urlpatterns = [
    path("mine/", MyApplicationListView.as_view(), name="application-mine"),
    path(
        "<int:pk>/withdraw/",
        ApplicationWithdrawView.as_view(),
        name="application-withdraw",
    ),
    path(
        "<int:pk>/accept/",
        ApplicationAcceptView.as_view(),
        name="application-accept",
    ),
    path(
        "<int:pk>/reject/",
        ApplicationRejectView.as_view(),
        name="application-reject",
    ),
]
