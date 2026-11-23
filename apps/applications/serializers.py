from rest_framework import serializers

from apps.opportunities.models import Opportunity
from apps.users.models import User
from .models import Application


class ApplicationCreateSerializer(serializers.Serializer):
    message = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
    )

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


class ApplicationApplicantSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "first_name", "last_name")
        read_only_fields = fields


class MyApplicationSerializer(serializers.ModelSerializer):
    opportunity_id = serializers.IntegerField(read_only=True)
    opportunity_title = serializers.CharField(
        source="opportunity.title",
        read_only=True,
    )
    opportunity_category = serializers.CharField(
        source="opportunity.category",
        read_only=True,
    )
    opportunity_status = serializers.CharField(
        source="opportunity.status",
        read_only=True,
    )
    created_at = serializers.DateTimeField(source="applied_at", read_only=True)
    updated_at = serializers.DateTimeField(
        source="status_updated_at",
        read_only=True,
    )

    class Meta:
        model = Application
        fields = (
            "id",
            "opportunity_id",
            "opportunity_title",
            "opportunity_category",
            "opportunity_status",
            "message",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class OpportunityApplicationSerializer(serializers.ModelSerializer):
    applicant = ApplicationApplicantSerializer(read_only=True)
    created_at = serializers.DateTimeField(source="applied_at", read_only=True)
    updated_at = serializers.DateTimeField(
        source="status_updated_at",
        read_only=True,
    )

    class Meta:
        model = Application
        fields = (
            "id",
            "applicant",
            "message",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
