import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App'
import AvailabilityGrid from './components/AvailabilityGrid'
import { api, describeSlots, slotOf } from './lib/api'

const course = { id: 1, code: 'CIS 1200', title: 'Programming', department: 'CS' }
const metrics = { users: 3, students_requested_match: 3, courses_with_requests: 1, matched_groups: 1, groups_eligible_for_meeting_stats: 1, pct_groups_met_at_least_once: 100, pct_groups_met_at_least_twice: 72.5, returning_students: 1, retention_pct: 33.3, time_to_match_hours_median: 4.5, time_to_match_hours_p90: 20, students_waiting: 0, algorithm: { runs: 2, greedy_avg_quality: 0.55, ilp_avg_quality: 0.66, ilp_quality_gain_pct: 20, greedy_avg_common_hours: 2, ilp_avg_common_hours: 2.5, ilp_overlap_gain_pct: 25 } }

type Reply = { status?: number; body?: unknown }
let overrides: Record<string, Reply> = {}
const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
  void init  // recorded in mock.calls for assertions
  const u = String(url)
  const hit = Object.entries(overrides).find(([k]) => u.includes(k))
  if (hit) { const { status = 200, body = {} } = hit[1]; return { ok: status < 400, status, json: async () => body } }
  if (u.includes('/auth/me')) return { ok: false, status: 401, json: async () => ({ detail: 'Authentication required' }) }
  const body = u.includes('/courses') ? [course]
    : u.includes('/exams') ? [{ id: 1, course_id: 1, name: 'Midterm 1', exam_date: '2030-03-01' }]
    : u.includes('/metrics') ? metrics
    : { items: [], total: 0, page: 1, page_size: 9 }
  return { ok: true, status: 200, json: async () => body }
})

beforeEach(() => {
  overrides = {}
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
  window.history.replaceState(null, '', '/')
  document.cookie = 'cc_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
})

describe('CampusConnect', () => {
  it('leads with matching and shows the exam window', async () => {
    render(<App />)
    expect(screen.getByText('in your class?')).toBeInTheDocument()
    expect(screen.getByText('Get matched with classmates')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('option', { name: /CIS 1200/ })).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText(/Midterm 1 on/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Find my group/ })).toBeDisabled()
  })

  it('shows outcome metrics on the impact tab', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Impact' }))
    await waitFor(() => expect(screen.getByText('72.5%')).toBeInTheDocument())
    expect(screen.getByText('of matched groups met at least twice')).toBeInTheDocument()
    expect(screen.getByText('+20%')).toBeInTheDocument()
  })

  it('browses open groups', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Explore groups' }))
    await waitFor(() => expect(screen.getByText('No groups found')).toBeInTheDocument())
  })
})

describe('Penn email verification', () => {
  it('asks new students to check their Penn inbox instead of signing them in', async () => {
    overrides['/auth/register'] = { status: 201, body: { id: 1, email: 'ben@seas.upenn.edu', name: 'Ben' } }
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: /Get started/ }))
    fireEvent.change(screen.getByPlaceholderText('Your name'), { target: { value: 'Ben' } })
    fireEvent.change(screen.getByPlaceholderText('you@upenn.edu'), { target: { value: 'ben@seas.upenn.edu' } })
    fireEvent.change(screen.getByPlaceholderText('At least 8 characters'), { target: { value: 'long-password-1' } })
    fireEvent.click(screen.getByRole('button', { name: /Create account/ }))
    await waitFor(() => expect(screen.getByText(/We sent a verification link to ben@seas.upenn.edu/)).toBeInTheDocument())
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/auth/login'))).toBe(false)
  })

  it('offers to resend the link when an unverified student signs in', async () => {
    overrides['/auth/login'] = { status: 403, body: { detail: 'Verify your Penn email first. Check your inbox for the link.' } }
    overrides['/auth/resend-verification'] = { status: 202, body: { detail: 'ok' } }
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }))
    fireEvent.change(screen.getByPlaceholderText('you@upenn.edu'), { target: { value: 'ben@upenn.edu' } })
    fireEvent.change(screen.getByPlaceholderText('At least 8 characters'), { target: { value: 'long-password-1' } })
    fireEvent.click(screen.getByRole('button', { name: /^Sign in/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Resend link' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Resend link' }))
    await waitFor(() => expect(screen.getByText(/A new verification link is on its way to ben@upenn.edu/)).toBeInTheDocument())
  })

  it('confirms the email from the link and opens sign-in', async () => {
    overrides['/auth/verify'] = { status: 200, body: { id: 1, email: 'ben@upenn.edu', name: 'Ben' } }
    window.history.replaceState(null, '', '/?verify=abc.def.ghi')
    render(<App />)
    await waitFor(() => expect(screen.getByText('Your Penn email is verified. Sign in to get matched.')).toBeInTheDocument())
    expect(window.location.search).toBe('')  // token removed from the address bar
    const verifyCall = fetchMock.mock.calls.find(([u]) => String(u).includes('/auth/verify'))!
    expect(JSON.parse((verifyCall[1] as RequestInit).body as string)).toEqual({ token: 'abc.def.ghi' })
  })
})

describe('api client', () => {
  it('sends cookies, and echoes the CSRF cookie on writes only', async () => {
    document.cookie = 'cc_csrf=token123'
    await api('/groups', { method: 'POST', body: '{}' })
    await api('/courses')
    const [post, get] = fetchMock.mock.calls.map(c => c[1] as RequestInit)
    expect(post.credentials).toBe('include')
    expect((post.headers as Record<string, string>)['X-CSRF-Token']).toBe('token123')
    expect((get.headers as Record<string, string>)['X-CSRF-Token']).toBeUndefined()
  })
})

describe('availability', () => {
  it('toggles and drag-paints cells', () => {
    const onChange = vi.fn()
    const { rerender } = render(<AvailabilityGrid value={[]} onChange={onChange} />)
    fireEvent.pointerDown(screen.getByRole('gridcell', { name: 'Mon 18:00' }))
    expect(onChange).toHaveBeenLastCalledWith([slotOf(0, 18)])
    rerender(<AvailabilityGrid value={[slotOf(0, 18)]} onChange={onChange} />)
    fireEvent.pointerEnter(screen.getByRole('gridcell', { name: 'Mon 19:00' }))
    expect(onChange).toHaveBeenLastCalledWith([slotOf(0, 18), slotOf(0, 19)])
  })

  it('describes slots like the backend', () => {
    expect(describeSlots([slotOf(0, 18), slotOf(0, 19), slotOf(2, 9)])).toBe('Mon 18:00–20:00, Wed 09:00–10:00')
  })
})
