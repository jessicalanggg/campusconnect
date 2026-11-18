import { useEffect, useRef } from 'react'
import { DAYS, FIRST_HOUR, HOURS_PER_DAY, slotOf } from '../lib/api'

type Props = {
  value: number[]; onChange: (slots: number[]) => void
  /** How many classmates are free in each slot (counts only); shades the grid when present. */
  heat?: number[]; heatStudents?: number
}

const range = (a: number, b: number) => Array.from({ length: b - a }, (_, i) => a + i)
const PRESETS: { label: string; slots: number[] }[] = [
  { label: 'Weekday evenings', slots: range(0, 5).flatMap(d => [18, 19, 20].map(h => slotOf(d, h))) },
  { label: 'Weekday afternoons', slots: range(0, 5).flatMap(d => [13, 14, 15, 16].map(h => slotOf(d, h))) },
  { label: 'Weekends', slots: [5, 6].flatMap(d => range(12, 18).map(h => slotOf(d, h))) },
]

/** Weekly free-time picker. Click or drag to paint hours; dragging from a selected cell erases. */
export default function AvailabilityGrid({ value, onChange, heat, heatStudents = 0 }: Props) {
  const painting = useRef<null | boolean>(null)
  const selected = new Set(value)
  const maxHeat = heat?.length ? Math.max(1, ...heat) : 0
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
  function addPreset(slots: number[]) { onChange([...new Set([...value, ...slots])].sort((a, b) => a - b)) }
  const hours = Array.from({ length: HOURS_PER_DAY }, (_, i) => FIRST_HOUR + i)
  return <div>
    <div className="presets" role="group" aria-label="Quick add">
      {PRESETS.map(p => <button type="button" key={p.label} className="preset" onClick={() => addPreset(p.slots)}>+ {p.label}</button>)}
      {value.length > 0 && <button type="button" className="preset clear" onClick={() => onChange([])}>Clear</button>}
    </div>
    <div className="avail" role="grid" aria-label="Weekly availability">
      <div className="avail-row avail-head" role="row"><span/>{DAYS.map(d => <span key={d} role="columnheader">{d}</span>)}</div>
      {hours.map(h => <div className="avail-row" role="row" key={h}>
        <span className="avail-hour">{h <= 12 ? h : h - 12}{h < 12 ? 'a' : 'p'}</span>
        {DAYS.map((d, di) => {
          const slot = slotOf(di, h)
          const on = selected.has(slot)
          const n = heat?.[slot] ?? 0
          const label = `${d} ${h}:00${maxHeat ? `, ${n} classmate${n === 1 ? '' : 's'} free` : ''}`
          return <button type="button" key={d} role="gridcell" aria-selected={on} aria-label={label} title={maxHeat ? `${n} classmate${n === 1 ? '' : 's'} free` : undefined}
            className={on ? 'cell on' : 'cell'}
            style={!on && maxHeat && n ? { background: `rgba(72, 197, 154, ${0.15 + 0.6 * (n / maxHeat)})` } : undefined}
            onPointerDown={e => { e.preventDefault(); painting.current = !on; set(slot, !on) }}
            onPointerEnter={() => { if (painting.current !== null) set(slot, painting.current) }}
            onKeyDown={e => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); set(slot, !on) } }} />
        })}
      </div>)}
      <small className="avail-count">{value.length} free hour{value.length === 1 ? '' : 's'} per week selected</small>
      {maxHeat > 0 && <small className="heat-legend"><span className="heat-swatch"/>Green shows when the {heatStudents} classmate{heatStudents === 1 ? '' : 's'} waiting in this course are free. Darker means more people.</small>}
    </div>
  </div>
}
