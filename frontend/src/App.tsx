import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { BookOpen, Users, Search, Plus, LogOut, ArrowRight, GraduationCap, X, Trash2, Pencil, UserRound, ChevronLeft, ChevronRight, Sparkles, CalendarCheck, Clock, RefreshCw } from 'lucide-react'
import { api, ApiError, describeSlots, type SignupConfig, type User, type Course, type Group, type GroupInput, type GroupPage } from './lib/api'
import MatchPanel from './components/MatchPanel'
import AdminPanel from './components/AdminPanel'

type AuthMode = 'login' | 'register'
type Tab = 'match' | 'discover' | 'mine' | 'admin'
const emptyGroup: GroupInput = { course_id: 0, title: '', description: '', max_members: 8 }
function readableDate(date: string) { return new Date(date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) }
const todayISO = () => new Date().toLocaleDateString('en-CA')

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [authOpen, setAuthOpen] = useState(false)
  const [auth, setAuth] = useState({ name: '', email: '', password: '' })
  const [courses, setCourses] = useState<Course[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [mine, setMine] = useState<Group[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [query, setQuery] = useState('')
  const [courseId, setCourseId] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<Group | null>(null)
  const [draft, setDraft] = useState<GroupInput>(emptyGroup)
  const [selected, setSelected] = useState<Group | null>(null)
  const [members, setMembers] = useState<User[]>([])
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

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page: String(page), page_size: '9' })
      if (query) params.set('q', query)
      if (courseId) params.set('course_id', courseId)
      const data = await api<GroupPage>(`/groups?${params}`)
      setGroups(data.items); setTotal(data.total)
      if (user) setMine(await api<Group[]>('/groups/mine'))
    } catch (e) { setError((e as Error).message) }
    finally { setLoading(false) }
  }, [page, query, courseId, user])

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
  function openEditor(group?: Group) {
    if (!user) { openAuth('login'); return }
    setEditing(group || null)
    setDraft(group ? { course_id: group.course_id, title: group.title, description: group.description, max_members: group.max_members } : { ...emptyGroup, course_id: courses[0]?.id || 0 })
    setEditorOpen(true); setError('')
  }
  async function saveGroup(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      if (editing) await api(`/groups/${editing.id}`, { method: 'PATCH', body: JSON.stringify({ title: draft.title, description: draft.description, max_members: draft.max_members }) })
      else await api('/groups', { method: 'POST', body: JSON.stringify(draft) })
      setEditorOpen(false); setNotice(editing ? 'Group updated.' : 'Your group has been created!'); await refresh()
      if (selected?.id === editing?.id) setSelected(null)
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  async function deleteGroup(group: Group) {
    if (!window.confirm(`Delete “${group.title}”? This cannot be undone.`)) return
    setBusy(true)
    try { await api(`/groups/${group.id}`, { method: 'DELETE' }); setSelected(null); setNotice('Group deleted.'); await refresh() }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  async function reloadSelected(id: number) {
    const [g, m] = await Promise.all([api<Group>(`/groups/${id}`), api<User[]>(`/groups/${id}/members`)])
    setSelected(g); setMembers(m)
  }
  async function act(group: Group, path: string, method: 'POST' | 'DELETE', message: string, body?: unknown) {
    if (!user) { openAuth('login'); return }
    setBusy(true); setError('')
    try {
      await api(`/groups/${group.id}/${path}`, { method, body: body ? JSON.stringify(body) : undefined })
      setNotice(message); bump(); await reloadSelected(group.id)
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  async function openGroup(group: Group | number) {
    const id = typeof group === 'number' ? group : group.id
    if (typeof group !== 'number') setSelected(group)
    setMembers([]); setMetOn(todayISO())
    try { await reloadSelected(id) } catch (e) { setError((e as Error).message) }
  }

  const visible = tab === 'mine' ? mine : groups
  const isMember = selected?.viewer_status === 'member'
  const full = selected ? selected.member_count >= selected.max_members : false
  const showGroups = tab === 'discover' || tab === 'mine'

  return <div className="app">
    <header className="topbar"><div className="container nav"><a href="/" className="brand" onClick={e => { e.preventDefault(); setTab('match'); setPage(1); setQuery(''); setCourseId('') }}><span className="brand-icon"><GraduationCap size={23}/></span> Campus<span>Connect</span></a>
      <nav>{([['match', 'Get matched'], ['discover', 'Explore groups'], ...(user ? [['mine', 'My groups']] : []), ...(user?.is_admin ? [['admin', 'Admin']] : [])] as [Tab, string][]).map(([t, label]) => <button key={t} className={tab === t ? 'nav-link active' : 'nav-link'} onClick={() => setTab(t)}>{label}</button>)}</nav>
      <div className="nav-actions">{user ? <><span className="hello"><UserRound size={16}/> {user.name}</span><button className="btn ghost" onClick={logout}><LogOut size={16}/> Sign out</button></> : <><button className="btn ghost" onClick={() => openAuth('login')}>Log in</button><button className="btn primary" onClick={needAuth}>Get started <ArrowRight size={16}/></button></>}</div></div></header>
    <main><section className="hero"><div className="container hero-inner"><div className="hero-content"><div className="eyebrow"><Sparkles size={14}/> For Penn students who don’t know anyone in class yet</div><h1>Don’t know anyone<br/><em>in your class?</em></h1><p>GroupMe works when you already have friends in the course. CampusConnect matches you with classmates who are free when you are, want to study the same way, and are preparing for the same exam.</p><div className="hero-buttons"><button className="btn white" onClick={() => { setTab('match'); document.getElementById('content')?.scrollIntoView({ behavior: 'smooth' }) }}>Get matched <ArrowRight size={17}/></button><button className="btn outline-white" onClick={() => { setTab('discover'); document.getElementById('content')?.scrollIntoView({ behavior: 'smooth' }) }}>Browse open groups</button></div></div><div className="hero-art"><div className="floating-card card-one"><span className="avatar purple">S</span><div><strong>Matched in CIS 1210</strong><small>Everyone free: Tue 18:00–20:00</small></div><span className="status-dot"/></div><div className="orbit"><BookOpen size={66} strokeWidth={1.3}/><span className="orbit-bubble bubble-one"><Users size={22}/></span><span className="orbit-bubble bubble-two"><GraduationCap size={24}/></span></div><div className="floating-card card-two"><span className="avatars"><i>A</i><i>M</i><i>J</i></span><div><strong>Midterm prep · 4 people</strong><small>Same goal, same pace</small></div></div></div></div></section>
    <section className="stats container"><div><strong>{total}</strong><span>Open groups to join</span></div><div><strong>{courses.length}</strong><span>Courses with matching</span></div><div><strong>{mine.length}</strong><span>{user ? 'Your groups' : 'Sign in to get matched'}</span></div></section>
    <div id="content">
    {(notice || error) && <div className="container">{notice && <div className="alert success" role="status">{notice}<button aria-label="Dismiss notice" onClick={() => setNotice('')}><X size={16}/></button></div>}{error && !authOpen && <div className="alert danger" role="alert">{error}<button aria-label="Dismiss error" onClick={() => setError('')}><X size={16}/></button></div>}</div>}
    {tab === 'match' && <MatchPanel user={user} courses={courses} onNeedAuth={needAuth} onOpenGroup={openGroup} onChanged={bump} notify={notify} fail={fail}/>}
    {tab === 'admin' && user?.is_admin && <AdminPanel courses={courses} notify={notify} fail={fail} onChanged={bump}/>}
    {showGroups && <section id="groups" className="container discovery"><div className="section-heading"><div><div className="section-kicker">{tab === 'mine' ? 'YOUR GROUPS' : 'OPEN GROUPS'}</div><h2>{tab === 'mine' ? 'Your study groups' : 'Join an open study group'}</h2><p>{tab === 'mine' ? 'Matched groups and groups you joined or are waitlisted for.' : 'Groups created by students. Full groups have a first-come, first-served waitlist.'}</p></div><button className="btn primary create" onClick={() => openEditor()}><Plus size={18}/> Create group</button></div>
    {tab === 'discover' && <div className="filters"><label className="search"><Search size={19}/><input aria-label="Search groups" placeholder="Search groups, topics, or course codes..." value={query} onChange={e => { setQuery(e.target.value); setPage(1) }}/></label><select aria-label="Filter by course" value={courseId} onChange={e => { setCourseId(e.target.value); setPage(1) }}><option value="">All courses</option>{courses.map(c => <option key={c.id} value={c.id}>{c.code} — {c.title}</option>)}</select></div>}
    {loading ? <div className="empty">Loading study groups...</div> : visible.length ? <div className="group-grid">{visible.map((g, i) => <article className="group-card" key={g.id}><div className="card-top"><span className={`course-pill color-${i % 4}`}>{g.course_code}</span>{g.kind === 'matched' ? <span className="match-tag"><Sparkles size={12}/> Matched</span> : <span className="date">{readableDate(g.created_at)}</span>}</div><div className="card-icon"><BookOpen size={25}/></div><h3>{g.title}</h3><p>{g.description || 'Connect with classmates and learn together.'}</p><div className="card-bottom"><span className="members"><Users size={16}/> {g.member_count} / {g.max_members}{g.viewer_status === 'waitlisted' ? ` · waitlist #${g.viewer_waitlist_position}` : g.waitlist_count ? ` · ${g.waitlist_count} waiting` : ''}</span><button className="view-link" onClick={() => openGroup(g)}>View group <ArrowRight size={16}/></button></div></article>)}</div> : <div className="empty"><BookOpen size={32}/><h3>{tab === 'mine' ? 'No groups yet' : 'No groups found'}</h3><p>{tab === 'mine' ? 'Get matched or join an open group to see it here.' : 'Be the first to create a study group for this search, or get matched instead.'}</p><button className="btn primary" onClick={() => setTab('match')}>Get matched</button></div>}
    {tab === 'discover' && total > 9 && <div className="pagination"><button disabled={page <= 1} onClick={() => setPage(p => p - 1)}><ChevronLeft size={18}/> Previous</button><span>Page {page} of {Math.ceil(total / 9)}</span><button disabled={page * 9 >= total} onClick={() => setPage(p => p + 1)}>Next <ChevronRight size={18}/></button></div>}</section>}
    </div></main>
    <footer><div className="container footer-inner"><span className="brand"><span className="brand-icon"><GraduationCap size={18}/></span> Campus<span>Connect</span></span><span className="affiliation">Made for Penn students · Not affiliated with the University of Pennsylvania</span><span>© {new Date().getFullYear()} CampusConnect</span></div></footer>
    {authOpen && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) setAuthOpen(false) }}><div className="modal" role="dialog" aria-modal="true" aria-label="Account"><button className="close" aria-label="Close" onClick={() => setAuthOpen(false)}><X/></button><div className="modal-mark"><GraduationCap/></div><h2>{authMode === 'login' ? 'Welcome back' : 'Join CampusConnect'}</h2><p>{authMode === 'login' ? 'Sign in to connect with your classmates.' : pennOnly ? 'Sign up with your Penn email to get matched with classmates.' : 'Create an account to get matched with classmates.'}</p>{authInfo && <div className="alert info" role="status">{authInfo}{pendingEmail && authInfo.includes('Verify') && <button type="button" className="link-btn" disabled={busy} onClick={resendVerification}>Resend link</button>}</div>}{error && <div className="alert danger" role="alert">{error}</div>}<form onSubmit={submitAuth}>{authMode === 'register' && <label>Full name<input required minLength={1} maxLength={120} value={auth.name} onChange={e => setAuth({ ...auth, name: e.target.value })} placeholder="Your name"/></label>}<label>{emailLabel}<input required type="email" value={auth.email} onChange={e => setAuth({ ...auth, email: e.target.value })} placeholder={emailPlaceholder} autoComplete="email"/>{authMode === 'register' && (signup.allowed_email_domains.length > 0 || signup.require_email_verification) && <small className="field-hint">{pennOnly ? '@upenn.edu or a school address like @engineering.upenn.edu.' : signup.allowed_email_domains.length ? `Use an address ending in ${signup.allowed_email_domains.map(d => '@' + d).join(' or ')}.` : ''}{signup.require_email_verification ? ' We’ll email you a link to confirm it.' : ''}</small>}</label><label>Password<input required type="password" minLength={8} value={auth.password} onChange={e => setAuth({ ...auth, password: e.target.value })} placeholder="At least 8 characters"/></label><button className="btn primary full" disabled={busy}>{busy ? 'Please wait...' : authMode === 'login' ? 'Sign in' : 'Create account'} <ArrowRight size={16}/></button></form><div className="switch">{authMode === 'login' ? "Don't have an account?" : 'Already have an account?'} <button onClick={() => openAuth(authMode === 'login' ? 'register' : 'login')}>{authMode === 'login' ? 'Sign up' : 'Sign in'}</button></div></div></div>}
    {editorOpen && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) setEditorOpen(false) }}><div className="modal" role="dialog" aria-modal="true" aria-label="Study group editor"><button className="close" aria-label="Close" onClick={() => setEditorOpen(false)}><X/></button><div className="modal-mark"><Plus/></div><h2>{editing ? 'Edit study group' : 'Create a study group'}</h2><p>Bring your classmates together to learn and grow.</p><form onSubmit={saveGroup}><label>Course<select required disabled={!!editing} value={draft.course_id || ''} onChange={e => setDraft({ ...draft, course_id: Number(e.target.value) })}><option value="" disabled>Select a course</option>{courses.map(c => <option key={c.id} value={c.id}>{c.code} — {c.title}</option>)}</select></label><label>Group name<input required minLength={3} maxLength={120} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} placeholder="e.g. Algorithms midterm prep"/></label><label>Description<textarea maxLength={3000} rows={4} value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} placeholder="What will your group focus on?"/></label><label>Maximum members<input type="number" required min={2} max={100} value={draft.max_members} onChange={e => setDraft({ ...draft, max_members: Number(e.target.value) })}/></label><button disabled={busy} className="btn primary full">{busy ? 'Saving...' : editing ? 'Save changes' : 'Create group'} <ArrowRight size={16}/></button></form></div></div>}
    {selected && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) setSelected(null) }}><div className="modal" role="dialog" aria-modal="true" aria-label="Group details"><button className="close" aria-label="Close" onClick={() => setSelected(null)}><X/></button>
      <span className="course-pill color-0">{selected.course_code}</span>{selected.kind === 'matched' && <span className="match-tag inline"><Sparkles size={12}/> Matched group</span>}
      <h2 className="detail-title">{selected.title}</h2>
      {selected.kind === 'matched' ? <div className="shared-time"><Clock size={16}/><div><strong>Everyone is free</strong><span>{describeSlots(selected.common_slots) || 'No shared time right now'}</span></div></div> : <p>{selected.description || 'Connect with classmates and learn together.'}</p>}
      <div className="detail-info"><Users size={18}/> {selected.member_count} of {selected.max_members} members{selected.waitlist_count > 0 && ` · ${selected.waitlist_count} on waitlist`}{selected.kind === 'matched' && selected.match_quality !== null && ` · match quality ${Math.round(selected.match_quality * 100)}%`}</div>
      <h4>Members</h4><div className="member-list">{members.map(m => <div key={m.id}><span className="member-avatar">{m.name[0]?.toUpperCase()}</span>{m.name}{m.id === selected.owner_id && <span className="owner-tag">Organizer</span>}</div>)}</div>
      {isMember && <div className="checkin"><div><CalendarCheck size={18}/><strong>Did your group meet?</strong><small>{selected.meetings_reported ? `${selected.meetings_reported} meeting${selected.meetings_reported === 1 ? '' : 's'} reported` : 'Help us learn which groups work.'}</small></div><div className="checkin-row"><input aria-label="Meeting date" type="date" max={todayISO()} value={metOn} onChange={e => setMetOn(e.target.value)}/><button className="btn secondary" disabled={busy} onClick={() => act(selected, 'checkins', 'POST', 'Thanks! Meeting recorded.', { met: true, met_on: metOn })}>Yes, we met</button><button className="btn ghost" disabled={busy} onClick={() => act(selected, 'checkins', 'POST', 'Thanks for letting us know.', { met: false, met_on: metOn })}>No</button></div></div>}
      {user && user.id === selected.owner_id ? <div className="detail-actions"><button className="btn secondary" onClick={() => { const g = selected; setSelected(null); openEditor(g) }}><Pencil size={16}/> Edit</button><button className="btn danger-btn" disabled={busy} onClick={() => deleteGroup(selected)}><Trash2 size={16}/> Delete</button></div>
        : selected.kind === 'matched' ? (isMember ? <div className="detail-actions"><button className="btn secondary" disabled={busy} onClick={() => act(selected, 'members/me?rematch=true', 'DELETE', 'You left the group. We’ll match you with a different one.')}><RefreshCw size={16}/> Find me a new group</button><button className="btn danger-btn" disabled={busy} onClick={() => act(selected, 'members/me', 'DELETE', 'You left the group.')}>Leave</button></div> : <button className="btn primary full" onClick={() => { setSelected(null); setTab('match') }}>Get matched for {selected.course_code} <ArrowRight size={16}/></button>)
        : isMember ? <button className="btn primary full" disabled={busy} onClick={() => act(selected, 'members/me', 'DELETE', 'You left the group.')}>Leave group</button>
        : selected.viewer_status === 'waitlisted' ? <button className="btn secondary full" disabled={busy} onClick={() => act(selected, 'waitlist/me', 'DELETE', 'You left the waitlist.')}>You’re #{selected.viewer_waitlist_position} on the waitlist · Leave waitlist</button>
        : full ? <button className="btn primary full" disabled={busy} onClick={() => act(selected, 'waitlist', 'POST', 'You’re on the waitlist. You’ll be added automatically when a seat opens.')}>Group is full · Join waitlist <ArrowRight size={16}/></button>
        : <button className="btn primary full" disabled={busy} onClick={() => act(selected, 'join', 'POST', 'You joined the group!')}>Join this group <ArrowRight size={16}/></button>}
    </div></div>}
  </div>
}
