from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import Application
from apps.users.pagination import PublicProfilePagination
from .models import Opportunity
from .serializers import (
    OpportunityCreateSerializer,
    OpportunityDetailSerializer,
    OpportunityFilterSerializer,
    OpportunitySerializer,
    OpportunityUpdateSerializer,
)


def parse_id_filter(value):
    if not value:
        return []
    values = value if isinstance(value, (list, tuple)) else [value]
    ids = []
    for group in values:
        for item in str(group).split(","):
            item = item.strip()
            if not item:
                raise serializers.ValidationError("شناسه‌ها باید اعداد صحیح باشند.")
            try:
                parsed = int(item)
            except (TypeError, ValueError) as error:
                raise serializers.ValidationError(
                    "شناسه‌ها باید اعداد صحیح باشند."
                ) from error
            if parsed < 1:
                raise serializers.ValidationError("شناسه‌ها باید اعداد مثبت باشند.")
            ids.append(parsed)
    return ids


OPPORTUNITY_FILTER_PARAMETERS = [
    OpenApiParameter("search", str, OpenApiParameter.QUERY, description="Search title or description."),
    OpenApiParameter("category", str, OpenApiParameter.QUERY, description="Portfolio category value."),
    OpenApiParameter("skills", str, OpenApiParameter.QUERY, description="Comma-separated skill IDs."),
    OpenApiParameter("interests", str, OpenApiParameter.QUERY, description="Comma-separated interest IDs."),
    OpenApiParameter("min_hours", float, OpenApiParameter.QUERY, description="Minimum weekly hours."),
    OpenApiParameter("max_hours", float, OpenApiParameter.QUERY, description="Maximum weekly hours."),
    OpenApiParameter("page", int, OpenApiParameter.QUERY),
    OpenApiParameter("page_size", int, OpenApiParameter.QUERY),
]


