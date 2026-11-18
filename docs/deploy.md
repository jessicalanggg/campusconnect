# Deploying CampusConnect

The root [`Dockerfile`](../Dockerfile) builds one image that:
- serves the React app and the API from the **same origin**, so session cookies are first-party and no CORS setup is needed
- runs database migrations and seeds the courses on start
- can run the matching scheduler in-process (`RUN_MATCHER_IN_PROCESS=true`) on hosts without background workers

Any Docker host works. The steps below use **Render**, because [`render.yaml`](../render.yaml) sets up the web service and the Postgres database together.

## 1. Email (optional)

Sign-up works with no email setup: it's open by default, and the live config only restricts it to `@upenn.edu` addresses. Email is needed for two things:

- **Verification** (`REQUIRE_EMAIL_VERIFICATION=true`): students confirm they own their Penn address before signing in.
- **"You're matched" emails**: sent when the matcher places a student in a group (not when they're placed instantly on submit, since they see that on screen). These go **only to verified accounts**, so with verification off nobody is emailed. Otherwise anyone could sign up with someone else's address and have the app email them. `NOTIFY_ON_MATCH=false` turns them off.

The app picks the first delivery method that's configured:

| Option | Settings | Notes |
|---|---|---|
| **Resend** (recommended on Render) | `RESEND_API_KEY=re_...`, `EMAIL_FROM=CampusConnect <hello@yourdomain.com>` | Sends over HTTPS, so it works on Render's free plan, which blocks outgoing SMTP ports. Free tier: 3,000 emails a month. Needs a domain you own. |
| **SMTP** (e.g. Gmail app password) | `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM` | Needs a host that allows outgoing SMTP (on Render, a paid instance). Gmail allows about 500 emails a day. |
| Neither | | Emails are written to the log (development). |

**Setting up Resend:**
1. Buy a domain (e.g. at Cloudflare or Namecheap; about $10 a year).
2. At resend.com → **Domains** → **Add domain**, then add the DNS records it shows (SPF, DKIM) at your domain registrar. Wait until Resend shows the domain as verified.
3. Resend → **API Keys** → create a key with "Sending access".
4. In the Render dashboard → your service → **Environment**, set `RESEND_API_KEY` to that key and `EMAIL_FROM` to an address on your domain, e.g. `CampusConnect <hello@yourdomain.com>`. Then set `REQUIRE_EMAIL_VERIFICATION=true`.
5. Sign up with a test Penn address and check the backend logs for `EMAIL SENT to … via Resend` (or `EMAIL FAILED`, which includes Resend's reason). Penn's mail filter sometimes quarantines mail from new domains, so check that your own test message arrived.

## 2. Deploy on Render

1. Render dashboard → **New → Blueprint** → choose the `campusconnect` repo.
2. Fill in the prompted values:
   - `APP_BASE_URL`: your service URL, e.g. `https://campusconnect.onrender.com`. Verification links point here.
   - `ADMIN_EMAILS`: the email you'll sign up with.
   - the email settings from step 1 (`RESEND_API_KEY` and `EMAIL_FROM`), only if you set up email.
3. Deploy. Check `https://<your-service>/health`, then sign up with your admin email.
4. Sign in as the admin. On the **Admin** tab, add the exam dates for your launch courses. Matching then runs automatically in the 14 days before each exam.

### Before real students use it

- **Upgrade the database.** Render's free Postgres expires after 30 days and has no backups, so you'd lose your launch data. The basic paid plan, or a free Neon/Supabase database (set `DATABASE_URL` to its URL), avoids this.
- **Keep the web service awake during exam windows.** Free instances sleep after about 15 minutes idle, and scheduled matching pauses while asleep. Use the Starter plan, or point an uptime monitor (e.g. UptimeRobot) at `/health` every 10 minutes.
- **Keep one instance.** The rate limiter keeps its state in memory per instance. If you scale to several instances, move it to Redis or Postgres.

## Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite file | Postgres URL (`postgres://` URLs are accepted) |
| `SECRET_KEY` | dev value | Signs sessions and verification links; long and random in production |
| `ALLOWED_EMAIL_DOMAINS` | `*` (any) | Accepted email domains, comma-separated; subdomains such as `engineering.upenn.edu` count |
| `REQUIRE_EMAIL_VERIFICATION` | `false` | Require an emailed confirmation link before first sign-in (needs Resend or SMTP) |
| `APP_BASE_URL` | `http://localhost:5173` | Public URL used in confirmation emails |
| `RESEND_API_KEY` | unset | Send email through Resend's HTTPS API (preferred over SMTP when set) |
| `SMTP_*`, `EMAIL_FROM` | unset | SMTP delivery and the sender address; with neither Resend nor SMTP, emails are written to the log |
| `NOTIFY_ON_MATCH` | `true` | Email verified students when they're placed in a group |
| `COOKIE_SECURE` | `true` in the image | Send session cookies only over HTTPS |
| `ADMIN_EMAILS` | unset | Accounts that can add exams and run matching |
| `RUN_MATCHER_IN_PROCESS` | `false` | Run the hourly matching scheduler inside the web process |
| `MATCH_INTERVAL_MINUTES` | `60` | How often the scheduler checks for courses to match |
