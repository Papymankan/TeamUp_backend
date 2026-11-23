from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.opportunities.models import Opportunity
from apps.users.pagination import PublicProfilePagination
from .email_utils import send_application_status_email
from .models import Application
from .serializers import (
    ApplicationCreateSerializer,
    MyApplicationSerializer,
    OpportunityApplicationSerializer,
)


class ApplyToOpportunityView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ApplicationCreateSerializer

    @extend_schema(
        request=ApplicationCreateSerializer,
        responses={201: MyApplicationSerializer},
    )
    def post(self, request, pk):
        serializer = ApplicationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                opportunity = get_object_or_404(
                    Opportunity.objects.select_for_update(),
                    pk=pk,
                )
                if opportunity.status != Opportunity.Status.PUBLISHED:
                    raise serializers.ValidationError(
                        {"opportunity": "فقط فرصت‌های منتشرشده درخواست می‌پذیرند."}
                    )
                if opportunity.owner_id == request.user.pk:
                    raise serializers.ValidationError(
                        {
                            "opportunity": (
                                "نمی‌توانید برای فرصت خودتان درخواست ارسال کنید."
                            )
                        }
                    )
                if Application.objects.filter(
                    opportunity=opportunity,
                    applicant=request.user,
                ).exists():
                    raise serializers.ValidationError(
                        {"detail": "برای این فرصت قبلاً درخواست ارسال کرده‌اید."}
                    )
                application = Application.objects.create(
                    opportunity=opportunity,
                    applicant=request.user,
                    message=serializer.validated_data.get("message"),
                )
        except IntegrityError as error:
            if Application.objects.filter(
                opportunity=opportunity,
                applicant=request.user,
            ).exists():
                raise serializers.ValidationError(
                    {"detail": "برای این فرصت قبلاً درخواست ارسال کرده‌اید."}
                ) from error
            raise

        return Response(
            MyApplicationSerializer(
                application,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )


class MyApplicationListView(generics.ListAPIView):
    serializer_class = MyApplicationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = PublicProfilePagination

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status",
                str,
                OpenApiParameter.QUERY,
                description="pending, accepted, rejected, or withdrawn.",
            ),
            OpenApiParameter("page", int, OpenApiParameter.QUERY),
            OpenApiParameter("page_size", int, OpenApiParameter.QUERY),
        ],
        responses={200: MyApplicationSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Application.objects.filter(
            applicant=self.request.user,
        ).select_related("opportunity")
        status_value = self.request.query_params.get("status")
        if status_value:
            if status_value not in Application.Status.values:
                raise serializers.ValidationError(
                    {"status": "وضعیت درخواست معتبر نیست."}
                )
            queryset = queryset.filter(status=status_value)
        return queryset.order_by("-applied_at")


class OpportunityApplicantListView(generics.ListAPIView):
    serializer_class = OpportunityApplicationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = PublicProfilePagination

    @extend_schema(
        parameters=[
            OpenApiParameter("page", int, OpenApiParameter.QUERY),
            OpenApiParameter("page_size", int, OpenApiParameter.QUERY),
        ],
        responses={200: OpportunityApplicationSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        opportunity = get_object_or_404(
            Opportunity.objects.only("id", "owner_id"),
            pk=self.kwargs["pk"],
        )
        if opportunity.owner_id != self.request.user.pk:
            raise PermissionDenied("فقط صاحب فرصت می‌تواند درخواست‌های آن را ببیند.")
        return (
            Application.objects.filter(opportunity=opportunity)
            .select_related("applicant")
            .order_by("-applied_at")
        )


class ApplicationStatusActionView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MyApplicationSerializer
    action = None

    def post(self, request, pk):
        with transaction.atomic():
            application = get_object_or_404(
                Application.objects.select_for_update().select_related(
                    "opportunity",
                    "applicant",
                ),
                pk=pk,
            )
            opportunity = get_object_or_404(
                Opportunity.objects.select_for_update(),
                pk=application.opportunity_id,
            )

            if self.action == Application.Status.WITHDRAWN:
                if application.applicant_id != request.user.pk:
                    raise PermissionDenied("فقط صاحب درخواست می‌تواند آن را پس بگیرد.")
            elif opportunity.owner_id != request.user.pk:
                raise PermissionDenied(
                    "فقط صاحب فرصت می‌تواند وضعیت درخواست را تغییر دهد."
                )

            if application.status != Application.Status.PENDING:
                raise serializers.ValidationError(
                    {"status": "فقط درخواست‌های در انتظار قابل تغییر هستند."}
                )
            if (
                self.action == Application.Status.ACCEPTED
                and opportunity.status != Opportunity.Status.PUBLISHED
            ):
                raise serializers.ValidationError(
                    {"opportunity": "فقط درخواست‌های فرصت منتشرشده قابل پذیرش هستند."}
                )

            application.status = self.action
            application.save(update_fields=["status", "status_updated_at"])
            if self.action in (
                Application.Status.ACCEPTED,
                Application.Status.REJECTED,
            ):
                transaction.on_commit(
                    lambda application_id=application.pk, target=self.action: (
                        send_application_status_email(application_id, target)
                    ),
                    robust=True,
                )
        return Response(
            MyApplicationSerializer(
                application,
                context={"request": request},
            ).data
        )


class ApplicationWithdrawView(ApplicationStatusActionView):
    action = Application.Status.WITHDRAWN


class ApplicationAcceptView(ApplicationStatusActionView):
    action = Application.Status.ACCEPTED


class ApplicationRejectView(ApplicationStatusActionView):
    action = Application.Status.REJECTED
