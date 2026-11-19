import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.cache import cache
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .email_utils import password_reset_expiration_message, send_auth_email
from .models import (
    Interest,
    Major,
    PortfolioItem,
    Profile,
    Skill,
    UserInterest,
    UserSkill,
)
from .pagination import PublicProfilePagination
from .serializers import (
    AccountSerializer,
    EmailVerificationResendSerializer,
    EmailVerificationTokenSerializer,
    InterestSerializer,
    LoginSerializer,
    LogoutSerializer,
    MajorSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PortfolioItemSerializer,
    PortfolioItemTypeSerializer,
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
EMAIL_VERIFICATION_SALT = "users.email_verification"
EMAIL_VERIFICATION_MAX_AGE = 24 * 60 * 60
EMAIL_VERIFICATION_RESEND_COOLDOWN = 5 * 60


class AuthenticationResponseSerializer(serializers.Serializer):
    user = AccountSerializer()
    access = serializers.CharField()
    refresh = serializers.CharField()


class DetailResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


def token_response(user):
    if not user.is_active:
        raise serializers.ValidationError(
            "برای ورود ابتدا نشانی ایمیل خود را تأیید کنید."
        )
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
        responses={201: DetailResponseSerializer},
    )
    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        send_verification_email(user)
        logger.info("User registration completed user_id=%s", user.pk)
        return Response(
            {
                "detail": (
                    "ثبت‌نام انجام شد. برای ورود، نشانی ایمیل خود را از طریق "
                    "پیوند ارسالی تأیید کنید. اگر ایمیل را دریافت نکردید، "
                    "می‌توانید درخواست ارسال مجدد دهید."
                )
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=LoginSerializer,
        responses={200: AuthenticationResponseSerializer},
        description=(
            "Only active (email-verified) accounts can receive access and "
            "refresh tokens."
        ),
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        logger.info("User login succeeded user_id=%s", user.pk)
        return Response(token_response(user))


def send_verification_email(user):
    if not settings.FRONTEND_URL:
        logger.warning(
            "Verification email not sent because FRONTEND_URL is unavailable "
            "or invalid."
        )
        return False

    token = signing.dumps(
        {"user_id": user.pk, "email": user.email},
        salt=EMAIL_VERIFICATION_SALT,
        compress=True,
    )
    verification_url = (
        f"{settings.FRONTEND_URL.rstrip('/')}/verify-email/"
        f"?{urlencode({'token': token})}"
    )
    return send_auth_email(
        user=user,
        subject="تأیید نشانی ایمیل در TeamUp",
        purpose="Email verification",
        template_context={
            "heading": "تأیید نشانی ایمیل",
            "introduction": (
                "ثبت‌نام شما در TeamUp با موفقیت انجام شد. برای فعال‌کردن "
                "حساب و استفاده از برنامه، نشانی ایمیل خود را با انتخاب "
                "دکمه زیر تأیید کنید."
            ),
            "button_label": "تأیید ایمیل",
            "action_url": verification_url,
            "expiration_message": (
                "این پیوند تا ۲۴ ساعت پس از ارسال معتبر است."
            ),
            "note": (
                "اگر شما در TeamUp ثبت‌نام نکرده‌اید، می‌توانید این ایمیل "
                "را نادیده بگیرید."
            ),
        },
    )


class EmailVerificationView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=EmailVerificationTokenSerializer,
        responses={
            200: DetailResponseSerializer,
            400: OpenApiResponse(description="Verification token is invalid or expired."),
        },
    )
    def post(self, request):
        serializer = EmailVerificationTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payload = signing.loads(
                serializer.validated_data["token"],
                salt=EMAIL_VERIFICATION_SALT,
                max_age=EMAIL_VERIFICATION_MAX_AGE,
            )
            user = User.objects.get(
                pk=payload["user_id"],
                email=payload["email"],
            )
        except (
            signing.BadSignature,
            KeyError,
            TypeError,
            ValueError,
            User.DoesNotExist,
        ) as error:
            raise serializers.ValidationError(
                {"token": "پیوند تأیید ایمیل نامعتبر یا منقضی شده است."}
            ) from error

        if user.is_active:
            return Response(
                {"detail": "نشانی ایمیل این حساب قبلاً تأیید شده است."}
            )

        user.is_active = True
        user.save(update_fields=("is_active",))
        logger.info("User email verified user_id=%s", user.pk)
        return Response(
            {"detail": "نشانی ایمیل با موفقیت تأیید شد. اکنون می‌توانید وارد شوید."}
        )


class EmailVerificationResendView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "email_verification_resend"

    @extend_schema(
        request=EmailVerificationResendSerializer,
        responses={
            200: DetailResponseSerializer,
            429: OpenApiResponse(description="Resend rate limit exceeded."),
        },
    )
    def post(self, request):
        serializer = EmailVerificationResendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        response_data = {
            "detail": (
                "اگر حسابی با این نشانی نیازمند تأیید باشد، پیوند تازه‌ای "
                "برای شما ارسال خواهد شد."
            )
        }

        user = User.objects.filter(email__iexact=email, is_active=False).first()
        if user is None:
            return Response(response_data)
        if not settings.FRONTEND_URL:
            logger.warning(
                "Verification email not sent because FRONTEND_URL is unavailable "
                "or invalid."
            )
            return Response(response_data)

        cooldown_key = f"teamup_email_verification_resend:{user.pk}"
        if not cache.add(
            cooldown_key,
            "1",
            timeout=EMAIL_VERIFICATION_RESEND_COOLDOWN,
        ):
            return Response(response_data)

        if not send_verification_email(user):
            cache.delete(cooldown_key)
        return Response(response_data)


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
        logger.info("User logout completed user_id=%s", request.user.pk)
        return Response({"detail": "با موفقیت از حساب کاربری خارج شدید."})


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
                "اگر حساب کاربری فعالی با این ایمیل وجود داشته باشد، "
                "راهنمای بازنشانی گذرواژه برای شما ارسال خواهد شد."
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
            send_auth_email(
                user=user,
                subject="بازنشانی گذرواژه TeamUp",
                purpose="Password reset",
                template_context={
                    "heading": "تغییر رمز عبور",
                    "introduction": (
                        "درخواست تغییر رمز عبور حساب TeamUp شما دریافت شد. "
                        "برای انتخاب رمز عبور جدید، دکمه زیر را انتخاب کنید."
                    ),
                    "button_label": "تغییر رمز عبور",
                    "action_url": reset_url,
                    "expiration_message": password_reset_expiration_message(
                        settings.PASSWORD_RESET_TIMEOUT
                    ),
                    "note": (
                        "اگر شما این درخواست را ثبت نکرده‌اید، می‌توانید این "
                        "ایمیل را نادیده بگیرید."
                    ),
                },
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
        logger.info(
            "Password reset completed user_id=%s",
            serializer.validated_data["user"].pk,
        )
        return Response({"detail": "گذرواژه با موفقیت بازنشانی شد."})


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
        logger.info("Profile updated user_id=%s", request.user.pk)
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


class AvailableMajorListView(generics.ListAPIView):
    serializer_class = MajorSerializer
    permission_classes = [AllowAny]
    queryset = Major.objects.all().order_by("name")


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


class PortfolioItemTypeListView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses={200: PortfolioItemTypeSerializer(many=True)})
    def get(self, request):
        persian_names = {
            PortfolioItem.ItemType.PROJECT: "پروژه",
            PortfolioItem.ItemType.ARTICLE: "مقاله",
            PortfolioItem.ItemType.TEACHING_ASSISTANT: "حل تمرین",
            PortfolioItem.ItemType.WORK_EXPERIENCE: "تجربه کاری",
            PortfolioItem.ItemType.LABORATORY_ACTIVITY: "فعالیت آزمایشگاهی",
            PortfolioItem.ItemType.OTHER: "سایر",
        }
        return Response(
            [
                {
                    "value": value,
                    "english_name": english_name,
                    "persian_name": persian_names[value],
                }
                for value, english_name in PortfolioItem.ItemType.choices
            ]
        )


PUBLIC_PROFILE_SEARCH_PARAMETERS = [
    OpenApiParameter("search", str, OpenApiParameter.QUERY, description="Case-insensitive name, university, major, or bio search."),
    OpenApiParameter("university", str, OpenApiParameter.QUERY, description="Case-insensitive partial university match."),
    OpenApiParameter("major", str, OpenApiParameter.QUERY, description="Case-insensitive partial major match."),
    OpenApiParameter("start_year", int, OpenApiParameter.QUERY, description="Filter by calendar start year."),
    OpenApiParameter("skill", str, OpenApiParameter.QUERY, description="Case-insensitive partial skill-name match."),
    OpenApiParameter("interest", str, OpenApiParameter.QUERY, description="Case-insensitive partial interest-name match."),
    OpenApiParameter("page", int, OpenApiParameter.QUERY, description="Page number."),
    OpenApiParameter("page_size", int, OpenApiParameter.QUERY, description="Results per page, up to 50."),
]


class PublicProfileListView(generics.ListAPIView):
    serializer_class = PublicProfileSummarySerializer
    permission_classes = [AllowAny]
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

        queryset = User.objects.filter(
            is_active=True,
            profile__isnull=False,
        )
        if self.request.user is not None and self.request.user.is_authenticated:
            queryset = queryset.exclude(pk=self.request.user.pk)
        queryset = queryset.select_related("profile").prefetch_related(
            "user_skills__skill",
            "user_interests__interest",
        )

        search = values.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(profile__university__icontains=search)
                | Q(profile__major__name__icontains=search)
                | Q(profile__bio__icontains=search)
            )

        university = values.get("university", "").strip()
        if university:
            queryset = queryset.filter(profile__university__icontains=university)

        major = values.get("major", "").strip()
        if major:
            queryset = queryset.filter(profile__major__name__icontains=major)

        if "start_year" in values:
            queryset = queryset.filter(profile__start_year=values["start_year"])

        skill = values.get("skill", "").strip()
        if skill:
            queryset = queryset.filter(user_skills__skill__name__icontains=skill)

        interest = values.get("interest", "").strip()
        if interest:
            queryset = queryset.filter(user_interests__interest__name__icontains=interest)

        return queryset.distinct().order_by("id")


class PublicProfileDetailView(generics.RetrieveAPIView):
    serializer_class = PublicProfileDetailSerializer
    permission_classes = [AllowAny]
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
