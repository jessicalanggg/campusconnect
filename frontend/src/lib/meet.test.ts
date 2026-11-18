import { describe, expect, it } from 'vitest'
import { slotOf, type Group, type Member } from './api'
import { blocks, firstMeeting, groupCalendar, groupMailto, nextOccurrence } from './meet'

const group: Group = {
  id: 7, course_id: 2, course_code: 'CIS 1210', title: 'CIS 1210 · Midterm 1 study group', description: '',
  max_members: 6, member_count: 3, created_at: '2026-11-18T12:00:00Z', match_quality: 0.7,
  common_slots: [slotOf(1, 18), slotOf(1, 19), slotOf(3, 19)], meetings_reported: 0, viewer_status: 'member',
  exam_name: 'Midterm 1', exam_date: '2026-11-27',
}
const members: Member[] = [
  { id: 1, name: 'Ava Chen', email: 'ava@upenn.edu', contact: null },
  { id: 2, name: 'Ben A.', email: 'ben@upenn.edu', contact: 'Discord: ben' },
  { id: 3, name: 'Kai J.', email: 'kai@upenn.edu', contact: null },
]

describe('meeting helpers', () => {
  it('merges consecutive hours into blocks', () => {
    expect(blocks(group.common_slots)).toEqual([{ day: 1, start: 18, end: 20 }, { day: 3, start: 19, end: 20 }])
  })

  it('finds the next occurrence of a weekly block', () => {
    const wed = new Date(2026, 10, 18, 12)  // Wed Nov 18 2026, noon
    expect(nextOccurrence({ day: 1, start: 18, end: 20 }, wed)).toEqual(new Date(2026, 10, 24, 18))  // next Tue
    expect(nextOccurrence({ day: 2, start: 18, end: 20 }, wed)).toEqual(new Date(2026, 10, 18, 18))  // later today
    expect(nextOccurrence({ day: 2, start: 9, end: 10 }, wed)).toEqual(new Date(2026, 10, 25, 9))  // already passed
    expect(firstMeeting(group.common_slots, wed)?.date).toEqual(new Date(2026, 10, 19, 19))  // Thu comes first
  })

  it('builds a weekly calendar that repeats until the exam', () => {
    const ics = groupCalendar(group, members, new Date(2026, 10, 18, 12))
    expect(ics.startsWith('BEGIN:VCALENDAR\r\n')).toBe(true)
    expect(ics.match(/BEGIN:VEVENT/g)).toHaveLength(2)
    expect(ics).toContain('DTSTART;TZID=America/New_York:20261124T180000')
    expect(ics).toContain('DTEND;TZID=America/New_York:20261124T200000')
    expect(ics).toContain('RRULE:FREQ=WEEKLY;UNTIL=20261127T235959Z')
    expect(ics).toContain('Members: Ava Chen\\, Ben A.\\, Kai J.')
  })

  it('emails everyone except me', () => {
    expect(groupMailto(group, members, { email: 'ava@upenn.edu' }))
      .toBe('mailto:ben@upenn.edu,kai@upenn.edu?subject=CIS%201210%20study%20group')
  })
})
