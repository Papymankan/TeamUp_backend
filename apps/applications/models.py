from django.conf import settings
from django.db import models


class Application(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        on_delete=models.CASCADE,
        related_name="applications",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="applications",
    )
    message = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=9,
        choices=Status.choices,
        default=Status.PENDING,
    )
    applied_at = models.DateTimeField(auto_now_add=True)
    status_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "applicant"],
                name="app_opp_applicant_unique",
            )
        ]

    def __str__(self):
        return f"{self.applicant.email} - {self.opportunity.title}"
