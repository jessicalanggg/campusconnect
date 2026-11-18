from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./campusconnect.db"
    secret_key: str = "CHANGE_ME_FOR_LOCAL_DEV_ONLY"
    access_token_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://localhost:5173"
    # Comma-separated emails allowed to manage exams and trigger matching runs.
    admin_emails: str = ""

    # --- Accounts: Penn-only signup with email verification
    # Comma-separated domains; subdomains are accepted too (e.g. seas.upenn.edu for upenn.edu).
    allowed_email_domains: str = "upenn.edu"
    verify_token_hours: int = 48
    # Where verification links point (the frontend's public URL).
    app_base_url: str = "http://localhost:5173"
    # SMTP for verification emails. When smtp_host is empty, emails are logged instead of sent (development).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    email_from: str = "CampusConnect <no-reply@localhost>"

    # --- Session cookies (HttpOnly) and CSRF
    cookie_secure: bool = False  # set true in production (HTTPS)
    rate_limit_enabled: bool = True

    # --- Matching
    # Matching runs automatically for a course during this many days before each of its exams.
    match_window_days: int = 14
    # Outside exam windows, waiting students are batched until the oldest has waited this long.
    match_max_wait_hours: int = 24
    match_interval_minutes: int = 60
    ilp_time_limit_seconds: float = 5.0
    # Run the matching scheduler inside the web process (for hosts without background workers).
    run_matcher_in_process: bool = False

    # --- Deployment: serve the built frontend from this directory (single-service deploys)
    static_dir: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def normalize_postgres_url(cls, v: str) -> str:
        # Hosts like Render/Railway/Heroku hand out postgres:// URLs; SQLAlchemy needs the psycopg driver name.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    def is_admin(self, email: str) -> bool:
        return email.lower() in {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    def email_allowed(self, email: str) -> bool:
        domain = email.rsplit("@", 1)[-1].lower()
        allowed = [d.strip().lower().lstrip("@") for d in self.allowed_email_domains.split(",") if d.strip()]
        return any(domain == d or domain.endswith("." + d) for d in allowed)


settings = Settings()
