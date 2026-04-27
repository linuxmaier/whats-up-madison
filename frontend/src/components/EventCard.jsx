function formatTime(isoString) {
  const date = new Date(isoString)
  return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Chicago' })
}

function formatTimeRange(start, end) {
  if (!end) return formatTime(start)
  return `${formatTime(start)} – ${formatTime(end)}`
}

export default function EventCard({ event }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 px-4 py-3 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs text-gray-400 mb-0.5">{formatTimeRange(event.start_at, event.end_at)}</p>
          <h2 className="text-base font-semibold text-gray-900 leading-snug">{event.title}</h2>
          {event.venue_name && (
            <p className="text-sm text-gray-500 mt-0.5">{event.venue_name}</p>
          )}
        </div>
      </div>
      {event.sources && event.sources.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {event.sources.map((s) => (
            <a
              key={s.source_name}
              href={s.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-600 hover:underline"
            >
              {s.source_name} ↗
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
