# TeamUp Backend

TeamUp's backend is a Django REST Framework API for students and professors to
find teammates and collaborate on academic opportunities. The foundation
includes a custom email-based user, profiles, skills, interests, and portfolio
models. Feature APIs will be added in later stages.

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

The project currently uses Django's default SQLite configuration. No
production database is configured. Django's built-in authentication and Admin
are enabled for the custom user model, but no registration or login APIs are
implemented. Visit <http://127.0.0.1:8000/admin/> to manage records.
