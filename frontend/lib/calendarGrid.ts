import type { Appointment, CalendarEntry, EventCard } from '@/lib/types'

export interface GridItem {
  id: string
  kind: 'appointment' | 'event' | 'recommendation'
  title: string
  day: string                         // YYYY-MM-DD (local)
  startMinutes: number | null         // minutes from midnight on `day`
  endMinutes: number | null           // null => end of day / open
  raw: Appointment | CalendarEntry
}

export interface LaidOutItem extends GridItem {
  column: number
  columnCount: number
}

/** Returns the Monday-to-Sunday week that contains `d`, anchored to local midnight. */
export function getWeekRange(d: Date): { start: Date; end: Date } {
  const start = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  // JS: Sunday=0..Saturday=6. Shift so Monday=0..Sunday=6.
  const dayMon0 = (start.getDay() + 6) % 7
  start.setDate(start.getDate() - dayMon0)
  const end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 7)
  return { start, end }
}

/** Formats a Date as YYYY-MM-DD using local time components. */
function toLocalDayKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Returns the number of minutes elapsed since local midnight for a given Date. */
function minutesFromMidnight(d: Date): number {
  return d.getHours() * 60 + d.getMinutes()
}

type GridInput =
  | { kind: 'appointment'; raw: Appointment }
  | { kind: 'event'; raw: CalendarEntry }

/** Converts an Appointment or CalendarEntry into a normalised GridItem. */
export function toGridItem(input: GridInput): GridItem {
  if (input.kind === 'appointment') {
    const a = input.raw
    return {
      id: a.id, kind: 'appointment', title: a.title, day: a.day,
      startMinutes: a.start_at ? minutesFromMidnight(new Date(a.start_at)) : null,
      endMinutes: a.end_at ? minutesFromMidnight(new Date(a.end_at)) : null,
      raw: a,
    }
  }
  const e: EventCard = input.raw.event
  const start = new Date(e.start_datetime)
  const end = e.end_datetime ? new Date(e.end_datetime) : null
  const kind: GridItem['kind'] = input.raw.kind === 'recommendation' ? 'recommendation' : 'event'
  return {
    id: e.id, kind, title: e.title, day: toLocalDayKey(start),
    startMinutes: minutesFromMidnight(start),
    endMinutes: end ? minutesFromMidnight(end) : null,
    raw: input.raw,
  }
}

/** Returns the effective end minute, treating null (open-ended) as end-of-day. */
function effectiveEnd(it: GridItem): number {
  return it.endMinutes ?? 24 * 60
}

/**
 * Assigns column layout positions to timed items in a single day column.
 * All-day items (startMinutes === null) are excluded from the result.
 * Overlapping items within the same overlap group are spread across columns.
 */
export function layoutDayColumn(items: GridItem[]): LaidOutItem[] {
  // Only timed items participate in overlap layout.
  const timed = items.filter(i => i.startMinutes !== null)
  timed.sort((a, b) => {
    const s = (a.startMinutes! - b.startMinutes!)
    if (s !== 0) return s
    // Longer events first within the same start time.
    return effectiveEnd(b) - effectiveEnd(a)
  })

  const out: LaidOutItem[] = []
  let i = 0
  while (i < timed.length) {
    // Build a group of mutually overlapping items by extending the group end.
    const group: GridItem[] = [timed[i]]
    let groupEnd = effectiveEnd(timed[i])
    let j = i + 1
    while (j < timed.length && timed[j].startMinutes! < groupEnd) {
      group.push(timed[j])
      groupEnd = Math.max(groupEnd, effectiveEnd(timed[j]))
      j++
    }

    // Greedy column assignment within the group.
    const columnEnds: number[] = []
    const localAssignments: { item: GridItem; column: number }[] = []
    for (const it of group) {
      let placed = false
      for (let c = 0; c < columnEnds.length; c++) {
        if (columnEnds[c] <= it.startMinutes!) {
          columnEnds[c] = effectiveEnd(it)
          localAssignments.push({ item: it, column: c })
          placed = true
          break
        }
      }
      if (!placed) {
        columnEnds.push(effectiveEnd(it))
        localAssignments.push({ item: it, column: columnEnds.length - 1 })
      }
    }

    const groupColumnCount = columnEnds.length
    for (const { item, column } of localAssignments) {
      out.push({ ...item, column, columnCount: groupColumnCount })
    }
    i = j
  }
  return out
}
