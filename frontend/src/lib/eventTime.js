const TZ = 'America/Chicago'

const timeFmt = new Intl.DateTimeFormat('en-US', {
  hour: 'numeric',
  minute: '2-digit',
  timeZone: TZ,
})

const hourFmt = new Intl.DateTimeFormat('en-US', {
  hour: 'numeric',
  hour12: false,
  timeZone: TZ,
})

const ymdFmt = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  timeZone: TZ,
})

const minuteFmt = new Intl.DateTimeFormat('en-US', {
  minute: '2-digit',
  timeZone: TZ,
})

export function formatTime(iso) {
  return timeFmt.format(new Date(iso))
}

export function formatTimeRange(start, end) {
  if (!end) return formatTime(start)
  return `${formatTime(start)} – ${formatTime(end)}`
}

export function localHour(iso) {
  const h = parseInt(hourFmt.format(new Date(iso)), 10)
  return h === 24 ? 0 : h
}

function localYMD(iso) {
  return ymdFmt.format(new Date(iso))
}

function isLocalMidnight(iso) {
  const d = new Date(iso)
  return parseInt(hourFmt.format(d), 10) % 24 === 0 && parseInt(minuteFmt.format(d), 10) === 0
}

export function isAllDay(event, requestedDate) {
  if (!event.start_at) return false

  // Multi-day event that fully spans the requested day (started before, ends after).
  if (event.end_at && requestedDate) {
    const startBefore = localYMD(event.start_at) < requestedDate
    const endAfter = localYMD(event.end_at) > requestedDate
    if (startBefore && endAfter) return true
  }

  // Otherwise the canonical all-day shape: midnight → midnight, ≥ 24h.
  if (!isLocalMidnight(event.start_at)) return false
  if (!event.end_at) return true
  if (event.end_at === event.start_at) return true
  if (!isLocalMidnight(event.end_at)) return false
  const ms = new Date(event.end_at) - new Date(event.start_at)
  return ms >= 24 * 60 * 60 * 1000
}

export function bucketOf(event) {
  const h = localHour(event.start_at)
  if (h >= 5 && h < 12) return 'morning'
  if (h >= 12 && h < 17) return 'afternoon'
  if (h >= 17 && h < 21) return 'evening'
  return 'night'
}

export function partitionEvents(events, requestedDate) {
  const groups = { allday: [], morning: [], afternoon: [], evening: [], night: [] }
  const hourCounts = new Array(24).fill(0)

  for (const event of events) {
    if (isAllDay(event, requestedDate)) {
      groups.allday.push(event)
      continue
    }

    if (requestedDate && localYMD(event.start_at) < requestedDate) {
      // Night-crossing from previous day (ends before 3am on requested date): skip entirely.
      // It belongs to the previous day's night bucket, not this day.
      if (event.end_at && localYMD(event.end_at) === requestedDate && localHour(event.end_at) < 3) {
        continue
      }
      // Multi-day event still ongoing: show in all-day strip.
      groups.allday.push(event)
      continue
    }

    const hour = localHour(event.start_at)
    hourCounts[hour] += 1
    groups[bucketOf(event)].push(event)
  }

  return { ...groups, hourCounts }
}
