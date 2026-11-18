export type User = { id: number; name: string; email: string; is_admin?: boolean }
export type SignupConfig = { allowed_email_domains: string[]; require_email_verification: boolean }
export type Course = { id: number; code: string; title: string; department: string }
/** A study group formed by the matcher (students never create or join groups directly). */
export type Group = {
  id: number; course_id: number; course_code: string; title: string; description: string
  max_members: number; member_count: number; created_at: string
  match_quality: number | null; common_slots: number[]; meetings_reported: number
  viewer_status: 'member' | null
}
export type Goal = 'exam_prep' | 'homework' | 'concepts' | 'projects'
export type MatchRequest = {
  id: number; course_id: number; course_code: string; exam_id: number | null; goal: Goal; pace: number
  preferred_size: number; availability: number[]; status: 'waiting' | 'matched' | 'withdrawn'
  group_id: number | null; created_at: string; matched_at: string | null
}
export type MatchRequestInput = { course_id: number; goal: Goal; pace: number; preferred_size: number; availability: number[] }
export type Exam = { id: number; course_id: number; name: string; exam_date: string }
export type MatchRun = {
  id: number; course_id: number; exam_id: number | null; trigger: string; algorithm: string; students: number
  assigned: number; groups_created: number; greedy_quality: number; local_search_quality: number; ilp_quality: number
  greedy_overlap_hours: number; ilp_overlap_hours: number; runtime_ms: number; created_at: string
}
export type Metrics = {
  users: number; students_requested_match: number; courses_with_requests: number; matched_groups: number
  groups_eligible_for_meeting_stats: number; pct_groups_met_at_least_once: number | null
  pct_groups_met_at_least_twice: number | null; returning_students: number; retention_pct: number | null
  time_to_match_hours_median: number | null; time_to_match_hours_p90: number | null; students_waiting: number
  algorithm: { runs: number; greedy_avg_quality: number | null; ilp_avg_quality: number | null; ilp_quality_gain_pct: number | null
    greedy_avg_common_hours: number | null; ilp_avg_common_hours: number | null; ilp_overlap_gain_pct: number | null }
}

// Weekly availability grid, mirrored from backend/app/matching/engine.py
export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
export const FIRST_HOUR = 8
export const HOURS_PER_DAY = 14
export const slotOf = (day: number, hour: number) => day * HOURS_PER_DAY + (hour - FIRST_HOUR)
export const GOAL_LABELS: Record<Goal, string> = { exam_prep: 'Exam prep', homework: 'Problem sets / homework', concepts: 'Understanding concepts', projects: 'Projects' }
export const PACE_LABELS: Record<number, string> = { 1: 'Slow & thorough', 2: 'Steady', 3: 'Fast' }

/** Human-readable weekly windows, e.g. "Mon 18:00–20:00". */
export function describeSlots(slots: number[]): string {
  const out: string[] = []
  DAYS.forEach((day, d) => {
    const hours = slots.filter(s => Math.floor(s / HOURS_PER_DAY) === d).map(s => s % HOURS_PER_DAY).sort((a, b) => a - b)
    let start: number | null = null, prev: number | null = null
    for (const h of [...hours, null]) {
      if (h !== null && prev !== null && h === prev + 1) { prev = h; continue }
      if (start !== null && prev !== null) out.push(`${day} ${String(FIRST_HOUR + start).padStart(2, '0')}:00–${String(FIRST_HOUR + prev + 1).padStart(2, '0')}:00`)
      start = prev = h
    }
  })
  return out.join(', ')
}

const BASE = import.meta.env.VITE_API_URL || ''
const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

/** The session lives in an HttpOnly cookie (unreadable here); writes echo the readable CSRF cookie in a header. */
function csrfToken(): string {
  const match = document.cookie.split('; ').find(c => c.startsWith('cc_csrf='))
  return match ? decodeURIComponent(match.slice('cc_csrf='.length)) : ''
}

export class ApiError extends Error { constructor(public status: number, message: string) { super(message) } }
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method || 'GET').toUpperCase()
  let response: Response
  try {
    response = await fetch(`${BASE}/api${path}`, {
      ...init,
      credentials: 'include',
      headers: { ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...(UNSAFE.has(method) ? { 'X-CSRF-Token': csrfToken() } : {}), ...init.headers },
    })
  } catch { throw new ApiError(0, 'Unable to reach the server. Please try again.') }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    const detail = Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail
    const message = typeof detail === 'string' ? detail.replace(/^Value error, /, '') : response.status === 422 ? 'Please check your form fields.' : response.status === 429 ? 'Too many requests. Please wait a bit and try again.' : `Request failed (${response.status})`
    throw new ApiError(response.status, message)
  }
  if (response.status === 204 || response.status === 202) return (response.status === 202 ? await response.json().catch(() => undefined) : undefined) as T
  return response.json() as Promise<T>
}
