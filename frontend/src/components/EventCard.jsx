import { formatTimeRange } from '../lib/eventTime'

export default function EventCard({ event }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 px-4 py-3 shadow-sm flex flex-col h-full">
      <p className="text-xs text-gray-400 mb-0.5">{formatTimeRange(event.start_at, event.end_at)}</p>
      <h2 className="text-base font-semibold text-gray-900 leading-snug">{event.title}</h2>
      {event.venue_name && (
        <p className="text-sm text-gray-500 mt-0.5">{event.venue_name}</p>
      )}
      {event.description && (
        <p className="text-sm text-gray-600 mt-2 line-clamp-2">{event.description}</p>
      )}
      {event.categories?.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {event.categories.map((c) => (
            <span
              key={c}
              className="text-[11px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600"
            >
              {c}
            </span>
          ))}
        </div>
      )}
      {event.sources && event.sources.length > 0 && (
        <div className="mt-auto pt-2 flex flex-wrap gap-2">
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