class OpportunityListCreateView(generics.ListCreateAPIView):
    pagination_class = PublicProfilePagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return [AllowAny()]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return OpportunityCreateSerializer
        return OpportunitySerializer

    def get_queryset(self):
        queryset = Opportunity.objects.filter(status=Opportunity.Status.PUBLISHED)
        filters = OpportunityFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        values = filters.validated_data

        search = values.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(description__icontains=search)
            )
        if "category" in values:
            queryset = queryset.filter(category=values["category"])

        skill_values = self.request.query_params.getlist("skills")
        if skill_values:
            skill_ids = parse_id_filter(skill_values)
            if skill_ids:
                queryset = queryset.filter(skills__id__in=skill_ids)

        interest_values = self.request.query_params.getlist("interests")
        if interest_values:
            interest_ids = parse_id_filter(interest_values)
            if interest_ids:
                queryset = queryset.filter(interests__id__in=interest_ids)

        if "min_hours" in values:
            queryset = queryset.filter(
                weekly_time_commitment_hours__gte=values["min_hours"]
            )
        if "max_hours" in values:
            queryset = queryset.filter(
                weekly_time_commitment_hours__lte=values["max_hours"]
            )
        if "status" in values:
            raise serializers.ValidationError(
                {"status": "وضعیت در فهرست عمومی قابل‌فیلتر نیست."}
            )

        return (
            queryset.select_related("owner")
            .prefetch_related("skills", "interests")
            .distinct()
            .order_by("-created_at")
        )

    @extend_schema(
        parameters=OPPORTUNITY_FILTER_PARAMETERS,
        responses={200: OpportunitySerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=OpportunityCreateSerializer,
        responses={201: OpportunitySerializer},
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        response = OpportunitySerializer(
            serializer.instance,
            context={"request": request},
        )
        return Response(response.data, status=status.HTTP_201_CREATED, headers=headers)


class OpportunityMineView(generics.ListAPIView):
    serializer_class = OpportunitySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = PublicProfilePagination

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status",
                str,
                OpenApiParameter.QUERY,
                description="draft, published, or closed.",
            ),
            OpenApiParameter("page", int, OpenApiParameter.QUERY),
            OpenApiParameter("page_size", int, OpenApiParameter.QUERY),
        ],
        responses={200: OpportunitySerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Opportunity.objects.filter(owner=self.request.user)
        status_value = self.request.query_params.get("status")
        if status_value:
            if status_value not in Opportunity.Status.values:
                raise serializers.ValidationError(
                    {"status": "وضعیت باید draft، published یا closed باشد."}
                )
            queryset = queryset.filter(status=status_value)
        return (
            queryset.select_related("owner")
            .prefetch_related("skills", "interests")
            .order_by("-created_at")
        )


class OpportunityDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Opportunity.objects.select_related("owner").prefetch_related(
        "skills",
        "interests",
    )
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return OpportunityUpdateSerializer
        if self.request.method == "GET":
            return OpportunityDetailSerializer
        return OpportunitySerializer

    def get_object(self):
        opportunity = get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        if self.request.method == "PATCH" or self.request.method == "DELETE":
            if (
                not getattr(self.request.user, "is_authenticated", False)
                or opportunity.owner_id != self.request.user.pk
            ):
                raise PermissionDenied("فقط صاحب فرصت می‌تواند آن را ویرایش یا حذف کند.")
            return opportunity
        elif opportunity.status == Opportunity.Status.PUBLISHED:
            return opportunity
        elif (
            getattr(self.request.user, "is_authenticated", False)
            and opportunity.owner_id == self.request.user.pk
        ):
            return opportunity
        elif (
            opportunity.status == Opportunity.Status.CLOSED
            and getattr(self.request.user, "is_authenticated", False)
            and Application.objects.filter(
                opportunity=opportunity,
                applicant=self.request.user,
            ).exists()
        ):
            return opportunity
        raise Http404

    def destroy(self, request, *args, **kwargs):
        opportunity = self.get_object()
        if opportunity.applications.exists():
            return Response(
                {
                    "detail": (
                        "این فرصت دارای درخواست‌های ارسال‌شده است و به‌منظور "
                        "حفظ داده‌ها قابل حذف نیست."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        opportunity = self.get_object()
        serializer = self.get_serializer(
            opportunity,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        response = OpportunitySerializer(
            serializer.instance,
            context={"request": request},
        )
        return Response(response.data)


class OpportunityPublishView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OpportunitySerializer

    @extend_schema(responses={200: OpportunitySerializer})
    def post(self, request, pk):
        opportunity = get_object_or_404(
            Opportunity.objects.select_related("owner").prefetch_related("skills", "interests"),
            pk=pk,
        )
        if opportunity.owner_id != request.user.pk:
            raise PermissionDenied("فقط صاحب فرصت می‌تواند آن را منتشر کند.")
        if opportunity.status not in (
            Opportunity.Status.DRAFT,
            Opportunity.Status.CLOSED,
        ):
            return Response(
                {"detail": "فقط فرصت‌های پیش‌نویس یا بسته قابل انتشار هستند."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not opportunity.title.strip():
            return Response(
                {"title": "برای انتشار، عنوان فرصت الزامی است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if opportunity.category not in PortfolioCategories():
            return Response(
                {"category": "دسته‌بندی فرصت معتبر نیست."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        opportunity.status = Opportunity.Status.PUBLISHED
        opportunity.published_at = now
        opportunity.closed_at = None
        opportunity.save(update_fields=["status", "published_at", "closed_at", "updated_at"])
        return Response(
            OpportunitySerializer(opportunity, context={"request": request}).data
        )


def PortfolioCategories():
    from apps.users.models import PortfolioItem

    return dict(PortfolioItem.ItemType.choices).keys()


class OpportunityCloseView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OpportunitySerializer

    @extend_schema(responses={200: OpportunitySerializer})
    def post(self, request, pk):
        opportunity = get_object_or_404(
            Opportunity.objects.select_related("owner").prefetch_related("skills", "interests"),
            pk=pk,
        )
        if opportunity.owner_id != request.user.pk:
            raise PermissionDenied("فقط صاحب فرصت می‌تواند آن را ببندد.")
        if opportunity.status != Opportunity.Status.PUBLISHED:
            return Response(
                {"detail": "فقط فرصت‌های منتشرشده قابل بستن هستند."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        opportunity.status = Opportunity.Status.CLOSED
        opportunity.closed_at = timezone.now()
        opportunity.save(update_fields=["status", "closed_at", "updated_at"])
        return Response(
            OpportunitySerializer(opportunity, context={"request": request}).data
        )
