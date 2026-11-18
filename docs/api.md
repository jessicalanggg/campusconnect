# API examples

Open interactive API docs at http://localhost:8000/docs.

```bash
curl http://localhost:8000/health
curl 'http://localhost:8000/api/courses?q=CIS'
curl -X POST http://localhost:8000/api/auth/register -H 'Content-Type: application/json' -d '{"email":"student@upenn.edu","name":"Student","password":"password12345"}'
# Only when REQUIRE_EMAIL_VERIFICATION=true: confirm with the token from the emailed (or logged) link
curl -X POST http://localhost:8000/api/auth/verify -H 'Content-Type: application/json' -d '{"token":"TOKEN_FROM_LINK"}'
curl -X POST http://localhost:8000/api/auth/login -H 'Content-Type: application/json' -d '{"email":"student@upenn.edu","password":"password12345"}'
# Browsers use the HttpOnly session cookie set by login. API clients can send the returned token instead:
curl -X POST http://localhost:8000/api/groups -H 'Content-Type: application/json' -H 'Authorization: Bearer YOUR_TOKEN' -d '{"course_id":1,"title":"Algorithms study circle","description":"Weekly review","max_members":8}'
curl 'http://localhost:8000/api/groups?q=algorithms&page=1&page_size=10'
curl -X POST http://localhost:8000/api/groups/1/join -H 'Authorization: Bearer YOUR_TOKEN'
# Request a match. Availability = hour slots, index = day*14 + (hour-8), Mon=0; e.g. Mon 18:00-20:00 = 10, 11
curl -X POST http://localhost:8000/api/match/requests -H 'Content-Type: application/json' -H 'Authorization: Bearer YOUR_TOKEN' -d '{"course_id":1,"goal":"exam_prep","pace":2,"preferred_size":4,"availability":[10,11,38,39]}'
curl http://localhost:8000/api/metrics
```

Admins are the accounts listed in `ADMIN_EMAILS`.

| Route | Authentication | Notes |
| --- | --- | --- |
| GET /api/config | Public | Sign-up rules: `allowed_email_domains` (empty = any) and `require_email_verification` |
| POST /api/auth/register | Public | 422 if the domain isn't allowed; emails a confirmation link when verification is on; 409 duplicate |
| POST /api/auth/verify | Public | `{"token": ...}` from the emailed link; marks the email verified |
| POST /api/auth/resend-verification | Public | Always 202 (doesn't reveal whether an account exists); 3 per 15 min per email |
| POST /api/auth/login | Public | Sets HttpOnly `cc_session` and readable `cc_csrf` cookies, and returns the token; 403 until verified (when verification is on); 10 attempts per 5 min per email |
| POST /api/auth/logout | Public | Clears the session cookies |
| GET /api/auth/me | Required | Current account |
| GET /api/courses?q= | Public | Case-insensitive course search |
| GET /api/groups?q=&course_id=&kind=&page=&page_size= | Public | Paginated, page size 1–50; `kind` = manual (default), matched, all. Includes `viewer_status` when signed in |
| GET /api/groups/mine | Required | Groups you're in or waitlisted for |
| GET /api/groups/{id} | Public | Group details |
| GET /api/groups/{id}/members | Public | Group roster |
| POST /api/groups | Required | Creates group and joins owner |
| PATCH /api/groups/{id} | Owner | Edit title/description/capacity |
| DELETE /api/groups/{id} | Owner | Delete group |
| POST /api/groups/{id}/join | Required | Manual groups only; 409 if full or already joined |
| POST /api/groups/{id}/waitlist | Required | Full manual groups; FIFO promotion when a seat opens or capacity rises |
| DELETE /api/groups/{id}/waitlist/me | Required | Leave the waitlist |
| DELETE /api/groups/{id}/members/me?rematch= | Required | Owner cannot leave. For matched groups, `rematch=true` requeues you (never into the same group) |
| POST /api/groups/{id}/checkins | Member | `{"met": true, "met_on": "2026-11-17"}`; one answer per member per date |
| POST /api/match/requests | Required | Join the matching pool for a course; may be placed instantly into an open matched group |
| GET /api/match/requests | Required | Your match requests (all cycles) |
| PATCH /api/match/requests/{id} | Owner | Update schedule/preferences; rematches you if your group can no longer meet |
| DELETE /api/match/requests/{id} | Owner | Withdraw (leaves your matched group) |
| GET /api/exams?course_id=&upcoming= | Public | Exam dates that drive automatic matching windows |
| GET /api/metrics | Public | Aggregate outcomes: meeting rates, retention, time to match, ILP vs greedy |
| POST /api/admin/exams | Admin | Add an exam date |
| POST /api/admin/courses/{id}/match | Admin | Run a matching round now |
| GET /api/admin/match-runs?course_id= | Admin | Per-round algorithm comparison |

Cookie-authenticated `POST`/`PATCH`/`DELETE` requests must send `X-CSRF-Token` equal to the `cc_csrf` cookie. Requests using `Authorization: Bearer` don't need it. Rate-limited endpoints return 429 with `Retry-After`.

FastAPI returns 422 for invalid inputs, 401 for missing/invalid credentials, 403 for insufficient ownership, 404 for missing resources, and 409 for state conflicts.
