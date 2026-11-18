import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { BookOpen, Users, LogOut, ArrowRight, GraduationCap, X, UserRound, Sparkles, CalendarCheck, CalendarPlus, Clock, Mail, MessageCircle, RefreshCw } from 'lucide-react'
import { api, ApiError, describeSlots, type SignupConfig, type User, type Course, type Group, type Member } from './lib/api'
import { describeBlock, downloadFile, firstMeeting, groupCalendar, groupMailto } from './lib/meet'
import MatchPanel from './components/MatchPanel'
import AdminPanel from './components/AdminPanel'

type AuthMode = 'login' | 'register'
type Tab = 'match' | 'mine' | 'admin'
const todayISO = () => new Date().toLocaleDateString('en-CA')

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [authOpen, setAuthOpen] = useState(false)
  const [auth, setAuth] = useState({ name: '', email: '', password: '' })
  const [courses, setCourses] = useState<Course[]>([])
  const [mine, setMine] = useState<Group[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState<Group | null>(null)
  const [members, setMembers] = useState<Member[]>([])
  const [contact, setContact] = useState('')
  const [tab, setTab] = useState<Tab>('match')
  const [metOn, setMetOn] = useState(todayISO())
  const [version, setVersion] = useState(0)
  // Account flow messages shown inside the sign-in dialog
  const [pendingEmail, setPendingEmail] = useState('')  // registered or unverified address awaiting verification
  const [authInfo, setAuthInfo] = useState('')
  const [signup, setSignup] = useState<SignupConfig>({ allowed_email_domains: [], require_email_verification: false })
  const pennOnly = signup.allowed_email_domains.length === 1 && signup.allowed_email_domains[0] === 'upenn.edu'
  const emailLabel = pennOnly ? 'Penn email' : signup.allowed_email_domains.length ? 'School email' : 'Email'
  const emailPlaceholder = pennOnly ? 'you@upenn.edu' : signup.allowed_email_domains.length ? `you@${signup.allowed_email_domains[0]}` : 'you@email.com'

  const notify = useCallback((msg: string) => { setNotice(msg); setError('') }, [])
  const fail = useCallback((msg: string) => setError(msg), [])
  const bump = useCallback(() => setVersion(v => v + 1), [])

  // Every group is formed by the matcher; a student only ever sees the groups they're in.
  const refresh = useCallback(async () => {
    if (!user) { setMine([]); return }
    setLoading(true)
    try { setMine(await api<Group[]>('/groups/mine')) }
    catch (e) { setError((e as Error).message) }
    finally { setLoading(false) }
  }, [user])

  useEffect(() => { api<Course[]>('/courses').then(setCourses).catch(e => setError(e.message)) }, [])
  useEffect(() => { api<SignupConfig>('/config').then(c => { if (c && Array.isArray(c.allowed_email_domains)) setSignup(c) }).catch(() => undefined) }, [])
  useEffect(() => { refresh() }, [refresh, version])
  // The session is an HttpOnly cookie, so ask the server who we are.
  useEffect(() => { api<User>('/auth/me').then(setUser).catch(() => setUser(null)) }, [])
  // Verification links land on /?verify=<token>
  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get('verify')
    if (!token) return
    window.history.replaceState(null, '', window.location.pathname)
    api<User>('/auth/verify', { method: 'POST', body: JSON.stringify({ token }) })
      .then(u => { setAuth(a => ({ ...a, email: u.email })); setAuthMode('login'); setAuthInfo('Your email is verified. Sign in to get matched.'); setAuthOpen(true) })
      .catch(e => setError((e as Error).message))
  }, [])

  async function submitAuth(e: FormEvent) {
    e.preventDefault(); setError(''); setAuthInfo(''); setBusy(true)
    try {
      if (authMode === 'register') {
        const created = await api<{ verification_required: boolean }>('/auth/register', { method: 'POST', body: JSON.stringify(auth) })
        if (created.verification_required) {
          setPendingEmail(auth.email); setAuthMode('login'); setAuth(a => ({ ...a, password: '' }))
          setAuthInfo(`We sent a verification link to ${auth.email}. Click it, then sign in here.`)
          return
        }
        // No verification step: sign the new student straight in.
      }
      await api('/auth/login', { method: 'POST', body: JSON.stringify({ email: auth.email, password: auth.password }) })
      setUser(await api<User>('/auth/me')); setAuthOpen(false); setPendingEmail(''); setAuth({ name: '', email: '', password: '' }); setNotice('Welcome to CampusConnect!')
    } catch (e) {
      if (e instanceof ApiError && e.status === 403 && authMode === 'login') { setPendingEmail(auth.email); setAuthInfo(e.message) }
      else setError((e as Error).message)
    }
    finally { setBusy(false) }
  }
  async function resendVerification() {
    setBusy(true); setError('')
    try { await api('/auth/resend-verification', { method: 'POST', body: JSON.stringify({ email: pendingEmail }) }); setAuthInfo(`A new verification link is on its way to ${pendingEmail}.`) }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  function openAuth(mode: AuthMode) { setAuthMode(mode); setAuthInfo(''); setError(''); setAuthOpen(true) }
  function needAuth() { openAuth('register') }
  async function logout() {
    await api('/auth/logout', { method: 'POST' }).catch(() => undefined)
    setUser(null); setMine([]); setTab('match'); setSelected(null); setNotice('You have signed out.')
  }
  async function reloadSelected(id: number) {
    const [g, m] = await Promise.all([api<Group>(`/groups/${id}`), api<Member[]>(`/groups/${id}/members`)])
    setSelected(g); setMembers(m)
  }
  async function act(group: Group, path: string, method: 'POST' | 'DELETE', message: string, body?: unknown) {
    if (!user) { openAuth('login'); return }
    setBusy(true); setError('')
    try {
      await api(`/groups/${group.id}/${path}`, { method, body: body ? JSON.stringify(body) : undefined })
      setNotice(message); bump()
      // Groups are private, so after leaving one there's nothing left to show.
      if (path.startsWith('members/me')) setSelected(null)
      else await reloadSelected(group.id)
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  async function saveContact() {
    setBusy(true); setError('')
    try {
      const me = await api<User>('/auth/me', { method: 'PATCH', body: JSON.stringify({ contact }) })
      setUser(me); setContact(me.contact ?? '')
      if (selected) setMembers(await api<Member[]>(`/groups/${selected.id}/members`))
      setNotice(me.contact ? 'Your group can now see how to reach you.' : 'Contact removed.')
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  async function openGroup(group: Group | number) {
    const id = typeof group === 'number' ? group : group.id
    if (typeof group !== 'number') setSelected(group)
    setMembers([]); setMetOn(todayISO()); setContact(user?.contact ?? '')
    try { await reloadSelected(id) } catch (e) { setError((e as Error).message) }
  }

  const isMember = selected?.viewer_status === 'member'
  const first = selected ? firstMeeting(selected.common_slots) : null

  return <div className="app">
    <header className="topbar"><div className="container nav"><a href="/" className="brand" onClick={e => { e.preventDefault(); setTab('match') }}><span className="brand-icon"><GraduationCap size={23}/></span> Campus<span>Connect</span></a>
      <nav>{([['match', 'Get matched'], ...(user ? [['mine', 'My groups']] : []), ...(user?.is_admin ? [['admin', 'Admin']] : [])] as [Tab, string][]).map(([t, label]) => <button key={t} className={tab === t ? 'nav-link active' : 'nav-link'} onClick={() => setTab(t)}>{label}</button>)}</nav>
      <div className="nav-actions">{user ? <><span className="hello"><UserRound size={16}/> {user.name}</span><button className="btn ghost" onClick={logout}><LogOut size={16}/> Sign out</button></> : <><button className="btn ghost" onClick={() => openAuth('login')}>Log in</button><button className="btn primary" onClick={needAuth}>Get started <ArrowRight size={16}/></button></>}</div></div></header>
    <main><section className="hero"><div className="container hero-inner"><div className="hero-content"><div className="eyebrow"><Sparkles size={14}/> For Penn students who don’t know anyone in class yet</div><h1>Don’t know anyone<br/><em>in your class?</em></h1><p>GroupMe works when you already have friends in the course. CampusConnect matches you with classmates who are free when you are, want to study the same way, and are preparing for the same exam.</p><div className="hero-buttons"><button className="btn white" onClick={() => { setTab('match'); document.getElementById('content')?.scrollIntoView({ behavior: 'smooth' }) }}>Get matched <ArrowRight size={17}/></button></div></div><div className="hero-art"><div className="floating-card card-one"><span className="avatar purple">S</span><div><strong>Matched in CIS 1210</strong><small>Everyone free: Tue 18:00–20:00</small></div><span className="status-dot"/></div><div className="orbit"><BookOpen size={66} strokeWidth={1.3}/><span className="orbit-bubble bubble-one"><Users size={22}/></span><span className="orbit-bubble bubble-two"><GraduationCap size={24}/></span></div><div className="floating-card card-two"><span className="avatars"><i>A</i><i>M</i><i>J</i></span><div><strong>Midterm prep · 4 people</strong><small>Same goal, same pace</small></div></div></div></div></section>
    <section className="stats container"><div><strong>{courses.length}</strong><span>Courses with matching</span></div><div><strong>{mine.length}</strong><span>{user ? 'Your groups' : 'Sign in to get matched'}</span></div></section>
    <div id="content">
    {(notice || error) && <div className="container">{notice && <div className="alert success" role="status">{notice}<button aria-label="Dismiss notice" onClick={() => setNotice('')}><X size={16}/></button></div>}{error && !authOpen && <div className="alert danger" role="alert">{error}<button aria-label="Dismiss error" onClick={() => setError('')}><X size={16}/></button></div>}</div>}
    {tab === 'match' && <MatchPanel user={user} courses={courses} onNeedAuth={needAuth} onOpenGroup={openGroup} onChanged={bump} notify={notify} fail={fail}/>}
    {tab === 'admin' && user?.is_admin && <AdminPanel courses={courses} notify={notify} fail={fail} onChanged={bump}/>}
    {tab === 'mine' && <section id="groups" className="container discovery"><div className="section-heading"><div><div className="section-kicker">YOUR GROUPS</div><h2>Your study groups</h2><p>Groups the matcher put you in, with everyone’s shared free time.</p></div></div>
    {loading ? <div className="empty">Loading study groups...</div> : mine.length ? <div className="group-grid">{mine.map((g, i) => <article className="group-card" key={g.id}><div className="card-top"><span className={`course-pill color-${i % 4}`}>{g.course_code}</span><span className="match-tag"><Sparkles size={12}/> Matched</span></div><div className="card-icon"><BookOpen size={25}/></div><h3>{g.title}</h3><p>{describeSlots(g.common_slots) ? `Everyone is free: ${describeSlots(g.common_slots)}` : g.description}</p><div className="card-bottom"><span className="members"><Users size={16}/> {g.member_count} / {g.max_members}</span><button className="view-link" onClick={() => openGroup(g)}>View group <ArrowRight size={16}/></button></div></article>)}</div> : <div className="empty"><BookOpen size={32}/><h3>No groups yet</h3><p>Ask to be matched for a course and your group will show up here.</p><button className="btn primary" onClick={() => setTab('match')}>Get matched</button></div>}
    </section>}
    </div></main>
    <footer><div className="container footer-inner"><span className="brand"><span className="brand-icon"><GraduationCap size={18}/></span> Campus<span>Connect</span></span><span className="affiliation">Made for Penn students · Not affiliated with the University of Pennsylvania</span><span>© {new Date().getFullYear()} CampusConnect</span></div></footer>
    {authOpen && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) setAuthOpen(false) }}><div className="modal" role="dialog" aria-modal="true" aria-label="Account"><button className="close" aria-label="Close" onClick={() => setAuthOpen(false)}><X/></button><div className="modal-mark"><GraduationCap/></div><h2>{authMode === 'login' ? 'Welcome back' : 'Join CampusConnect'}</h2><p>{authMode === 'login' ? 'Sign in to connect with your classmates.' : pennOnly ? 'Sign up with your Penn email to get matched with classmates.' : 'Create an account to get matched with classmates.'}</p>{authInfo && <div className="alert info" role="status">{authInfo}{pendingEmail && authInfo.includes('Verify') && <button type="button" className="link-btn" disabled={busy} onClick={resendVerification}>Resend link</button>}</div>}{error && <div className="alert danger" role="alert">{error}</div>}<form onSubmit={submitAuth}>{authMode === 'register' && <label>Full name<input required minLength={1} maxLength={120} value={auth.name} onChange={e => setAuth({ ...auth, name: e.target.value })} placeholder="Your name"/></label>}<label>{emailLabel}<input required type="email" value={auth.email} onChange={e => setAuth({ ...auth, email: e.target.value })} placeholder={emailPlaceholder} autoComplete="email"/>{authMode === 'register' && (signup.allowed_email_domains.length > 0 || signup.require_email_verification) && <small className="field-hint">{pennOnly ? '@upenn.edu or a school address like @engineering.upenn.edu.' : signup.allowed_email_domains.length ? `Use an address ending in ${signup.allowed_email_domains.map(d => '@' + d).join(' or ')}.` : ''}{signup.require_email_verification ? ' We’ll email you a link to confirm it.' : ''}</small>}</label><label>Password<input required type="password" minLength={8} value={auth.password} onChange={e => setAuth({ ...auth, password: e.target.value })} placeholder="At least 8 characters"/></label><button className="btn primary full" disabled={busy}>{busy ? 'Please wait...' : authMode === 'login' ? 'Sign in' : 'Create account'} <ArrowRight size={16}/></button></form><div className="switch">{authMode === 'login' ? "Don't have an account?" : 'Already have an account?'} <button onClick={() => openAuth(authMode === 'login' ? 'register' : 'login')}>{authMode === 'login' ? 'Sign up' : 'Sign in'}</button></div></div></div>}
    {selected && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) setSelected(null) }}><div className="modal" role="dialog" aria-modal="true" aria-label="Group details"><button className="close" aria-label="Close" onClick={() => setSelected(null)}><X/></button>
      <span className="course-pill color-0">{selected.course_code}</span><span className="match-tag inline"><Sparkles size={12}/> Matched group</span>
      <h2 className="detail-title">{selected.title}</h2>
      <div className="shared-time"><Clock size={16}/><div><strong>Everyone is free</strong><span>{describeSlots(selected.common_slots) || 'No shared time right now'}</span></div></div>
      <div className="detail-info"><Users size={18}/> {selected.member_count} of {selected.max_members} members{selected.match_quality !== null && ` · match quality ${Math.round(selected.match_quality * 100)}%`}</div>
      {isMember && first && <div className="first-meeting"><CalendarCheck size={16}/><div><strong>Suggested first meeting</strong><span>{first.date.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })}, {describeBlock(first.block).slice(4)}{selected.exam_name && selected.exam_date && ` · before ${selected.exam_name} on ${new Date(selected.exam_date + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`}</span></div></div>}
      {isMember && members.length > 0 && <div className="group-tools"><a className="btn primary" href={groupMailto(selected, members, user)}><Mail size={15}/> Email the group</a><button className="btn secondary" disabled={!selected.common_slots.length} onClick={() => downloadFile(`${selected.course_code.replace(/\s+/g, '-')}-study-group.ics`, groupCalendar(selected, members))}><CalendarPlus size={15}/> Add to calendar</button></div>}
      <h4>Members</h4><div className="member-list">{members.map(m => <div key={m.id}><span className="member-avatar">{m.name[0]?.toUpperCase()}</span><div className="member-info"><strong>{m.name}{m.email === user?.email && <em> (you)</em>}</strong>{isMember && <a href={`mailto:${m.email}`}>{m.email}</a>}{isMember && m.contact && <span><MessageCircle size={12}/> {m.contact}</span>}</div></div>)}</div>
      {isMember && <div className="contact-edit"><label htmlFor="contact">How should your group reach you? <small>Optional, e.g. Discord or phone. Only your group members see it.</small></label><div className="checkin-row"><input id="contact" maxLength={120} value={contact} placeholder="e.g. Discord: ava.c" onChange={e => setContact(e.target.value)}/><button className="btn secondary" disabled={busy || contact.trim() === (user?.contact ?? '')} onClick={saveContact}>Save</button></div></div>}
      {isMember && <div className="checkin"><div><CalendarCheck size={18}/><strong>Did your group meet?</strong><small>{selected.meetings_reported ? `${selected.meetings_reported} meeting${selected.meetings_reported === 1 ? '' : 's'} reported` : 'Help us learn which groups work.'}</small></div><div className="checkin-row"><input aria-label="Meeting date" type="date" max={todayISO()} value={metOn} onChange={e => setMetOn(e.target.value)}/><button className="btn secondary" disabled={busy} onClick={() => act(selected, 'checkins', 'POST', 'Thanks! Meeting recorded.', { met: true, met_on: metOn })}>Yes, we met</button><button className="btn ghost" disabled={busy} onClick={() => act(selected, 'checkins', 'POST', 'Thanks for letting us know.', { met: false, met_on: metOn })}>No</button></div></div>}
      {isMember && <div className="detail-actions"><button className="btn secondary" disabled={busy} onClick={() => act(selected, 'members/me?rematch=true', 'DELETE', 'You left the group. We’ll match you with a different one.')}><RefreshCw size={16}/> Find me a new group</button><button className="btn danger-btn" disabled={busy} onClick={() => act(selected, 'members/me', 'DELETE', 'You left the group.')}>Leave</button></div>}
    </div></div>}
  </div>
}
