import logging
from email.mime.image import MIMEImage
from smtplib import SMTPException
from urllib.parse import urlsplit

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from apps.users.email_utils import LOGO_PATH
from .models import Application


logger = logging.getLogger(__name__)

ACCEPTED_SUBJECT = "خبر خوب! درخواست همکاری شما پذیرفته شد 🎉"
REJECTED_SUBJECT = "به‌روزرسانی وضعیت درخواست شما در TeamUp"


def _absolute_frontend_url(path):
    base_url = settings.FRONTEND_URL
    if not base_url:
        return None

    parsed_path = urlsplit(path)
    if (
        not path.startswith("/")
        or path.startswith("//")
        or parsed_path.scheme
        or parsed_path.netloc
    ):
        return None
    return f"{base_url.rstrip('/')}{path}"


def _status_email_urls(opportunity_id):
    try:
        opportunity_path = settings.FRONTEND_OPPORTUNITY_DETAIL_PATH.format(
            id=opportunity_id,
        )
    except (AttributeError, KeyError, ValueError):
        return None

    opportunity_url = _absolute_frontend_url(opportunity_path)
    opportunities_url = _absolute_frontend_url(
        settings.FRONTEND_OPPORTUNITIES_PATH
    )
    if opportunity_url is None or opportunities_url is None:
        return None
    return opportunity_url, opportunities_url


def send_application_status_email(application_id, expected_status):
    if expected_status not in (
        Application.Status.ACCEPTED,
        Application.Status.REJECTED,
    ):
        return False

    application = (
        Application.objects.select_related("applicant", "opportunity")
        .filter(pk=application_id, status=expected_status)
        .first()
    )
    if application is None:
        return False

    urls = _status_email_urls(application.opportunity_id)
    if urls is None:
        logger.error(
            "Application status email skipped application_id=%s "
            "(frontend URL configuration is invalid or missing).",
            application.pk,
        )
        return False

    opportunity_url, opportunities_url = urls
    accepted = expected_status == Application.Status.ACCEPTED
    context = {
        "recipient_name": application.applicant.first_name.strip() or "دوست عزیز",
        "opportunity_title": application.opportunity.title,
        "opportunity_url": opportunity_url,
        "opportunities_url": opportunities_url,
        "accepted": accepted,
    }
    subject = ACCEPTED_SUBJECT if accepted else REJECTED_SUBJECT
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string(
            "applications/email/application_status.txt",
            context,
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[application.applicant.email],
    )
    logo = MIMEImage(LOGO_PATH.read_bytes(), _subtype="png")
    logo.add_header("Content-ID", "<teamup-logo>")
    logo.add_header("Content-Disposition", "inline", filename="teamup-logo.png")
    message.attach(logo)
    message.attach_alternative(
        render_to_string(
            "applications/email/application_status.html",
            context,
        ),
        "text/html",
    )

    try:
        sent_count = message.send(fail_silently=False)
    except (OSError, SMTPException) as error:
        logger.error(
            "Application status email delivery failed application_id=%s "
            "(error_type=%s).",
            application.pk,
            type(error).__name__,
            exc_info=(type(error), None, error.__traceback__),
        )
        return False

    if sent_count != 1:
        logger.error(
            "Application status email delivery failed application_id=%s "
            "(sent_count=%s).",
            application.pk,
            sent_count,
        )
        return False

    logger.info(
        "Application status email sent application_id=%s status=%s",
        application.pk,
        expected_status,
    )
    return True
