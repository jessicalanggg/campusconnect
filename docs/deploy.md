# Deploying CampusConnect

The root [`Dockerfile`](../Dockerfile) builds one image that:
- serves the React app and the API from the **same origin**, so session cookies are first-party and no CORS setup is needed
- runs database migrations and seeds the courses on start
- can run the matching scheduler in-process (`RUN_MATCHER_IN_PROCESS=true`) on hosts without background workers

Any Docker host works. The steps below use **Render**, because [`render.yaml`](../render.yaml) sets up the web service and the Postgres database together.

## 1. Email (optional)

Sign-up is open to any email with no confirmation step by default, so no email setup is needed. To require students to confirm their address, set `REQUIRE_EMAIL_VERIFICATION=true`, and optionally restrict sign-up to a school with `ALLOWED_EMAIL_DOMAINS=upenn.edu`. Then the app needs a way to send email:

| Option | SMTP settings | Notes |
|---|---|---|
| **Gmail app password** (quickest) | `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER=you@gmail.com`, `SMTP_PASSWORD=<16-character app password>` | Turn on 2-Step Verification, then create an app password at myaccount.google.com/apppasswords. About 500 emails/day. |
| **Resend / SendGrid / Postmark** | Use the provider's SMTP host, user and API key | Better deliverability and higher limits; usually needs a domain you own. |

Set `EMAIL_FROM` to the sending address, e.g. `CampusConnect <you@gmail.com>`.

**Free Render instances may block outgoing SMTP ports** (check Render's docs for your plan), in which case Gmail SMTP needs a paid instance. Check the backend logs for `EMAIL SENT` or `EMAIL FAILED` after a sign-up. If you're sending to Penn addresses, send yourself a test first and check that Penn's filter didn't quarantine it.

## 2. Deploy on Render

1. Render dashboard → **New → Blueprint** → choose the `campusconnect` repo.
2. Fill in the prompted values:
   - `APP_BASE_URL`: your service URL, e.g. `https://campusconnect.onrender.com`. Verification links point here.
   - `ADMIN_EMAILS`: the email you'll sign up with.
   - the SMTP settings from step 1, only if you turned verification on.
3. Deploy. Check `https://<your-service>/health`, then sign up with your admin email.
4. Sign in as the admin. On the **Impact** tab, add the exam dates for your launch courses. Matching then runs automatically in the 14 days before each exam.

### Before real students use it

- **Upgrade the database.** Render's free Postgres expires after 30 days and has no backups, so you'd lose your launch data. The basic paid plan, or a free Neon/Supabase database (set `DATABASE_URL` to its URL), avoids this.
- **Keep the web service awake during exam windows.** Free instances sleep after about 15 minutes idle, and scheduled matching pauses while asleep. Use the Starter plan, or point an uptime monitor (e.g. UptimeRobot) at `/health` every 10 minutes.
- **Keep one instance.** The rate limiter keeps its state in memory per instance. If you scale to several instances, move it to Redis or Postgres.

## Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite file | Postgres URL (`postgres://` URLs are accepted) |
| `SECRET_KEY` | dev value | Signs sessions and verification links; long and random in production |
| `ALLOWED_EMAIL_DOMAINS` | `*` (any) | Accepted email domains, comma-separated; subdomains such as `seas.upenn.edu` count |
| `REQUIRE_EMAIL_VERIFICATION` | `false` | Require an emailed confirmation link before first sign-in (needs `SMTP_*`) |
| `APP_BASE_URL` | `http://localhost:5173` | Public URL used in confirmation emails |
| `SMTP_*`, `EMAIL_FROM` | unset | Email delivery; when `SMTP_HOST` is empty, emails are written to the log instead |
| `COOKIE_SECURE` | `true` in the image | Send session cookies only over HTTPS |
| `ADMIN_EMAILS` | unset | Accounts that can add exams and run matching |
| `RUN_MATCHER_IN_PROCESS` | `false` | Run the hourly matching scheduler inside the web process |
| `MATCH_INTERVAL_MINUTES` | `60` | How often the scheduler checks for courses to match |
