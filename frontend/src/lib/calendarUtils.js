function toUtcDateStr(isoStr) {
  return new Date(isoStr).toISOString().slice(0, 10).replace(/-/g, '')
}

function toUtcDateTimeStr(isoStr) {
  return new Date(isoStr).toISOString().slice(0, 19).replace(/[-:]/g, '') + 'Z'
}

function nextDayIso(isoStr) {
  const d = new Date(isoStr)
  d.setUTCDate(d.getUTCDate() + 1)
  return d.toISOString()
}

function escapeIcal(str) {
  return str
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r\n|\n|\r/g, '\\n')
}

function icalFilename(title) {
  return title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 50) + '.ics'
}

function buildIcalContent(event) {
  const { id, title, description, start_at, end_at, venue_name, venue_address, all_day, sources } = event
  const now = new Date().toISOString().slice(0, 19).replace(/[-:]/g, '') + 'Z'
  const location = [venue_name, venue_address].filter(Boolean).join(', ')
  const url = sources?.[0]?.source_url || ''

  const dtstart = all_day
    ? `DTSTART;VALUE=DATE:${toUtcDateStr(start_at)}`
    : `DTSTART:${toUtcDateTimeStr(start_at)}`
  const dtend = all_day
    ? `DTEND;VALUE=DATE:${toUtcDateStr(end_at || nextDayIso(start_at))}`
    : `DTEND:${toUtcDateTimeStr(end_at || start_at)}`

  return [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//whats-up-madison//Events//EN',
    'BEGIN:VEVENT',
    `UID:${id}@whats-up-madison`,
    `DTSTAMP:${now}`,
    dtstart,
    dtend,
    `SUMMARY:${escapeIcal(title)}`,
    description ? `DESCRIPTION:${escapeIcal(description)}` : null,
    location ? `LOCATION:${escapeIcal(location)}` : null,
    url ? `URL:${url}` : null,
    'END:VEVENT',
    'END:VCALENDAR',
  ].filter(Boolean).join('\r\n')
}

const TZ = 'America/Chicago'

const dateFmt = new Intl.DateTimeFormat('en-US', {
  timeZone: TZ,
  weekday: 'long',
  month: 'long',
  day: 'numeric',
  year: 'numeric',
})

const timeFmt = new Intl.DateTimeFormat('en-US', {
  timeZone: TZ,
  hour: 'numeric',
  minute: '2-digit',
})

export function formatEventText(event) {
  const { title, start_at, end_at, all_day, venue_name, venue_address, description, sources } = event
  const dateStr = dateFmt.format(new Date(start_at))
  const timeStr = all_day
    ? 'All day'
    : end_at
      ? `${timeFmt.format(new Date(start_at))} – ${timeFmt.format(new Date(end_at))}`
      : timeFmt.format(new Date(start_at))
  const location = [venue_name, venue_address].filter(Boolean).join(', ')
  const url = sources?.[0]?.source_url
  return [
    title,
    `${dateStr} · ${timeStr}`,
    location || null,
    description ? `\n${description}` : null,
    url ? `\n${url}` : null,
  ].filter(Boolean).join('\n')
}

export function googleCalendarUrl(event) {
  const { title, description, start_at, end_at, venue_name, venue_address, all_day } = event
  let startFmt, endFmt
  if (all_day) {
    startFmt = toUtcDateStr(start_at)
    endFmt = toUtcDateStr(end_at || nextDayIso(start_at))
  } else {
    startFmt = toUtcDateTimeStr(start_at)
    endFmt = toUtcDateTimeStr(end_at || start_at)
  }
  const location = [venue_name, venue_address].filter(Boolean).join(', ')
  const params = new URLSearchParams({
    action: 'TEMPLATE',
    text: title,
    dates: `${startFmt}/${endFmt}`,
    details: description || '',
    location,
  })
  return `https://calendar.google.com/calendar/render?${params}`
}

export function downloadIcal(event) {
  const content = buildIcalContent(event)
  const blob = new Blob([content], { type: 'text/calendar;charset=utf-8' })
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = icalFilename(event.title)
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(href)
}

// Shares a calendar invite (.ics) via the native share sheet on mobile.
// Falls back to downloading the .ics file on desktop so the user can attach it to an email.
// Returns { downloaded: true } when the fallback download was used.
export async function shareCalendarInvite(event) {
  const content = buildIcalContent(event)
  const filename = icalFilename(event.title)
  const blob = new Blob([content], { type: 'text/calendar;charset=utf-8' })
  const file = new File([blob], filename, { type: 'text/calendar' })

  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: event.title })
    } catch {
      // user dismissed the share sheet
    }
    return {}
  }

  // Desktop fallback: download the .ics so the user can attach it to email
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(href)
  return { downloaded: true }
}
