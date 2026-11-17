from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./campusconnect.db"
    secret_key: str = "CHANGE_ME_FOR_LOCAL_DEV_ONLY"
    access_token_minutes: int = 60
    cors_origins: str = "http://localhost:5173"
    # Comma-separated emails allowed to manage exams and trigger matching runs.
    admin_emails: str = ""
    # Matching runs automatically for a course during this many days before each of its exams.
    match_window_days: int = 14
    # Outside exam windows, waiting students are batched until the oldest has waited this long.
    match_max_wait_hours: int = 24
    match_interval_minutes: int = 60
    ilp_time_limit_seconds: float = 5.0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def is_admin(self, email: str) -> bool:
        return email.lower() in {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


settings = Settings()
