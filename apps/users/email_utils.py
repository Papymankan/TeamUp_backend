import logging
import math
from email.mime.image import MIMEImage
from pathlib import Path
from smtplib import SMTPException

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


logger = logging.getLogger(__name__)
LOGO_PATH = (
    Path(__file__).resolve().parent
    / "static"
    / "users"
    / "email"
    / "teamup-logo.png"
)


def send_auth_email(*, user, subject, template_context, purpose):
    context = {
        "recipient_name": user.first_name.strip() or "دوست عزیز",
        **template_context,
    }
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string("users/email/auth_email.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    logo = MIMEImage(LOGO_PATH.read_bytes(), _subtype="png")
    logo.add_header("Content-ID", "<teamup-logo>")
    logo.add_header("Content-Disposition", "inline", filename="teamup-logo.png")
    message.attach(logo)
    message.attach_alternative(
        render_to_string("users/email/auth_email.html", context),
        "text/html",
    )

    try:
        sent_count = message.send(fail_silently=False)
    except (OSError, SMTPException) as error:
        logger.error(
            "%s email delivery failed user_id=%s (error_type=%s).",
            purpose,
            user.pk,
            type(error).__name__,
            exc_info=(type(error), None, error.__traceback__),
        )
        return False

    if sent_count != 1:
        logger.error(
            "%s email delivery failed user_id=%s (sent_count=%s).",
            purpose,
            user.pk,
            sent_count,
        )
        return False

    logger.info("%s email sent user_id=%s", purpose, user.pk)
    return True


def password_reset_expiration_message(timeout):
    if timeout <= 0:
        return "مهلت اعتبار این پیوند به پایان رسیده است."

    if timeout % 86400 == 0:
        amount = timeout // 86400
        unit = "روز"
    elif timeout >= 3600:
        amount = math.ceil(timeout / 3600)
        unit = "ساعت"
    elif timeout >= 60:
        amount = math.ceil(timeout / 60)
        unit = "دقیقه"
    else:
        amount = timeout
        unit = "ثانیه"

    persian_amount = str(amount).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    return f"این پیوند تا {persian_amount} {unit} پس از درخواست معتبر است."
