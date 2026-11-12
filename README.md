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
database is configured. `.env` is ignored by Git.

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
token, except registration, login, refresh, and password reset. Health and API
documentation routes remain public. Send protected requests with
`Authorization: Bearer <access-token>`.

- `POST /api/auth/register/` — create an account and return account details and
  an access/refresh token pair.
- `POST /api/auth/login/` — authenticate with email and password.
- `POST /api/auth/token/refresh/` — obtain a new access token; refresh tokens
  rotate and the previous refresh token is blacklisted.
- `POST /api/auth/logout/` — blacklist the authenticated user's refresh token.
- `POST /api/auth/password-reset/` — request password-reset instructions.
- `POST /api/auth/password-reset/confirm/` — confirm a reset with the emailed
  UID and token.
- `GET /api/account/` and `PATCH /api/account/` — read or update the
  authenticated user's own name and email.
- `GET /api/profile/` and `PATCH /api/profile/` — read or update the
  authenticated user's own profile and education information.
- `GET /api/profile/skills/`, `POST /api/profile/skills/`, and
  `DELETE /api/profile/skills/<skill_id>/` — manage the current user's skills.
- `GET /api/profile/interests/`, `POST /api/profile/interests/`, and
  `DELETE /api/profile/interests/<interest_id>/` — manage the current user's
  interests.
- `GET /api/profile/portfolio/`, `POST /api/profile/portfolio/`,
  `PATCH /api/profile/portfolio/<id>/`, and
  `DELETE /api/profile/portfolio/<id>/` — manage the current user's portfolio.
- `GET /api/skills/` and `GET /api/interests/` — list reusable skills and
  interests.
- `GET /api/users/<id>/` — retrieve an authenticated user's public profile.
- `GET /api/users/` — discover other active users with profiles.

Profile discovery supports combining `search`, `university`, `major`,
`study_year`, `skill`, and `interest` query parameters. Results are paginated
with a default page size of 10; `page_size` may be set up to 50. Search results
contain a brief profile summary, while the individual public-profile endpoint
includes the profile, skills with proficiency, interests, and portfolio.

Access tokens last 30 minutes and refresh tokens last 7 days. Blacklisting a
refresh token does **not** immediately invalidate an already-issued access
token; access tokens remain usable until they expire.

In local development, password-reset email is printed to the terminal by
Django's console email backend. The link uses `FRONTEND_URL` and points to
`/reset-password/confirm/` with `uid` and `token` query parameters. For an email
provider, configure `EMAIL_BACKEND` as Django's SMTP backend and set
`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
`EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL` in `.env`. Real provider delivery has
not been configured or verified.

Visit <http://127.0.0.1:8000/admin/> to manage records.
