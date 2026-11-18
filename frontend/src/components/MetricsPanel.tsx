import { useEffect, useState } from 'react'
import { api, type Metrics } from '../lib/api'

const fmt = (v: number | null | undefined, suffix = '') => v === null || v === undefined ? '—' : `${v}${suffix}`

/** Outcome metrics: did matched groups actually meet, did students come back, how fast were they placed. */
export default function MetricsPanel({ refreshKey }: { refreshKey: number }) {
  const [m, setM] = useState<Metrics | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { api<Metrics>('/metrics').then(setM).catch(e => setError(e.message)) }, [refreshKey])
  if (error) return <section className="container impact"><div className="alert danger">{error}</div></section>
  if (!m) return <section className="container impact"><div className="empty">Loading metrics…</div></section>
  const a = m.algorithm
  const tiles: [string, string, string][] = [
    [fmt(m.pct_groups_met_at_least_twice, '%'), 'of matched groups met at least twice', `${m.groups_eligible_for_meeting_stats} groups at least a week old`],
    [fmt(m.pct_groups_met_at_least_once, '%'), 'met at least once', 'from members’ “did your group meet?” check-ins'],
    [fmt(m.retention_pct, '%'), 'of students came back', `${m.returning_students} used matching again for another exam or course`],
    [fmt(m.time_to_match_hours_median, 'h'), 'median time to match', `p90 ${fmt(m.time_to_match_hours_p90, 'h')}`],
  ]
  return <section id="impact" className="container impact">
    <div className="section-heading"><div><div className="section-kicker">OUTCOMES, NOT SIGNUPS</div><h2>Does it work?</h2><p>{m.students_requested_match} students asked to be matched across {m.courses_with_requests} course{m.courses_with_requests === 1 ? '' : 's'}; {m.matched_groups} groups formed; {m.students_waiting} waiting now.</p></div></div>
    <div className="metric-grid">{tiles.map(([v, label, sub]) => <div className="metric" key={label}><strong>{v}</strong><span>{label}</span><small>{sub}</small></div>)}</div>
    <div className="algo-card">
      <h3>Matching algorithm</h3>
      <p>Each round scores possible groups on shared free time, study goal, pace and size preference, then picks the best set of groups with an integer linear program (OR-Tools CP-SAT). A greedy baseline runs on the same students every round for comparison.</p>
      {a.runs ? <div className="algo-stats">
        <div><span>Avg match quality</span><b>{fmt(a.greedy_avg_quality)}</b> greedy → <b>{fmt(a.ilp_avg_quality)}</b> ILP <em>{a.ilp_quality_gain_pct !== null ? `${a.ilp_quality_gain_pct > 0 ? '+' : ''}${a.ilp_quality_gain_pct}%` : ''}</em></div>
        <div><span>Shared hours / week</span><b>{fmt(a.greedy_avg_common_hours)}</b> greedy → <b>{fmt(a.ilp_avg_common_hours)}</b> ILP <em>{a.ilp_overlap_gain_pct !== null ? `${a.ilp_overlap_gain_pct > 0 ? '+' : ''}${a.ilp_overlap_gain_pct}%` : ''}</em></div>
        <div><span>Matching rounds</span><b>{a.runs}</b></div>
      </div> : <p className="muted">No matching rounds have run yet.</p>}
    </div>
  </section>
}
