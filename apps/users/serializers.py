from binascii import Error as BinasciiError
from decimal import Decimal

from django.contrib.auth import authenticate, get_user_model, password_validation
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from .models import (
    Interest,
    Major,
    PortfolioItem,
    Profile,
    Skill,
    User,
    UserInterest,
    UserSkill,
    normalize_name,
)


def normalize_email(email):
    return User.objects.normalize_email(email)


MAX_USER_SKILLS = 10
MAX_USER_INTERESTS = 3


class StrictInputMixin:
    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown_fields = set(data) - set(self.fields)
            if unknown_fields:
                raise serializers.ValidationError(
                    {
                        field: "ارسال این فیلد مجاز نیست."
                        for field in sorted(unknown_fields)
                    }
                )
        return super().to_internal_value(data)


class AccountSerializer(StrictInputMixin, serializers.ModelSerializer):
    email = serializers.EmailField()

    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "date_joined")
        read_only_fields = ("id", "date_joined")

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if "email" in attrs:
            email = normalize_email(attrs["email"])
            if User.objects.filter(email__iexact=email).exclude(
                pk=self.instance.pk
            ).exists():
                raise serializers.ValidationError(
                    {"email": "کاربری با این ایمیل قبلاً ثبت‌نام کرده است."}
                )
            attrs["email"] = email
        return attrs

    def update(self, instance, validated_data):
        email = validated_data.get("email")
        try:
            with transaction.atomic():
                return super().update(instance, validated_data)
        except IntegrityError as error:
            if email and User.objects.filter(email__iexact=email).exclude(
                pk=instance.pk
            ).exists():
                raise serializers.ValidationError(
                    {"email": "کاربری با این ایمیل قبلاً ثبت‌نام کرده است."}
                ) from error
            raise


class RegistrationSerializer(StrictInputMixin, serializers.ModelSerializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={"input_type": "password"},
    )
    first_name = serializers.CharField(required=True, allow_blank=False)
    last_name = serializers.CharField(required=True, allow_blank=False)

    class Meta:
        model = User
        fields = ("email", "password", "first_name", "last_name")

    def validate_email(self, value):
        email = normalize_email(value)
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                "کاربری با این ایمیل قبلاً ثبت‌نام کرده است."
            )
        return email

    def validate(self, attrs):
        user = User(
            email=attrs["email"],
            first_name=attrs["first_name"],
            last_name=attrs["last_name"],
        )
        try:
            password_validation.validate_password(attrs["password"], user=user)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"password": error.messages}) from error
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        try:
            with transaction.atomic():
                return User.objects.create_user(password=password, **validated_data)
        except IntegrityError as error:
            if User.objects.filter(email__iexact=validated_data["email"]).exists():
                raise serializers.ValidationError(
                    {"email": "کاربری با این ایمیل قبلاً ثبت‌نام کرده است."}
                ) from error
            raise


class LoginSerializer(StrictInputMixin, serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={"input_type": "password"},
    )

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=normalize_email(attrs["email"]),
            password=attrs["password"],
        )
        if user is None:
            raise serializers.ValidationError("ایمیل یا رمز عبور نادرست است.")
        attrs["user"] = user
        return attrs


class LogoutSerializer(StrictInputMixin, serializers.Serializer):
    refresh = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_refresh(self, value):
        try:
            token = RefreshToken(value)
        except TokenError as error:
            raise serializers.ValidationError(
                "توکن نوسازی نامعتبر یا منقضی شده است."
            ) from error

        request_user = self.context["request"].user
        token_user_id = token.get(api_settings.USER_ID_CLAIM)
        if token_user_id is None or str(token_user_id) != str(request_user.pk):
            raise serializers.ValidationError("توکن نوسازی نامعتبر یا منقضی شده است.")
        return token


class PasswordResetRequestSerializer(StrictInputMixin, serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return normalize_email(value)


class PasswordResetConfirmSerializer(StrictInputMixin, serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={"input_type": "password"},
    )

    def validate(self, attrs):
        try:
            user_id = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = get_user_model()._default_manager.get(pk=user_id)
        except (
            BinasciiError,
            DjangoValidationError,
            TypeError,
            ValueError,
            OverflowError,
            UnicodeDecodeError,
            get_user_model().DoesNotExist,
        ) as error:
            raise serializers.ValidationError(
                {"token": "لینک بازنشانی رمز عبور نامعتبر یا منقضی شده است."}
            ) from error

        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError(
                {"token": "لینک بازنشانی رمز عبور نامعتبر یا منقضی شده است."}
            )

        try:
            password_validation.validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as error:
            raise serializers.ValidationError(
                {"new_password": error.messages}
            ) from error

        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=("password",))
        return user


