import { DAYS, FIRST_HOUR, HOURS_PER_DAY, type Group, type Member } from './api'

/** A contiguous weekly block of shared free time, e.g. Tue 18:00–20:00 (day 0 = Monday). */
export type Block = { day: number; start: number; end: number }

export function blocks(slots: number[]): Block[] {
  const out: Block[] = []
  for (const s of [...new Set(slots)].sort((a, b) => a - b)) {
    const day = Math.floor(s / HOURS_PER_DAY), hour = FIRST_HOUR + (s % HOURS_PER_DAY)
    const last = out[out.length - 1]
    if (last && last.day === day && last.end === hour) last.end = hour + 1
    else out.push({ day, start: hour, end: hour + 1 })
  }
  return out
}

/** The next date (local time) on which `block` starts after `from`. */
export function nextOccurrence(block: Block, from = new Date()): Date {
  const d = new Date(from)
  d.setHours(block.start, 0, 0, 0)
  const jsDay = (block.day + 1) % 7  // Monday-first grid → JS Sunday-first
  let add = (jsDay - d.getDay() + 7) % 7
  if (add === 0 && d <= from) add = 7
  d.setDate(d.getDate() + add)
  return d
}

/** The soonest upcoming shared block: a natural first meeting. */
export function firstMeeting(slots: number[], from = new Date()): { block: Block; date: Date } | null {
  const options = blocks(slots).map(block => ({ block, date: nextOccurrence(block, from) }))
  options.sort((a, b) => a.date.getTime() - b.date.getTime())
  return options[0] ?? null
}

const hh = (h: number) => `${String(h).padStart(2, '0')}:00`
export const describeBlock = (b: Block) => `${DAYS[b.day]} ${hh(b.start)}–${hh(b.end)}`

const pad = (n: number) => String(n).padStart(2, '0')
const icsLocal = (d: Date) => `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}T${pad(d.getHours())}0000`
const icsUtc = (d: Date) => d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')
const icsText = (s: string) => s.replace(/\\/g, '\\\\').replace(/[,;]/g, m => '\\' + m).replace(/\n/g, '\\n')

/** A calendar file with one weekly event per shared block, repeating until the group's exam (or for 8 weeks).
 * Times are Penn local time (America/New_York), the same hours students marked on the grid. */
export function groupCalendar(group: Group, members: Member[], now = new Date()): string {
  const until = group.exam_date ? `UNTIL=${group.exam_date.replace(/-/g, '')}T235959Z` : 'COUNT=8'
  const names = members.map(m => m.name).join(', ')
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//CampusConnect//Study groups//EN', 'CALSCALE:GREGORIAN',
    'BEGIN:VTIMEZONE', 'TZID:America/New_York',
    'BEGIN:DAYLIGHT', 'TZOFFSETFROM:-0500', 'TZOFFSETTO:-0400', 'TZNAME:EDT', 'DTSTART:19700308T020000', 'RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU', 'END:DAYLIGHT',
    'BEGIN:STANDARD', 'TZOFFSETFROM:-0400', 'TZOFFSETTO:-0500', 'TZNAME:EST', 'DTSTART:19701101T020000', 'RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU', 'END:STANDARD',
    'END:VTIMEZONE']
  for (const b of blocks(group.common_slots)) {
    const start = nextOccurrence(b, now), end = new Date(start)
    end.setHours(b.end)
    lines.push('BEGIN:VEVENT', `UID:campusconnect-group-${group.id}-${b.day}-${b.start}@campusconnect`, `DTSTAMP:${icsUtc(now)}`,
      `DTSTART;TZID=America/New_York:${icsLocal(start)}`, `DTEND;TZID=America/New_York:${icsLocal(end)}`,
      `RRULE:FREQ=WEEKLY;${until}`, `SUMMARY:${icsText(`${group.course_code} study group`)}`,
      `DESCRIPTION:${icsText(`${group.title}\nMembers: ${names}\nEveryone in the group is free at this time.`)}`, 'END:VEVENT')
  }
  lines.push('END:VCALENDAR')
  return lines.join('\r\n') + '\r\n'
}

export function downloadFile(name: string, text: string, type = 'text/calendar') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url; a.download = name
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** A mailto: link addressed to everyone else in the group. */
export function groupMailto(group: Group, members: Member[], me: { email: string } | null): string {
  const to = members.filter(m => m.email !== me?.email).map(m => m.email).join(',')
  const subject = encodeURIComponent(`${group.course_code} study group`)
  return `mailto:${to}?subject=${subject}`
}
