import { useState } from 'react'
import { formatTimeRange } from '../lib/eventTime'

export default function EventCard({ event }) {
  const [expanded, setExpanded] = useState(false)
  const primaryUrl = event.sources?.[0]?.source_url

  return (
    <div
      className="bg-white rounded-lg border border-gray-200 px-4 py-3 shadow-sm flex flex-col cursor-pointer hover:border-gray-300 hover:shadow transition select-none"
      onClick={() => setExpanded(e => !e)}
    >
      <p className="text-xs text-gray-400 mb-0.5">{formatTimeRange(event.start_at, event.end_at)}</p>
      {primaryUrl ? (
        <a
          href={primaryUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-base font-semibold text-gray-900 leading-snug hover:underline"
          onClick={e => e.stopPropagation()}
        >
          {event.title}
        </a>
      ) : (
        <h2 className="text-base font-semibold text-gray-900 leading-snug">{event.title}</h2>
      )}
      {event.venue_name && (
        <p className="text-sm text-gray-500 mt-0.5">{event.venue_name}</p>
      )}
      {event.description && (
        expanded ? (
          <div className="mt-2 space-y-2">
            {event.description.split('\n\n').map((para, i) => (
              <p key={i} className="text-sm text-gray-600 whitespace-pre-line">{para}</p>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-600 mt-2 line-clamp-2 whitespace-pre-line">
            {event.description}
          </p>
        )
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
              onClick={e => e.stopPropagation()}
            >
              {s.source_name} ↗
            </a>
          ))}
        </div>
      )}
      <div className="mt-auto pt-1 flex justify-end">
        <span className="text-[10px] text-gray-300">{expanded ? '▲' : '▼'}</span>
      </div>
    </div>
  )
}
