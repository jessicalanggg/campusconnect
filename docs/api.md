# API examples

Open interactive API docs at http://localhost:8000/docs.

```bash
curl http://localhost:8000/health
curl 'http://localhost:8000/api/courses?q=CIS'
curl -X POST http://localhost:8000/api/auth/register -H 'Content-Type: application/json' -d '{"email":"student@example.com","name":"Student","password":"password12345"}'
curl -X POST http://localhost:8000/api/auth/login -H 'Content-Type: application/json' -d '{"email":"student@example.com","password":"password12345"}'
# Substitute the JWT from the login response:
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
| POST /api/auth/register | Public | 201 or 409 duplicate email |
| POST /api/auth/login | Public | JWT response; 401 invalid credentials |
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

FastAPI returns 422 for invalid inputs, 401 for missing/invalid credentials, 403 for insufficient ownership, 404 for missing resources, and 409 for state conflicts.
