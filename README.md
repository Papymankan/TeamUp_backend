# TeamUp Backend

TeamUp's backend is a Django REST Framework API for students and professors to
find teammates and collaborate on academic opportunities. The foundation
includes a custom email-based user, profiles, skills, interests, and portfolio
models. Authentication and basic account management are available through
JWT-protected API endpoints.

## Requirements

- Python 3.12 or newer
- PowerShell on Windows

## Set up the environment

Open PowerShell in the repository folder and run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell prevents virtual environment activation, allow local scripts for
your user and try activating again:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\.venv\Scripts\Activate.ps1
```

## Configure environment variables

Create a local `.env` file from the example:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set `DJANGO_SECRET_KEY` to a private, randomly generated value.
The example key is only a placeholder for local setup and must not be used in
production. Adjust `CORS_ALLOWED_ORIGINS` if your frontend runs at a different
address. SQLite is the default (`DB_ENGINE=sqlite`). To prepare a local
PostgreSQL connection later, set `DB_ENGINE=postgresql` and provide `DB_NAME`,
`DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT`. No shared or production
database is configured. Set `DB_SSLMODE=require` for Neon; leaving
`DB_SSLMODE` empty preserves the PostgreSQL driver's default behavior. `.env`
is ignored by Git.

## Run the development server

With the virtual environment active and `.env` configured:

```powershell
python manage.py check
python manage.py migrate
python manage.py runserver
```

The API is available at <http://127.0.0.1:8000/>. The public health check is
<http://127.0.0.1:8000/api/health/>.

## API documentation

- Swagger UI: <http://127.0.0.1:8000/api/docs/>
- OpenAPI schema: <http://127.0.0.1:8000/api/schema/>
- ReDoc: <http://127.0.0.1:8000/api/redoc/>

## Authentication and account endpoints

Protected API endpoints use JWT authentication by default and require an access
token, except registration, login, email verification, verification resend,
refresh, and password reset. Health and API documentation routes remain public.
Send protected requests with
`Authorization: Bearer <access-token>`.

- `POST /api/auth/register/` — create an inactive account and send an email
  verification link; the response contains a `detail` message and no tokens.
- `POST /api/auth/login/` — authenticate with email and password.
- `POST /api/auth/verify-email/` — verify an account using
  `{"token": "<signed-verification-token>"}`.
- `POST /api/auth/resend-verification/` — request another verification link
  using `{"email": "student@example.com"}`. Responses do not disclose whether
  the address belongs to an unverified account; requests are throttled to
  five per hour per IP and each account has a five-minute cooldown.
- `POST /api/auth/token/refresh/` — obtain a new access token; refresh tokens
  rotate and the previous refresh token is blacklisted.
- `POST /api/auth/logout/` — blacklist the authenticated user's refresh token.
- `POST /api/auth/password-reset/` — request password-reset instructions.
- `POST /api/auth/password-reset/confirm/` — confirm a reset with the emailed
  UID and token.
- `GET /api/account/` and `PATCH /api/account/` — read or update the
  authenticated user's own name and email.
- `GET /api/profile/` and `PATCH /api/profile/` — read or update the
  authenticated user's own profile, education information, and optional
  `github_url` and `linkedin_url` values.
- `GET /api/profile/skills/`, `POST /api/profile/skills/`, and
  `DELETE /api/profile/skills/<skill_id>/` — manage the current user's skills.
- `GET /api/profile/interests/`, `POST /api/profile/interests/`, and
  `DELETE /api/profile/interests/<interest_id>/` — manage the current user's
  interests.
- `GET /api/profile/portfolio/`, `POST /api/profile/portfolio/`,
  `PATCH /api/profile/portfolio/<id>/`, and
  `DELETE /api/profile/portfolio/<id>/` — manage the current user's portfolio.
- `GET /api/portfolio-item-types/` — public list of allowed portfolio item
  types with their stable value and English and Persian names. Send the
  returned `value` as `item_type` when creating or updating a portfolio item.
- `GET /api/skills/` and `GET /api/interests/` — list reusable skills and
  interests. Profile skill and interest submissions must match an existing
  catalog name; unknown names are rejected rather than added automatically.
- `GET /api/majors/` — list available major names. Set the profile's `major`
  to one of the returned exact names; unknown names are rejected.
- `GET /api/users/<id>/` — retrieve an authenticated user's public profile.
- `GET /api/users/` — discover other active users with profiles.

Profile education data uses `start_year`, optional `graduation_year`, and
`is_currently_studying`. The old `study_year` values remain stored but are no
longer exposed or used. Profile discovery supports combining `search`,
`university`, `major`, `start_year`, `skill`, and `interest` query parameters. Results are paginated
with a default page size of 10; `page_size` may be set up to 50. Search results
contain a brief profile summary, while the individual public-profile endpoint
includes the profile, skills with proficiency, interests, and portfolio.

## API messages and logs

User-facing API success and error messages are in Persian. Validation errors
remain associated with their field so the frontend can display the relevant
message.

Application and Django request logs are written to standard output, which is
available in the Wasmer deployment logs. Unhandled API errors include a
stack trace and request method/path; credentials, tokens, and request bodies
are not logged. Password-reset delivery failures are logged without exposing
the email address or SMTP exception text.

Access tokens last 30 minutes and refresh tokens last 7 days. Blacklisting a
refresh token does **not** immediately invalidate an already-issued access
token; access tokens remain usable until they expire.

Password-reset and email-verification messages use the same Persian, right-to-left
TeamUp email layout and are sent through Gmail SMTP. The reset link uses
`FRONTEND_URL` and points to `/reset-password/confirm/` with `uid` and `token`
query parameters. Registration and resend links point to
`/verify-email/?token=...` on the frontend; that frontend page must submit the
token to `POST /api/auth/verify-email/`. Verification links expire after 24
hours. Set the SMTP variables shown in `.env.example`; provide
`EMAIL_HOST_PASSWORD` as a Gmail App Password through your environment or
hosting dashboard, never in source control. For local development,
`.env.example` uses the Vite origin `http://localhost:5173`. In production,
`FRONTEND_URL` is optional until the frontend is deployed. If it is missing or
isn't a valid non-local HTTPS URL, the backend still starts, but password-reset
and verification requests return their usual generic responses without sending
email or generating links. Set `FRONTEND_URL` to the actual deployed HTTPS
frontend origin when it is available.

