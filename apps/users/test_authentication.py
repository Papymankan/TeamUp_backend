from datetime import timedelta
from smtplib import SMTPException
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.cache import cache
from django.core import mail
from django.test import TestCase, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from config.settings import resolve_frontend_url

from .models import Profile


User = get_user_model()
REGISTER_URL = "/api/auth/register/"
LOGIN_URL = "/api/auth/login/"
REFRESH_URL = "/api/auth/token/refresh/"
LOGOUT_URL = "/api/auth/logout/"
RESET_URL = "/api/auth/password-reset/"
RESET_CONFIRM_URL = "/api/auth/password-reset/confirm/"
VERIFY_EMAIL_URL = "/api/auth/verify-email/"
RESEND_VERIFICATION_URL = "/api/auth/resend-verification/"
ACCOUNT_URL = "/api/account/"
VALID_PASSWORD = "StrongPassword123!"
EMAIL_VERIFICATION_SALT = "users.email_verification"


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    FRONTEND_URL="http://localhost:5173",
)
class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.client = APIClient()
        self.payload = {
            "email": " Student@Example.com ",
            "password": VALID_PASSWORD,
            "first_name": "Ali",
            "last_name": "Ahmadi",
        }

    def test_registration_creates_inactive_user_and_sends_verification_email(self):
        response = self.client.post(REGISTER_URL, self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email="student@example.com")
        self.assertFalse(user.is_active)
        self.assertTrue(user.check_password(VALID_PASSWORD))
        self.assertNotEqual(user.password, VALID_PASSWORD)
        self.assertEqual(Profile.objects.filter(user=user).count(), 1)
        self.assertEqual(
            response.data,
            {
                "detail": (
                    "ثبت‌نام انجام شد. برای ورود، نشانی ایمیل خود را از طریق "
                    "پیوند ارسالی تأیید کنید. اگر ایمیل را دریافت نکردید، "
                    "می‌توانید درخواست ارسال مجدد دهید."
                )
            },
        )
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [user.email])
        html_body, _ = mail.outbox[0].alternatives[0]
        self.assertIn(">تأیید ایمیل</a>", html_body)
        self.assertIn("۲۴ ساعت", mail.outbox[0].body)

    def test_duplicate_email_is_rejected_case_insensitively(self):
        User.objects.create_user(email="student@example.com", password=VALID_PASSWORD)

        response = self.client.post(REGISTER_URL, self.payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)

    def test_duplicate_unverified_email_requests_verification_resend(self):
        existing_user = User.objects.create_user(
            email="student@example.com",
            password=VALID_PASSWORD,
            is_active=False,
        )

        response = self.client.post(REGISTER_URL, self.payload, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.data,
            {
                "code": "email_verification_required",
                "detail": (
                    "برای این ایمیل یک حساب تأییدنشده وجود دارد. "
                    "برای دریافت دوباره پیوند، درخواست ارسال مجدد کنید."
                ),
                "email": "student@example.com",
            },
        )
        self.assertEqual(User.objects.filter(email="student@example.com").count(), 1)
        existing_user.refresh_from_db()
        self.assertTrue(existing_user.check_password(VALID_PASSWORD))
        self.assertFalse(existing_user.is_active)
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_email_is_rejected(self):
        self.payload["email"] = "not-an-email"

        response = self.client.post(REGISTER_URL, self.payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)
        self.assertIn("پست الکترونیکی صحیح وارد کنید", str(response.data["email"]))

    def test_password_may_be_similar_to_email(self):
        self.payload["password"] = "student@example.com!A9"

        response = self.client.post(REGISTER_URL, self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email="student@example.com")
        self.assertTrue(user.check_password(self.payload["password"]))

    def test_weak_password_is_rejected(self):
        self.payload["password"] = "password"

        response = self.client.post(REGISTER_URL, self.payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data)
        self.assertFalse(User.objects.filter(email="student@example.com").exists())

    def test_privileged_fields_are_rejected(self):
        self.payload["is_staff"] = True

        response = self.client.post(REGISTER_URL, self.payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email="student@example.com").exists())

    def test_required_names_are_required(self):
        self.payload.pop("first_name")

        response = self.client.post(REGISTER_URL, self.payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("first_name", response.data)

    def test_email_delivery_failure_keeps_account_inactive_and_can_be_retried(self):
        with patch(
            "apps.users.email_utils.EmailMultiAlternatives.send",
            side_effect=SMTPException("private smtp error"),
        ):
            with self.assertLogs("apps.users.email_utils", level="ERROR"):
                response = self.client.post(
                    REGISTER_URL,
                    self.payload,
                    format="json",
                )

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email="student@example.com")
        self.assertFalse(user.is_active)

        retry_response = self.client.post(
            RESEND_VERIFICATION_URL,
            {"email": user.email},
            format="json",
        )

        self.assertEqual(retry_response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertFalse(User.objects.get(pk=user.pk).is_active)


class LoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="login@example.com",
            password=VALID_PASSWORD,
            first_name="Ali",
            last_name="Ahmadi",
        )

    def test_login_returns_tokens_and_safe_account_information(self):
        response = self.client.post(
            LOGIN_URL,
            {"email": " LOGIN@Example.COM ", "password": VALID_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["user"]["email"], self.user.email)
        self.assertNotIn("password", response.data["user"])

    def test_incorrect_and_unknown_credentials_have_same_generic_response(self):
        incorrect_password = self.client.post(
            LOGIN_URL,
            {"email": self.user.email, "password": "wrong-password"},
            format="json",
        )
        unknown_email = self.client.post(
            LOGIN_URL,
            {"email": "unknown@example.com", "password": "wrong-password"},
            format="json",
        )

        self.assertEqual(incorrect_password.status_code, 400)
        self.assertEqual(unknown_email.status_code, 400)
        self.assertEqual(incorrect_password.data, unknown_email.data)

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save(update_fields=("is_active",))

        response = self.client.post(
            LOGIN_URL,
            {"email": self.user.email, "password": VALID_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data["non_field_errors"],
            ["ایمیل یا رمز عبور نادرست است."],
        )
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    FRONTEND_URL="http://localhost:5173",
)
class EmailVerificationTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="verify@example.com",
            password=VALID_PASSWORD,
            first_name="Sara",
            is_active=False,
        )

    def _token(self, user=None):
        user = user or self.user
        return signing.dumps(
            {"user_id": user.pk, "email": user.email},
            salt=EMAIL_VERIFICATION_SALT,
            compress=True,
        )

    def test_valid_token_activates_account_and_cannot_activate_another(self):
        other_user = User.objects.create_user(
            email="other-verify@example.com",
            password=VALID_PASSWORD,
            is_active=False,
        )

        response = self.client.post(
            VERIFY_EMAIL_URL,
            {"token": self._token()},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        other_user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertFalse(other_user.is_active)

    @patch("apps.users.views.EMAIL_VERIFICATION_MAX_AGE", -1)
    def test_expired_token_is_rejected(self):
        response = self.client.post(
            VERIFY_EMAIL_URL,
            {"token": self._token()},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("token", response.data)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_invalid_and_malformed_tokens_are_rejected(self):
        for token in ("not-a-signed-token", "%%%"):
            with self.subTest(token=token):
                response = self.client.post(
                    VERIFY_EMAIL_URL,
                    {"token": token},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("token", response.data)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_token_bound_to_another_email_is_rejected(self):
        other_user = User.objects.create_user(
            email="different@example.com",
            password=VALID_PASSWORD,
            is_active=False,
        )
        mismatched_token = signing.dumps(
            {"user_id": other_user.pk, "email": self.user.email},
            salt=EMAIL_VERIFICATION_SALT,
            compress=True,
        )

        response = self.client.post(
            VERIFY_EMAIL_URL,
            {"token": mismatched_token},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        other_user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertFalse(other_user.is_active)

    def test_already_verified_account_gets_specific_response(self):
        self.user.is_active = True
        self.user.save(update_fields=("is_active",))

        response = self.client.post(
            VERIFY_EMAIL_URL,
            {"token": self._token()},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["detail"],
            "نشانی ایمیل این حساب قبلاً تأیید شده است.",
        )

    def test_resend_sends_email_only_for_unverified_account(self):
        response = self.client.post(
            RESEND_VERIFICATION_URL,
            {"email": self.user.email},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        html_body, _ = mail.outbox[0].alternatives[0]
        self.assertIn(">تأیید ایمیل</a>", html_body)

        self.user.is_active = True
        self.user.save(update_fields=("is_active",))
        verified_response = self.client.post(
            RESEND_VERIFICATION_URL,
            {"email": self.user.email},
            format="json",
        )
        self.assertEqual(verified_response.data, response.data)
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_cooldown_and_unknown_email_response(self):
        first_response = self.client.post(
            RESEND_VERIFICATION_URL,
            {"email": self.user.email},
            format="json",
        )
        unknown_response = self.client.post(
            RESEND_VERIFICATION_URL,
            {"email": "unknown@example.com"},
            format="json",
        )
        repeated_response = self.client.post(
            RESEND_VERIFICATION_URL,
            {"email": self.user.email},
            format="json",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(unknown_response.data, first_response.data)
        self.assertEqual(repeated_response.data, first_response.data)
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_ip_rate_limit_is_enforced(self):
        for _ in range(5):
            response = self.client.post(
                RESEND_VERIFICATION_URL,
                {"email": "unknown@example.com"},
                format="json",
            )
            self.assertEqual(response.status_code, 200)

        limited_response = self.client.post(
            RESEND_VERIFICATION_URL,
            {"email": "unknown@example.com"},
            format="json",
        )
        self.assertEqual(limited_response.status_code, 429)

    def test_verification_email_uses_shared_persian_branding_and_frontend_link(self):
        response = self.client.post(
            RESEND_VERIFICATION_URL,
            {"email": self.user.email},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("سلام Sara،", email.body)
        self.assertIn("۲۴ ساعت", email.body)
        link = next(line.strip() for line in email.body.splitlines() if line.startswith("http"))
        parsed_link = urlsplit(link)
        self.assertEqual(parsed_link.scheme, "http")
        self.assertEqual(parsed_link.netloc, "localhost:5173")
        self.assertEqual(parsed_link.path, "/verify-email/")
        self.assertTrue(parse_qs(parsed_link.query).get("token"))

        html_body, content_type = email.alternatives[0]
        self.assertEqual(content_type, "text/html")
        self.assertIn('lang="fa" dir="rtl"', html_body)
        self.assertIn('src="cid:teamup-logo"', html_body)
        self.assertIn(">تأیید ایمیل</a>", html_body)
        self.assertIn("max-width:520px", html_body)
        self.assertEqual(email.attachments[0].get_content_type(), "image/png")


class TokenTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="tokens@example.com",
            password=VALID_PASSWORD,
        )
        self.client = APIClient()

    def test_valid_refresh_rotates_and_blacklists_old_refresh_token(self):
        old_refresh = str(RefreshToken.for_user(self.user))

        response = self.client.post(
            REFRESH_URL,
            {"refresh": old_refresh},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

        old_refresh_response = self.client.post(
            REFRESH_URL,
            {"refresh": old_refresh},
            format="json",
        )
        self.assertEqual(old_refresh_response.status_code, 401)

    def test_invalid_and_expired_refresh_tokens_are_rejected(self):
        invalid_response = self.client.post(
            REFRESH_URL,
            {"refresh": "not-a-token"},
            format="json",
        )
        self.assertEqual(invalid_response.status_code, 401)
        self.assertEqual(
            invalid_response.data["detail"],
            "توکن احراز هویت نامعتبر یا منقضی شده است.",
        )

        expired = RefreshToken.for_user(self.user)
        expired.set_exp(lifetime=timedelta(seconds=-1))
        expired_response = self.client.post(
            REFRESH_URL,
            {"refresh": str(expired)},
            format="json",
        )
        self.assertEqual(expired_response.status_code, 401)
        self.assertEqual(
            expired_response.data["detail"],
            "توکن احراز هویت نامعتبر یا منقضی شده است.",
        )

    def test_logout_requires_authentication_and_blacklists_refresh_token(self):
        refresh = str(RefreshToken.for_user(self.user))
        anonymous_response = self.client.post(
            LOGOUT_URL,
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(anonymous_response.status_code, 401)

        self.client.force_authenticate(user=self.user)
        logout_response = self.client.post(
            LOGOUT_URL,
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(logout_response.status_code, 200)
        self.assertEqual(
            logout_response.data["detail"],
            "با موفقیت از حساب کاربری خارج شدید.",
        )

        refresh_response = self.client.post(
            REFRESH_URL,
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(refresh_response.status_code, 401)

    def test_logout_rejects_another_users_refresh_token(self):
        other_user = User.objects.create_user(
            email="other@example.com",
            password=VALID_PASSWORD,
        )
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            LOGOUT_URL,
            {"refresh": str(RefreshToken.for_user(other_user))},
            format="json",
        )

        self.assertEqual(response.status_code, 400)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="reset@example.com",
            password=VALID_PASSWORD,
        )

    @override_settings(FRONTEND_URL="http://localhost:5173")
    def test_reset_request_sends_email_for_existing_account(self):
        response = self.client.post(
            RESET_URL,
            {"email": self.user.email},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, self._request_response())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn("reset-password/confirm/", mail.outbox[0].body)
        self.assertIn("برای ادامه، این پیوند را باز کنید", mail.outbox[0].body)
        logo = mail.outbox[0].attachments[0]
        self.assertEqual(logo.get_content_type(), "image/png")
        self.assertEqual(logo["Content-ID"], "<teamup-logo>")
        self.assertEqual(logo.get_content_disposition(), "inline")
        html_body, content_type = mail.outbox[0].alternatives[0]
        self.assertEqual(content_type, "text/html")
        self.assertIn('src="cid:teamup-logo"', html_body)
        self.assertIn(">تغییر رمز عبور</a>", html_body)
        self.assertIn("۳ روز", html_body)
        self.assertIn("اگر دکمه کار نمی‌کند", html_body)
        self.assertIn(
            'href="http://localhost:5173/reset-password/confirm/',
            html_body,
        )
        self.assertIn(
            ">http://localhost:5173/reset-password/confirm/",
            html_body,
        )

    @override_settings(DEBUG=False, FRONTEND_URL="http://localhost:5173")
    def test_production_reset_email_can_target_local_vite(self):
        response = self.client.post(
            RESET_URL,
            {"email": self.user.email},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, self._request_response())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            "http://localhost:5173/reset-password/confirm/",
            mail.outbox[0].body,
        )
        html_body, _ = mail.outbox[0].alternatives[0]
        self.assertIn(
            'href="http://localhost:5173/reset-password/confirm/',
            html_body,
        )

    def test_frontend_url_validation_allows_vite_and_deployed_https_only(self):
        self.assertEqual(
            resolve_frontend_url("http://localhost:5173", debug=False),
            "http://localhost:5173",
        )
        self.assertEqual(
            resolve_frontend_url("https://teamup-web.example.com", debug=False),
            "https://teamup-web.example.com",
        )
        for unsafe_url in (
            "http://localhost:5174",
            "http://127.0.0.1:5173",
            "https://localhost:5173",
            "http://teamup-web.example.com",
            "http://localhost:5173/other",
            "http://localhost:5173/?next=https://attacker.example",
        ):
            with self.subTest(url=unsafe_url):
                self.assertIsNone(resolve_frontend_url(unsafe_url, debug=False))

    def test_unknown_email_gets_same_response_without_sending_email(self):
        existing_response = self.client.post(
            RESET_URL,
            {"email": self.user.email},
            format="json",
        )
        mail.outbox.clear()

        unknown_response = self.client.post(
            RESET_URL,
            {"email": "unknown@example.com"},
            format="json",
        )

        self.assertEqual(unknown_response.status_code, 200)
        self.assertEqual(unknown_response.data, existing_response.data)
        self.assertEqual(mail.outbox, [])

    @override_settings(FRONTEND_URL=None)
    def test_missing_frontend_url_returns_generic_response_without_sending_email(self):
        with patch("apps.users.email_utils.EmailMultiAlternatives") as email_message:
            with self.assertLogs("apps.users.views", level="WARNING") as captured:
                responses = [
                    self.client.post(
                        RESET_URL,
                        {"email": email},
                        format="json",
                    )
                    for email in (self.user.email, "unknown@example.com")
                ]

        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(
            [response.data for response in responses],
            [self._request_response(), self._request_response()],
        )
        email_message.assert_not_called()
        self.assertIn("FRONTEND_URL", captured.output[0])
        self.assertNotIn(self.user.email, captured.output[0])

    def test_delivery_failure_is_logged_without_exposing_email_contents(self):
        private_error_detail = "private-smtp-error-detail"
        with patch(
            "apps.users.email_utils.EmailMultiAlternatives.send",
            side_effect=SMTPException(private_error_detail),
        ):
            with self.assertLogs("apps.users.email_utils", level="ERROR") as captured:
                response = self.client.post(
                    RESET_URL,
                    {"email": self.user.email},
                    format="json",
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, self._request_response())
        self.assertIn(f"user_id={self.user.pk}", captured.output[0])
        self.assertIn("SMTPException", captured.output[0])
        self.assertNotIn(private_error_detail, captured.output[0])
        self.assertNotIn(self.user.email, captured.output[0])

    def test_valid_reset_changes_password_and_token_cannot_be_reused(self):
        uid, token = self._reset_credentials()
        response = self.client.post(
            RESET_CONFIRM_URL,
            {
                "uid": uid,
                "token": token,
                "new_password": "NewStrongPassword456!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewStrongPassword456!"))
        self.assertEqual(response.data["detail"], "گذرواژه با موفقیت بازنشانی شد.")

        reused_response = self.client.post(
            RESET_CONFIRM_URL,
            {
                "uid": uid,
                "token": token,
                "new_password": "AnotherStrongPassword789!",
            },
            format="json",
        )
        self.assertEqual(reused_response.status_code, 400)

    def test_invalid_uid_or_token_is_rejected(self):
        response = self.client.post(
            RESET_CONFIRM_URL,
            {
                "uid": "invalid",
                "token": "invalid",
                "new_password": "NewStrongPassword456!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("token", response.data)

    @override_settings(PASSWORD_RESET_TIMEOUT=-1)
    def test_expired_reset_token_is_rejected(self):
        uid, token = self._reset_credentials()

        response = self.client.post(
            RESET_CONFIRM_URL,
            {
                "uid": uid,
                "token": token,
                "new_password": "NewStrongPassword456!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("token", response.data)

    def test_new_password_must_pass_configured_validators(self):
        uid, token = self._reset_credentials()

        response = self.client.post(
            RESET_CONFIRM_URL,
            {"uid": uid, "token": token, "new_password": "password"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("new_password", response.data)

    def _reset_credentials(self):
        return (
            urlsafe_base64_encode(force_bytes(self.user.pk)),
            default_token_generator.make_token(self.user),
        )

    @staticmethod
    def _request_response():
        return {
            "detail": (
                "اگر حساب کاربری فعالی با این ایمیل وجود داشته باشد، "
                "راهنمای بازنشانی گذرواژه برای شما ارسال خواهد شد."
            )
        }


class AccountTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="account@example.com",
            password=VALID_PASSWORD,
            first_name="Ali",
            last_name="Ahmadi",
        )

    def test_account_requires_authentication(self):
        response = self.client.get(ACCOUNT_URL)

        self.assertEqual(response.status_code, 401)

    def test_authenticated_user_gets_only_safe_account_information(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get(ACCOUNT_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], self.user.pk)
        self.assertEqual(response.data["email"], self.user.email)
        self.assertEqual(response.data["first_name"], "Ali")
        self.assertEqual(response.data["last_name"], "Ahmadi")
        self.assertIn("date_joined", response.data)
        self.assertNotIn("password", response.data)
        self.assertNotIn("is_superuser", response.data)

    def test_account_can_update_name_and_normalized_email(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(
            ACCOUNT_URL,
            {
                "first_name": "Alireza",
                "last_name": "Ahmadi",
                "email": " NEW@Example.COM ",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Alireza")
        self.assertEqual(self.user.last_name, "Ahmadi")
        self.assertEqual(self.user.email, "new@example.com")

    def test_duplicate_email_is_rejected(self):
        User.objects.create_user(email="taken@example.com", password=VALID_PASSWORD)
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(
            ACCOUNT_URL,
            {"email": "TAKEN@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)

    def test_privileged_and_password_fields_cannot_be_modified(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(
            ACCOUNT_URL,
            {
                "is_staff": True,
                "is_superuser": True,
                "is_active": False,
                "password": "attacker-controlled",
                "id": 9999,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.user.check_password(VALID_PASSWORD))


class AuthDocumentationTests(TestCase):
    def test_schema_includes_authentication_and_account_routes(self):
        response = self.client.get("/api/schema/")

        self.assertEqual(response.status_code, 200)
        schema = response.content.decode()
        for path in (
            "/api/auth/register/",
            "/api/auth/login/",
            "/api/auth/verify-email/",
            "/api/auth/resend-verification/",
            "/api/auth/token/refresh/",
            "/api/auth/logout/",
            "/api/auth/password-reset/",
            "/api/auth/password-reset/confirm/",
            "/api/account/",
        ):
            with self.subTest(path=path):
                self.assertIn(path, schema)
