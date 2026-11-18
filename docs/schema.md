# Data model

```mermaid
erDiagram
 USERS ||--o{ MEMBERSHIPS : joins
 COURSES ||--o{ STUDY_GROUPS : includes
 STUDY_GROUPS ||--o{ MEMBERSHIPS : has
 STUDY_GROUPS ||--o{ MEETING_CHECKINS : reports
 COURSES ||--o{ EXAMS : schedules
 COURSES ||--o{ MATCH_REQUESTS : pools
 USERS ||--o{ MATCH_REQUESTS : submits
 MATCH_RUNS ||--o{ STUDY_GROUPS : forms
 USERS { int id PK string email UK string name string password_hash }
 COURSES { int id PK string code UK string title string department }
 STUDY_GROUPS { int id PK int course_id FK string title float match_quality json common_slots int max_members int match_run_id FK }
 EXAMS { int id PK int course_id FK string name date exam_date }
 MATCH_REQUESTS { int id PK int user_id FK int course_id FK int exam_id FK string goal int pace int preferred_size json availability string status int group_id FK json left_group_ids datetime matched_at }
 MATCH_RUNS { int id PK int course_id FK string trigger int students int assigned float greedy_quality float ilp_quality float greedy_overlap_hours float ilp_overlap_hours }
 MEETING_CHECKINS { int id PK int user_id FK int group_id FK bool met date met_on }
 MEMBERSHIPS { int id PK int user_id FK int group_id FK datetime joined_at }
```

`memberships` has a unique constraint on `(user_id, group_id)`; `study_groups.max_members` has a database CHECK >= 2.

All groups are formed by the matcher. They have no owner, any member may leave, and only members (and admins) can see them. Migration 004 removed student-created groups and the old `waitlist_entries` table; the unused `owner_id` and `kind` columns remain for compatibility. `meeting_checkins` is unique on `(user_id, group_id, met_on)`: a group "met" on a date if any member reported `met = true` for it.
