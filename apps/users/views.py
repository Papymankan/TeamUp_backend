import logging
from smtplib import SMTPException
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    Interest,
    PortfolioItem,
    Profile,
    Skill,
    UserInterest,
    UserSkill,
)
from .pagination import PublicProfilePagination
from .serializers import (
    AccountSerializer,
    InterestSerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PortfolioItemSerializer,
    ProfileSerializer,
    PublicProfileDetailSerializer,
    PublicProfileSearchSerializer,
    PublicProfileSummarySerializer,
    RegistrationSerializer,
    SkillSerializer,
    UserInterestSerializer,
    UserSkillSerializer,
)


User = get_user_model()
logger = logging.getLogger(__name__)


class AuthenticationResponseSerializer(serializers.Serializer):
    user = AccountSerializer()
    access = serializers.CharField()
    refresh = serializers.CharField()


class DetailResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


def token_response(user):
    refresh = RefreshToken.for_user(user)
    return {
        "user": AccountSerializer(user).data,
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


class RegistrationView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=RegistrationSerializer,
        responses={201: AuthenticationResponseSerializer},
    )
    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(token_response(user), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=LoginSerializer,
        responses={200: AuthenticationResponseSerializer},
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return Response(token_response(serializer.validated_data["user"]))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=LogoutSerializer,
        responses={200: DetailResponseSerializer},
    )
    def post(self, request):
        serializer = LogoutSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.validated_data["refresh"].blacklist()
        return Response({"detail": "Successfully logged out."})


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=PasswordResetRequestSerializer,
        responses={200: DetailResponseSerializer},
    )
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        response_data = {
            "detail": (
                "If an account exists for that email, password reset "
                "instructions will be sent."
            )
        }

        if not settings.FRONTEND_URL:
            logger.warning(
                "Password reset email not sent because FRONTEND_URL is "
                "unavailable or invalid."
            )
            return Response(response_data)

        users = User.objects.filter(email__iexact=email, is_active=True).order_by("pk")
        for user in users:
            if not user.has_usable_password():
                continue
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = (
                f"{settings.FRONTEND_URL.rstrip('/')}/reset-password/confirm/"
                f"?{urlencode({'uid': uid, 'token': token})}"
            )
            try:
                send_mail(
                    subject="Reset your TeamUp password",
                    message=(
                        "Use the following link to reset your TeamUp password. "
                        "If you did not request this, you can ignore this email.\n\n"
                        f"{reset_url}"
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
            except (SMTPException, OSError) as error:
                logger.error(
                    "Password reset email delivery failed for user_id=%s "
                    "(error_type=%s).",
                    user.pk,
                    type(error).__name__,
                )

        return Response(response_data)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=PasswordResetConfirmSerializer,
        responses={200: DetailResponseSerializer},
    )
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Password has been reset successfully."})


class AccountView(generics.RetrieveUpdateAPIView):
    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ProfileSerializer})
    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        return Response(ProfileSerializer(profile).data)

    @extend_schema(request=ProfileSerializer, responses={200: ProfileSerializer})
    def patch(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class AvailableSkillListView(generics.ListAPIView):
    serializer_class = SkillSerializer
    permission_classes = [AllowAny]
    queryset = Skill.objects.all().order_by("name")


class UserSkillListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: UserSkillSerializer(many=True)})
    def get(self, request):
        user_skills = UserSkill.objects.filter(user=request.user).select_related("skill")
        serializer = UserSkillSerializer(user_skills, many=True, context={"request": request})
        return Response(serializer.data)

    @extend_schema(
        request=UserSkillSerializer,
        responses={200: UserSkillSerializer, 201: UserSkillSerializer},
    )
    def post(self, request):
        serializer = UserSkillSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user_skill = serializer.save()
        status_code = status.HTTP_201_CREATED if getattr(serializer, "created", False) else status.HTTP_200_OK
        return Response(
            UserSkillSerializer(user_skill, context={"request": request}).data,
            status=status_code,
        )


class UserSkillDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request, skill_id):
        user_skill = get_object_or_404(UserSkill, user=request.user, skill_id=skill_id)
        user_skill.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AvailableInterestListView(generics.ListAPIView):
    serializer_class = InterestSerializer
    permission_classes = [AllowAny]
    queryset = Interest.objects.all().order_by("name")


class UserInterestListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: UserInterestSerializer(many=True)})
    def get(self, request):
        user_interests = UserInterest.objects.filter(user=request.user).select_related("interest")
        serializer = UserInterestSerializer(user_interests, many=True, context={"request": request})
        return Response(serializer.data)

    @extend_schema(
        request=UserInterestSerializer,
        responses={200: UserInterestSerializer, 201: UserInterestSerializer},
    )
    def post(self, request):
        serializer = UserInterestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user_interest = serializer.save()
        status_code = status.HTTP_201_CREATED if getattr(serializer, "created", False) else status.HTTP_200_OK
        return Response(
            UserInterestSerializer(user_interest, context={"request": request}).data,
            status=status_code,
        )


class UserInterestDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request, interest_id):
        user_interest = get_object_or_404(UserInterest, user=request.user, interest_id=interest_id)
        user_interest.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PortfolioItemListCreateView(generics.ListCreateAPIView):
    serializer_class = PortfolioItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return PortfolioItem.objects.filter(profile__user=self.request.user).order_by("-created_at")


PUBLIC_PROFILE_SEARCH_PARAMETERS = [
    OpenApiParameter("search", str, OpenApiParameter.QUERY, description="Case-insensitive name, university, major, or bio search."),
    OpenApiParameter("university", str, OpenApiParameter.QUERY, description="Case-insensitive partial university match."),
    OpenApiParameter("major", str, OpenApiParameter.QUERY, description="Case-insensitive partial major match."),
    OpenApiParameter("study_year", int, OpenApiParameter.QUERY, description="Filter by positive study year."),
    OpenApiParameter("skill", str, OpenApiParameter.QUERY, description="Case-insensitive partial skill-name match."),
    OpenApiParameter("interest", str, OpenApiParameter.QUERY, description="Case-insensitive partial interest-name match."),
    OpenApiParameter("page", int, OpenApiParameter.QUERY, description="Page number."),
    OpenApiParameter("page_size", int, OpenApiParameter.QUERY, description="Results per page, up to 50."),
]


class PublicProfileListView(generics.ListAPIView):
    serializer_class = PublicProfileSummarySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = PublicProfilePagination

    @extend_schema(
        parameters=PUBLIC_PROFILE_SEARCH_PARAMETERS,
        responses={200: PublicProfileSummarySerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        filters = PublicProfileSearchSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        values = filters.validated_data

        queryset = (
            User.objects.filter(is_active=True, profile__isnull=False)
            .exclude(pk=self.request.user.pk)
            .select_related("profile")
            .prefetch_related("user_skills__skill", "user_interests__interest")
        )

        search = values.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(profile__university__icontains=search)
                | Q(profile__major__icontains=search)
                | Q(profile__bio__icontains=search)
            )

        university = values.get("university", "").strip()
        if university:
            queryset = queryset.filter(profile__university__icontains=university)

        major = values.get("major", "").strip()
        if major:
            queryset = queryset.filter(profile__major__icontains=major)

        if "study_year" in values:
            queryset = queryset.filter(profile__study_year=values["study_year"])

        skill = values.get("skill", "").strip()
        if skill:
            queryset = queryset.filter(user_skills__skill__name__icontains=skill)

        interest = values.get("interest", "").strip()
        if interest:
            queryset = queryset.filter(user_interests__interest__name__icontains=interest)

        return queryset.distinct().order_by("id")


class PublicProfileDetailView(generics.RetrieveAPIView):
    serializer_class = PublicProfileDetailSerializer
    permission_classes = [IsAuthenticated]
    queryset = (
        User.objects.filter(is_active=True)
        .select_related("profile")
        .prefetch_related(
            "user_skills__skill",
            "user_interests__interest",
            "profile__portfolio_items",
        )
    )

    @extend_schema(responses={200: PublicProfileDetailSerializer})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def perform_create(self, serializer):
        profile, _ = Profile.objects.get_or_create(user=self.request.user)
        serializer.save()


class PortfolioItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PortfolioItemSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return PortfolioItem.objects.filter(profile__user=self.request.user).order_by("-created_at")
