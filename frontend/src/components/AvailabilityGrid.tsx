import { useEffect, useRef } from 'react'
import { DAYS, FIRST_HOUR, HOURS_PER_DAY, slotOf } from '../lib/api'

type Props = { value: number[]; onChange: (slots: number[]) => void }

/** Weekly free-time picker. Click or drag to paint hours; dragging from a selected cell erases. */
export default function AvailabilityGrid({ value, onChange }: Props) {
  const painting = useRef<null | boolean>(null)
  const selected = new Set(value)
  useEffect(() => {
    const stop = () => { painting.current = null }
    window.addEventListener('pointerup', stop)
    return () => window.removeEventListener('pointerup', stop)
  }, [])
  function set(slot: number, on: boolean) {
    const next = new Set(value)
    if (on) next.add(slot); else next.delete(slot)
    if (next.size !== selected.size) onChange([...next].sort((a, b) => a - b))
  }
  const hours = Array.from({ length: HOURS_PER_DAY }, (_, i) => FIRST_HOUR + i)
  return <div className="avail" role="grid" aria-label="Weekly availability">
    <div className="avail-row avail-head" role="row"><span/>{DAYS.map(d => <span key={d} role="columnheader">{d}</span>)}</div>
    {hours.map(h => <div className="avail-row" role="row" key={h}>
      <span className="avail-hour">{h <= 12 ? h : h - 12}{h < 12 ? 'a' : 'p'}</span>
      {DAYS.map((d, di) => {
        const slot = slotOf(di, h)
        const on = selected.has(slot)
        return <button type="button" key={d} role="gridcell" aria-selected={on} aria-label={`${d} ${h}:00`}
          className={on ? 'cell on' : 'cell'}
          onPointerDown={e => { e.preventDefault(); painting.current = !on; set(slot, !on) }}
          onPointerEnter={() => { if (painting.current !== null) set(slot, painting.current) }}
          onKeyDown={e => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); set(slot, !on) } }} />
      })}
    </div>)}
    <small className="avail-count">{value.length} free hour{value.length === 1 ? '' : 's'} per week selected</small>
  </div>
}
