import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ArrowRight, CalendarClock, CheckCircle2, Clock, Pencil, Sparkles, X } from 'lucide-react'
import AvailabilityGrid from './AvailabilityGrid'
import { api, GOAL_LABELS, PACE_LABELS, type Course, type Exam, type Goal, type MatchRequest, type MatchRequestInput, type User } from '../lib/api'

type Props = {
  user: User | null; courses: Course[]; onNeedAuth: () => void; onOpenGroup: (groupId: number) => void
  onChanged: () => void; notify: (msg: string) => void; fail: (msg: string) => void
}

function shortDate(d: string) { return new Date(d + (d.length === 10 ? 'T12:00:00' : '')).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) }

export default function MatchPanel({ user, courses, onNeedAuth, onOpenGroup, onChanged, notify, fail }: Props) {
  const [requests, setRequests] = useState<MatchRequest[]>([])
  const [exams, setExams] = useState<Exam[]>([])
  const [form, setForm] = useState<MatchRequestInput>({ course_id: 0, goal: 'exam_prep', pace: 2, preferred_size: 4, availability: [] })
  const [editing, setEditing] = useState<MatchRequest | null>(null)
  const [editSlots, setEditSlots] = useState<number[]>([])
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (!user) { setRequests([]); return }
    try {
      const rows = await api<MatchRequest[]>('/match/requests')
      setRequests(rows)
      // Prefill the schedule from the most recent request so returning students don't re-enter it.
      if (rows[0]) setForm(f => f.availability.length ? f : { ...f, availability: rows[0].availability, pace: rows[0].pace, preferred_size: rows[0].preferred_size })
    } catch (e) { fail((e as Error).message) }
  }, [user, fail])
  useEffect(() => { load() }, [load])
  useEffect(() => { if (!form.course_id && courses[0]) setForm(f => ({ ...f, course_id: courses[0].id })) }, [courses, form.course_id])
  useEffect(() => {
    if (!form.course_id) return
    api<Exam[]>(`/exams?course_id=${form.course_id}`).then(setExams).catch(() => setExams([]))
  }, [form.course_id])

  const active = requests.filter(r => r.status !== 'withdrawn')
  const hasActive = active.some(r => r.course_id === form.course_id)
  const nextExam = exams[0]

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!user) { onNeedAuth(); return }
    setBusy(true)
    try {
      const r = await api<MatchRequest>('/match/requests', { method: 'POST', body: JSON.stringify(form) })
      notify(r.status === 'matched' ? 'You were matched straight into a group with open seats!' : 'You’re in the matching pool. We’ll place you in the next matching round.')
      await load(); onChanged()
    } catch (e) { fail((e as Error).message) } finally { setBusy(false) }
  }
  async function saveSchedule() {
    if (!editing) return
    setBusy(true)
    try {
      const r = await api<MatchRequest>(`/match/requests/${editing.id}`, { method: 'PATCH', body: JSON.stringify({ availability: editSlots }) })
      notify(editing.status === 'matched' && r.status === 'waiting' ? 'Your new schedule no longer overlaps your group, so we’re finding you a new one.' : 'Schedule updated.')
      setEditing(null); await load(); onChanged()
    } catch (e) { fail((e as Error).message) } finally { setBusy(false) }
  }
  async function withdraw(r: MatchRequest) {
    if (!window.confirm(r.status === 'matched' ? `Withdraw from matching for ${r.course_code}? You’ll leave your matched group.` : `Stop looking for a group in ${r.course_code}?`)) return
    setBusy(true)
    try { await api(`/match/requests/${r.id}`, { method: 'DELETE' }); notify('Match request withdrawn.'); await load(); onChanged() }
    catch (e) { fail((e as Error).message) } finally { setBusy(false) }
  }

  return <section id="match" className="container match">
    <div className="section-heading"><div><div className="section-kicker">DON’T KNOW ANYONE IN YOUR CLASS?</div><h2>Get matched with classmates</h2><p>Tell us when you’re free and how you like to study. We form groups that can actually meet.</p></div></div>
    {active.length > 0 && <div className="request-list">{active.map(r => <div className={`request-card ${r.status}`} key={r.id}>
      <div className="request-main">
        {r.status === 'matched' ? <CheckCircle2 size={22}/> : <Clock size={22}/>}
        <div><strong>{r.course_code}</strong> · {GOAL_LABELS[r.goal]}<small>{r.status === 'matched' ? `Matched ${r.matched_at ? shortDate(r.matched_at) : ''}` : `Waiting since ${shortDate(r.created_at)} for the next matching round`}</small></div>
      </div>
      <div className="request-actions">
        {r.status === 'matched' && r.group_id && <button className="btn primary" onClick={() => onOpenGroup(r.group_id!)}>View group <ArrowRight size={15}/></button>}
        <button className="btn secondary" onClick={() => { setEditing(r); setEditSlots(r.availability) }}><Pencil size={15}/> Schedule</button>
        <button className="btn ghost" disabled={busy} onClick={() => withdraw(r)}><X size={15}/> Withdraw</button>
      </div>
    </div>)}</div>}
    <form className="match-form" onSubmit={submit}>
      <div className="match-fields">
        <label>Course<select value={form.course_id || ''} onChange={e => setForm({ ...form, course_id: Number(e.target.value) })}>{courses.map(c => <option key={c.id} value={c.id}>{c.code} — {c.title}</option>)}</select></label>
        {nextExam && <div className="exam-note"><CalendarClock size={16}/> {nextExam.name} on {shortDate(nextExam.exam_date)}: groups form automatically in the two weeks before.</div>}
        <label>What do you want to work on?<select value={form.goal} onChange={e => setForm({ ...form, goal: e.target.value as Goal })}>{Object.entries(GOAL_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label>Your pace<div className="segmented">{[1, 2, 3].map(p => <button type="button" key={p} className={form.pace === p ? 'on' : ''} onClick={() => setForm({ ...form, pace: p })}>{PACE_LABELS[p]}</button>)}</div></label>
        <label>Preferred group size<div className="segmented">{[3, 4, 5, 6].map(n => <button type="button" key={n} className={form.preferred_size === n ? 'on' : ''} onClick={() => setForm({ ...form, preferred_size: n })}>{n}</button>)}</div></label>
        <button className="btn primary full" disabled={busy || hasActive || form.availability.length < 2}>{hasActive ? 'Already matching for this course' : busy ? 'Please wait…' : <>Find my group <Sparkles size={16}/></>}</button>
        {form.availability.length < 2 && <small className="hint">Select at least 2 free hours on the grid.</small>}
      </div>
      <div><div className="grid-label">When are you free each week?</div><AvailabilityGrid value={form.availability} onChange={availability => setForm({ ...form, availability })}/></div>
    </form>
    {editing && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) setEditing(null) }}><div className="modal wide" role="dialog" aria-modal="true" aria-label="Edit schedule"><button className="close" aria-label="Close" onClick={() => setEditing(null)}><X/></button><h2>Update your schedule</h2><p>{editing.status === 'matched' ? 'If your group can no longer meet with your new hours, we’ll automatically find you a new group.' : 'Your updated hours are used in the next matching round.'}</p><AvailabilityGrid value={editSlots} onChange={setEditSlots}/><button className="btn primary full" disabled={busy || editSlots.length < 2} onClick={saveSchedule}>Save schedule</button></div></div>}
  </section>
}
