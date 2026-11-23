from bleach import Cleaner
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.applications.models import Application
from apps.users.models import Interest, PortfolioItem, Skill
from .models import Opportunity


ALLOWED_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "ul",
    "ol",
    "li",
    "a",
}
ALLOWED_ATTRIBUTES = {"a": ["href", "title"]}
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def sanitize_description(value):
    if value is None:
        return ""
    cleaner = Cleaner(
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
    return cleaner.clean(value)


class OpportunityCatalogSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ("id", "name")


class OpportunitySkillSerializer(OpportunityCatalogSerializer):
    class Meta(OpportunityCatalogSerializer.Meta):
        model = Skill


class OpportunityInterestSerializer(OpportunityCatalogSerializer):
    class Meta(OpportunityCatalogSerializer.Meta):
        model = Interest


class OpportunityOwnerSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)


class StrictOpportunityInputMixin:
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


class OpportunityCreateSerializer(StrictOpportunityInputMixin, serializers.ModelSerializer):
    category = serializers.ChoiceField(
        choices=PortfolioItem.ItemType.choices,
        error_messages={
            "invalid_choice": "لطفاً دسته‌بندی را از گزینه‌های موجود انتخاب کنید."
        },
    )
    weekly_time_commitment_hours = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=0,
    )
    skills = serializers.PrimaryKeyRelatedField(
        queryset=Skill.objects.all(),
        many=True,
        required=False,
    )
    interests = serializers.PrimaryKeyRelatedField(
        queryset=Interest.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model = Opportunity
        fields = (
            "title",
            "description",
            "category",
            "weekly_time_commitment_hours",
            "skills",
            "interests",
        )

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError("عنوان فرصت الزامی است.")
        return value.strip()

    def validate_description(self, value):
        return sanitize_description(value)

    def create(self, validated_data):
        skills = validated_data.pop("skills", [])
        interests = validated_data.pop("interests", [])
        opportunity = Opportunity.objects.create(
            owner=self.context["request"].user,
            status=Opportunity.Status.DRAFT,
            **validated_data,
        )
        opportunity.skills.set(skills)
        opportunity.interests.set(interests)
        return opportunity


class OpportunityUpdateSerializer(StrictOpportunityInputMixin, serializers.ModelSerializer):
    category = serializers.ChoiceField(
        choices=PortfolioItem.ItemType.choices,
        required=False,
        error_messages={
            "invalid_choice": "لطفاً دسته‌بندی را از گزینه‌های موجود انتخاب کنید."
        },
    )
    weekly_time_commitment_hours = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=0,
        required=False,
    )
    skills = serializers.PrimaryKeyRelatedField(
        queryset=Skill.objects.all(),
        many=True,
        required=False,
    )
    interests = serializers.PrimaryKeyRelatedField(
        queryset=Interest.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model = Opportunity
        fields = (
            "title",
            "description",
            "category",
            "weekly_time_commitment_hours",
            "skills",
            "interests",
        )

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError("عنوان فرصت الزامی است.")
        return value.strip()

    def validate_description(self, value):
        return sanitize_description(value)

    def update(self, instance, validated_data):
        skills = validated_data.pop("skills", None)
        interests = validated_data.pop("interests", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if skills is not None:
            instance.skills.set(skills)
        if interests is not None:
            instance.interests.set(interests)
        return instance


class OpportunitySerializer(serializers.ModelSerializer):
    owner = OpportunityOwnerSerializer(read_only=True)
    skills = OpportunitySkillSerializer(many=True, read_only=True)
    interests = OpportunityInterestSerializer(many=True, read_only=True)
    category = serializers.ChoiceField(
        choices=PortfolioItem.ItemType.choices,
        read_only=True,
    )

    class Meta:
        model = Opportunity
        fields = (
            "id",
            "owner",
            "title",
            "description",
            "category",
            "weekly_time_commitment_hours",
            "status",
            "skills",
            "interests",
            "created_at",
            "updated_at",
            "published_at",
            "closed_at",
        )
        read_only_fields = fields


class CurrentUserApplicationSerializer(serializers.ModelSerializer):
    status = serializers.CharField(source="get_status_display", read_only=True)
    created_at = serializers.DateTimeField(source="applied_at", read_only=True)

    class Meta:
        model = Application
        fields = ("id", "status", "created_at")
        read_only_fields = fields


class OpportunityDetailSerializer(OpportunitySerializer):
    current_user_application = serializers.SerializerMethodField()

    class Meta(OpportunitySerializer.Meta):
        fields = OpportunitySerializer.Meta.fields + ("current_user_application",)
        read_only_fields = fields

    @extend_schema_field(CurrentUserApplicationSerializer(allow_null=True))
    def get_current_user_application(self, opportunity):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            return None

        application = (
            Application.objects.filter(
                opportunity=opportunity,
                applicant=user,
            )
            .only("id", "status", "applied_at")
            .first()
        )
        if application is None:
            return None
        return CurrentUserApplicationSerializer(application).data


class OpportunityFilterSerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True)
    category = serializers.ChoiceField(
        choices=PortfolioItem.ItemType.choices,
        required=False,
        error_messages={
            "invalid_choice": "لطفاً دسته‌بندی را از گزینه‌های موجود انتخاب کنید."
        },
    )
    skills = serializers.CharField(required=False, allow_blank=True)
    interests = serializers.CharField(required=False, allow_blank=True)
    min_hours = serializers.DecimalField(
        required=False,
        min_value=0,
        max_digits=5,
        decimal_places=2,
    )
    max_hours = serializers.DecimalField(
        required=False,
        min_value=0,
        max_digits=5,
        decimal_places=2,
    )
    status = serializers.ChoiceField(
        choices=Opportunity.Status.choices,
        required=False,
    )
