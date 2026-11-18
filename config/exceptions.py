import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as default_exception_handler
from rest_framework_simplejwt.exceptions import InvalidToken


logger = logging.getLogger(__name__)
GENERIC_SERVER_ERROR = "خطای غیرمنتظره‌ای رخ داد. لطفاً کمی بعد دوباره تلاش کنید."


def api_exception_handler(exc, context):
    response = default_exception_handler(exc, context)
    if response is not None and response.status_code < status.HTTP_500_INTERNAL_SERVER_ERROR:
        if isinstance(exc, InvalidToken):
            response.data["detail"] = "توکن احراز هویت نامعتبر یا منقضی شده است."
        return response

    request = context.get("request")
    user = getattr(request, "user", None)
    logger.error(
        "API request failed method=%s path=%s user_id=%s exception_type=%s",
        getattr(request, "method", "unknown"),
        getattr(request, "path", "unknown"),
        getattr(user, "pk", None),
        type(exc).__name__,
        exc_info=(type(exc), exc, exc.__traceback__),
    )

    if response is not None:
        response.data = {"detail": GENERIC_SERVER_ERROR}
        return response
    return Response(
        {"detail": GENERIC_SERVER_ERROR},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
