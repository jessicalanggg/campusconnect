import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Play } from 'lucide-react'
import { api, type Course, type MatchRun } from '../lib/api'

type Props = { courses: Course[]; notify: (msg: string) => void; fail: (msg: string) => void; onChanged: () => void }

/** Admin tools: add exam dates (which drive automatic matching windows) and run matching on demand. */
export default function AdminPanel({ courses, notify, fail, onChanged }: Props) {
  const [runs, setRuns] = useState<MatchRun[]>([])
  const [exam, setExam] = useState({ course_id: 0, name: 'Midterm 1', exam_date: '' })
  const [busy, setBusy] = useState(false)
  const code = (id: number) => courses.find(c => c.id === id)?.code ?? `#${id}`
  const load = useCallback(() => api<MatchRun[]>('/admin/match-runs').then(setRuns).catch(e => fail(e.message)), [fail])
  useEffect(() => { load() }, [load])
  useEffect(() => { if (!exam.course_id && courses[0]) setExam(x => ({ ...x, course_id: courses[0].id })) }, [courses, exam.course_id])

  async function addExam(e: FormEvent) {
    e.preventDefault(); setBusy(true)
    try { await api('/admin/exams', { method: 'POST', body: JSON.stringify(exam) }); notify(`${exam.name} added for ${code(exam.course_id)}.`) }
    catch (e) { fail((e as Error).message) } finally { setBusy(false) }
  }
  async function runNow() {
    setBusy(true)
    try {
      const run = await api<MatchRun | null>(`/admin/courses/${exam.course_id}/match`, { method: 'POST' })
      notify(run ? `Placed ${run.assigned} of ${run.students} students in ${run.groups_created} groups.` : 'Not enough waiting students for a new round; open seats were filled where possible.')
      await load(); onChanged()
    } catch (e) { fail((e as Error).message) } finally { setBusy(false) }
  }
  return <section className="container admin">
    <div className="section-heading"><div><div className="section-kicker">ADMIN</div><h2>Matching control</h2></div></div>
    <form className="admin-form" onSubmit={addExam}>
      <select aria-label="Course" value={exam.course_id || ''} onChange={e => setExam({ ...exam, course_id: Number(e.target.value) })}>{courses.map(c => <option key={c.id} value={c.id}>{c.code}</option>)}</select>
      <input aria-label="Exam name" required value={exam.name} onChange={e => setExam({ ...exam, name: e.target.value })}/>
      <input aria-label="Exam date" type="date" required value={exam.exam_date} onChange={e => setExam({ ...exam, exam_date: e.target.value })}/>
      <button className="btn secondary" disabled={busy}>Add exam</button>
      <button type="button" className="btn primary" disabled={busy} onClick={runNow}><Play size={15}/> Run matching now</button>
    </form>
    {runs.length > 0 && <div className="table-wrap"><table className="runs"><thead><tr><th>When</th><th>Course</th><th>Trigger</th><th>Placed</th><th>Groups</th><th>Greedy</th><th>Local search</th><th>ILP</th><th>Shared hrs (greedy→ILP)</th><th>ms</th></tr></thead>
      <tbody>{runs.map(r => <tr key={r.id}><td>{new Date(r.created_at).toLocaleString()}</td><td>{code(r.course_id)}</td><td>{r.trigger}</td><td>{r.assigned}/{r.students}</td><td>{r.groups_created}</td><td>{r.greedy_quality.toFixed(3)}</td><td>{r.local_search_quality.toFixed(3)}</td><td>{r.ilp_quality.toFixed(3)}</td><td>{r.greedy_overlap_hours.toFixed(1)}→{r.ilp_overlap_hours.toFixed(1)}</td><td>{r.runtime_ms}</td></tr>)}</tbody></table></div>}
  </section>
}
