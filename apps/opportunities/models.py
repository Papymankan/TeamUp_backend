from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from apps.users.models import PortfolioItem


class Opportunity(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        CLOSED = "closed", "Closed"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="opportunities",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(
        blank=True,
        help_text=(
            "HTML is stored as-is. API endpoints must sanitize allowed tags, "
            "attributes, and links before accepting or rendering this content."
        ),
    )
    category = models.CharField(
        max_length=20,
        choices=PortfolioItem.ItemType.choices,
    )
    weekly_time_commitment_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    status = models.CharField(
        max_length=9,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    skills = models.ManyToManyField(
        "users.Skill",
        related_name="opportunities",
        blank=True,
    )
    interests = models.ManyToManyField(
        "users.Interest",
        related_name="opportunities",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(weekly_time_commitment_hours__gte=Decimal("0.00")),
                name="opp_weekly_hours_nonnegative",
            )
        ]

    def __str__(self):
        return self.title
