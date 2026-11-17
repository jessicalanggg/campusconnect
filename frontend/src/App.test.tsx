import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App'
import AvailabilityGrid from './components/AvailabilityGrid'
import { describeSlots, slotOf } from './lib/api'

const course = { id: 1, code: 'CIS 1200', title: 'Programming', department: 'CS' }
const metrics = { users: 3, students_requested_match: 3, courses_with_requests: 1, matched_groups: 1, groups_eligible_for_meeting_stats: 1, pct_groups_met_at_least_once: 100, pct_groups_met_at_least_twice: 72.5, returning_students: 1, retention_pct: 33.3, time_to_match_hours_median: 4.5, time_to_match_hours_p90: 20, students_waiting: 0, algorithm: { runs: 2, greedy_avg_quality: 0.55, ilp_avg_quality: 0.66, ilp_quality_gain_pct: 20, greedy_avg_common_hours: 2, ilp_avg_common_hours: 2.5, ilp_overlap_gain_pct: 25 } }

function respond(url: string) {
  if (url.includes('/courses')) return [course]
  if (url.includes('/exams')) return [{ id: 1, course_id: 1, name: 'Midterm 1', exam_date: '2030-03-01' }]
  if (url.includes('/metrics')) return metrics
  return { items: [], total: 0, page: 1, page_size: 9 }
}

beforeEach(() => {
  sessionStorage.clear()
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, status: 200, json: async () => respond(String(url)) })))
})

describe('CampusConnect', () => {
  it('leads with matching and shows the exam window', async () => {
    render(<App />)
    expect(screen.getByText('in your class?')).toBeInTheDocument()
    expect(screen.getByText('Get matched with classmates')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('option', { name: /CIS 1200/ })).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText(/Midterm 1 on/)).toBeInTheDocument())
    // Submitting is disabled until at least two free hours are selected.
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