Visit <http://127.0.0.1:8000/admin/> to manage records.

## Deploy to Render with Neon

Create a **Web Service** from this repository and configure:

- **Root Directory:** `.` (the repository root)
- **Build Command:** `pip install -r requirements.txt && python manage.py collectstatic --no-input && python manage.py migrate --no-input`
- **Start Command:** `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`
- **Health Check Path:** `/api/health/`

Render's build command installs requirements, collects static assets, and
applies migrations. This repository's root is the Django project directory, so
leave Render's root directory at `.` (the default).

Set these Render environment variables (use values from your Neon connection
details; never put credentials in the repository):

| Variable | Value |
| --- | --- |
| `DJANGO_SECRET_KEY` | A new, long, randomly generated secret |
| `DJANGO_DEBUG` | `False` |
| `DJANGO_ALLOWED_HOSTS` | Your Render API hostname, e.g. `teamup-api.onrender.com` |
| `CORS_ALLOWED_ORIGINS` | Your deployed React origin, e.g. `https://teamup-web.onrender.com` |
| `CSRF_TRUSTED_ORIGINS` | The deployed frontend origin(s), including `https://`, comma-separated |
| `DB_ENGINE` | `postgresql` |
| `DB_NAME` | Neon database name |
| `DB_USER` | Neon username |
| `DB_PASSWORD` | Neon password |
| `DB_HOST` | Neon hostname |
| `DB_PORT` | Neon port (usually `5432`) |
| `DB_SSLMODE` | `require` |
| `EMAIL_HOST` | `smtp.gmail.com` |
| `EMAIL_PORT` | `587` |
| `EMAIL_USE_TLS` | `True` |
| `EMAIL_HOST_USER` | `teamup.kntu@gmail.com` |
| `EMAIL_HOST_PASSWORD` | Gmail App Password, entered as a secret |
| `DEFAULT_FROM_EMAIL` | `TeamUp <teamup.kntu@gmail.com>` |
| `FRONTEND_URL` | Optional until the frontend is deployed; then use its HTTPS origin |

`CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` can be updated later when the
React app's production origin is known. Origins must include their scheme and
must not include URL paths. Keep the Render API hostname in
`DJANGO_ALLOWED_HOSTS`. Render terminates HTTPS at its proxy; Django is
configured to recognize `X-Forwarded-Proto` and serve collected static files
through WhiteNoise. The Django admin and existing API documentation routes
remain available.

`EMAIL_HOST_PASSWORD` must be set to the Gmail App Password in the hosting
dashboard before password-reset emails can be delivered. Do not commit the
password or put it in a GitHub file. The backend can be deployed before the
frontend; reset requests will remain generic and will not send email until a
valid deployed `FRONTEND_URL` is configured. After setting that URL, redeploy or
restart the service, request a reset for an account you control, and verify
that the email arrives (including Spam) and its link opens the deployed
frontend's reset-confirmation page. SMTP delivery failures are logged with the
user ID and error type only; credentials, reset links, and tokens are not
logged.

## Deploy to Wasmer Edge

Configure Wasmer to install dependencies from `requirements.txt` with `uv`,
then use:

- **Build command:** `bash build.sh`
- **Start command:** `uvicorn config.asgi:application --host 0.0.0.0 --port 8080`

Wasmer's build script only collects static files; it does not install
dependencies or run migrations. Keep Wasmer's generated `after_deploy` command
`python manage.py migrate` enabled so migrations run after deployment. The
script uses `set -euo pipefail`, so static collection failure stops the build.

Set the same application, database, SMTP, and frontend variables listed above,
using your actual Wasmer hostname (without a scheme) for `DJANGO_ALLOWED_HOSTS`,
and the frontend origin(s) for `CORS_ALLOWED_ORIGINS` and
`CSRF_TRUSTED_ORIGINS`. In particular, set `DJANGO_SECRET_KEY`,
`DJANGO_DEBUG=False`, `DB_ENGINE=postgresql`, `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_SSLMODE=require`, `EMAIL_HOST`,
`EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
`DEFAULT_FROM_EMAIL`, and, once the frontend is deployed, its HTTPS URL as
`FRONTEND_URL`. `FRONTEND_URL` is not required for Wasmer to deploy the backend.
Ensure the other settings are available when Wasmer runs `collectstatic` as well
as at runtime. Django's ASGI app is `config.asgi:application`; the existing
HTTPS proxy header setting is retained.

For a one-time SMTP certificate diagnostic, temporarily add
`"after_deploy": "python manage.py migrate_and_diagnose"` to the existing
`commands` mapping in `python_config(...)`. Leave `python_serve(...)` and
`python_migration_strategy = "django"` unchanged. This overrides only the
generated `after_deploy` command; it does not replace the other generated
commands or build steps. The management command runs migrations first and
starts the SMTP TLS diagnostic only if migrations succeed. After inspecting
the deployment logs, remove the temporary `after_deploy` entry so Anybuild
restores its generated Django migration command. Do not use `&&` here: Wasmer
executes each generated command directly, without shell interpretation. The
diagnostic does not authenticate or send email and is not exposed as an API
endpoint.

The root `Anybuild` file disables cross-platform Python dependency installation
for the Docker runtime image. Anybuild then installs dependencies in its
`/opt/venv` mount, which is copied into the runtime image; the Docker runner
adds `/opt/venv/bin` to runtime `PATH` for both the Uvicorn start command and
the Django `after_deploy` migration. Use the Docker runner for this image
configuration; the separate Wasmer/WASIX runner selects cross-platform wheels.