class ProfileSerializer(StrictInputMixin, serializers.ModelSerializer):
    major = serializers.SlugRelatedField(
        slug_field="name",
        queryset=Major.objects.all(),
        required=False,
        allow_null=True,
        error_messages={
            "does_not_exist": "رشته تحصیلی انتخاب‌شده معتبر نیست.",
            "invalid": "نام رشته تحصیلی معتبر نیست.",
        },
    )
    start_year = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
    )
    graduation_year = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
    )
    weekly_available_hours = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.00"),
        max_value=Decimal("168.00"),
        required=False,
    )

    class Meta:
        model = Profile
        fields = (
            "bio",
            "github_url",
            "linkedin_url",
            "university",
            "major",
            "start_year",
            "graduation_year",
            "is_currently_studying",
            "weekly_available_hours",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")

    def validate(self, attrs):
        attrs = super().validate(attrs)
        start_year = attrs.get(
            "start_year",
            getattr(self.instance, "start_year", None),
        )
        graduation_year = attrs.get(
            "graduation_year",
            getattr(self.instance, "graduation_year", None),
        )
        if (
            start_year is not None
            and graduation_year is not None
            and graduation_year < start_year
        ):
            raise serializers.ValidationError(
                {"graduation_year": "سال پایان تحصیل نمی‌تواند قبل از سال شروع تحصیل باشد."}
            )
        return attrs


class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = ("id", "name", "created_at")
        read_only_fields = ("id", "created_at")


class UserSkillSerializer(serializers.ModelSerializer):
    skill = SkillSerializer(read_only=True)
    name = serializers.CharField(write_only=True)
    proficiency_level = serializers.ChoiceField(
        choices=UserSkill.Proficiency.choices,
        required=False,
        allow_blank=True,
    )

    class Meta:
        model = UserSkill
        fields = ("id", "skill", "name", "proficiency_level", "created_at")
        read_only_fields = ("id", "skill", "created_at")

    def validate_name(self, value):
        value = normalize_name(value)
        if not value:
            raise serializers.ValidationError("وارد کردن نام مهارت الزامی است.")
        return value

    def create(self, validated_data):
        request = self.context["request"]
        name = validated_data.pop("name")
        normalized_name = normalize_name(name)
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            skill = Skill.objects.filter(name__iexact=normalized_name).first()
            if skill is None:
                raise serializers.ValidationError(
                    {"name": "لطفاً یک مهارت را از فهرست مهارت‌های موجود انتخاب کنید."}
                )

            user_skill = UserSkill.objects.filter(
                user=request.user,
                skill=skill,
            ).first()
            created = user_skill is None
            if created:
                if UserSkill.objects.filter(user=request.user).count() >= MAX_USER_SKILLS:
                    raise serializers.ValidationError(
                        {"name": "حداکثر می‌توانید ۱۰ مهارت به پروفایل خود اضافه کنید."}
                    )
                user_skill = UserSkill.objects.create(
                    user=request.user,
                    skill=skill,
                    proficiency_level=validated_data.get("proficiency_level", ""),
                )
            elif "proficiency_level" in validated_data:
                user_skill.proficiency_level = validated_data["proficiency_level"]
                user_skill.save(update_fields=["proficiency_level"])
        self.created = created
        return user_skill


class InterestSerializer(serializers.ModelSerializer):
    class Meta:
        model = Interest
        fields = ("id", "name", "created_at")
        read_only_fields = ("id", "created_at")


class MajorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Major
        fields = ("name",)


class UserInterestSerializer(serializers.ModelSerializer):
    interest = InterestSerializer(read_only=True)
    name = serializers.CharField(write_only=True)

    class Meta:
        model = UserInterest
        fields = ("id", "interest", "name", "created_at")
        read_only_fields = ("id", "interest", "created_at")

    def validate_name(self, value):
        value = normalize_name(value)
        if not value:
            raise serializers.ValidationError("وارد کردن نام علاقه‌مندی الزامی است.")
        return value

    def create(self, validated_data):
        request = self.context["request"]
        name = validated_data.pop("name")
        normalized_name = normalize_name(name)
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            interest = Interest.objects.filter(name__iexact=normalized_name).first()
            if interest is None:
                raise serializers.ValidationError(
                    {
                        "name": (
                            "لطفاً یک علاقه‌مندی را از فهرست علاقه‌مندی‌های موجود "
                            "انتخاب کنید."
                        )
                    }
                )

            user_interest = UserInterest.objects.filter(
                user=request.user,
                interest=interest,
            ).first()
            created = user_interest is None
            if created:
                if (
                    UserInterest.objects.filter(user=request.user).count()
                    >= MAX_USER_INTERESTS
                ):
                    raise serializers.ValidationError(
                        {
                            "name": (
                                "حداکثر می‌توانید ۳ علاقه‌مندی به پروفایل خود اضافه کنید."
                            )
                        }
                    )
                user_interest = UserInterest.objects.create(
                    user=request.user,
                    interest=interest,
                )
        self.created = created
        return user_interest


class PortfolioItemSerializer(StrictInputMixin, serializers.ModelSerializer):
    item_type = serializers.ChoiceField(
        choices=PortfolioItem.ItemType.choices,
        required=False,
        error_messages={
            "invalid_choice": "لطفاً نوع نمونه‌کار را از گزینه‌های موجود انتخاب کنید."
        },
    )
    url = serializers.URLField(required=False, allow_blank=True)

    class Meta:
        model = PortfolioItem
        fields = (
            "id",
            "title",
            "description",
            "url",
            "item_type",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def create(self, validated_data):
        request = self.context["request"]
        profile, _ = Profile.objects.get_or_create(user=request.user)
        validated_data.pop("profile", None)
        return PortfolioItem.objects.create(profile=profile, **validated_data)


class PortfolioItemTypeSerializer(serializers.Serializer):
    value = serializers.CharField()
    english_name = serializers.CharField()
    persian_name = serializers.CharField()


class PublicProfileFieldsSerializer(serializers.ModelSerializer):
    major = serializers.SlugRelatedField(slug_field="name", read_only=True)

    class Meta:
        model = Profile
        fields = (
            "bio",
            "github_url",
            "linkedin_url",
            "university",
            "major",
            "start_year",
            "graduation_year",
            "is_currently_studying",
            "weekly_available_hours",
        )


class PublicSkillSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="skill.name")

    class Meta:
        model = UserSkill
        fields = ("name", "proficiency_level")


class PublicInterestSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="interest.name")

    class Meta:
        model = UserInterest
        fields = ("name",)


class PublicPortfolioItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortfolioItem
        fields = ("title", "description", "url", "item_type", "created_at")


class PublicProfileDetailSerializer(serializers.ModelSerializer):
    profile = serializers.SerializerMethodField()
    skills = serializers.SerializerMethodField()
    interests = serializers.SerializerMethodField()
    portfolio = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "first_name",
            "last_name",
            "date_joined",
            "profile",
            "skills",
            "interests",
            "portfolio",
        )

    @extend_schema_field(PublicProfileFieldsSerializer(allow_null=True))
    def get_profile(self, user):
        try:
            profile = user.profile
        except Profile.DoesNotExist:
            return None
        return PublicProfileFieldsSerializer(profile).data

    @extend_schema_field(PublicSkillSerializer(many=True))
    def get_skills(self, user):
        return PublicSkillSerializer(
            user.user_skills.all(),
            many=True,
        ).data

    @extend_schema_field(PublicInterestSerializer(many=True))
    def get_interests(self, user):
        return PublicInterestSerializer(
            user.user_interests.all(),
            many=True,
        ).data

    @extend_schema_field(PublicPortfolioItemSerializer(many=True))
    def get_portfolio(self, user):
        try:
            profile = user.profile
        except Profile.DoesNotExist:
            return []
        return PublicPortfolioItemSerializer(
            profile.portfolio_items.all(),
            many=True,
        ).data


class PublicProfileSummarySerializer(serializers.ModelSerializer):
    university = serializers.CharField(source="profile.university")
    major = serializers.CharField(source="profile.major.name", allow_null=True)
    start_year = serializers.IntegerField(source="profile.start_year", allow_null=True)
    graduation_year = serializers.IntegerField(
        source="profile.graduation_year",
        allow_null=True,
    )
    is_currently_studying = serializers.BooleanField(
        source="profile.is_currently_studying",
    )
    bio = serializers.SerializerMethodField()
    skills = serializers.SerializerMethodField()
    interests = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "first_name",
            "last_name",
            "university",
            "major",
            "start_year",
            "graduation_year",
            "is_currently_studying",
            "bio",
            "skills",
            "interests",
        )

    @extend_schema_field(serializers.CharField())
    def get_bio(self, user):
        return user.profile.bio[:280]

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_skills(self, user):
        return [user_skill.skill.name for user_skill in user.user_skills.all()]

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_interests(self, user):
        return [user_interest.interest.name for user_interest in user.user_interests.all()]


class PublicProfileSearchSerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True)
    university = serializers.CharField(required=False, allow_blank=True)
    major = serializers.CharField(required=False, allow_blank=True)
    start_year = serializers.IntegerField(required=False, min_value=1)
    skill = serializers.CharField(required=False, allow_blank=True)
    interest = serializers.CharField(required=False, allow_blank=True)
