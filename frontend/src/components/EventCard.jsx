import { useState } from 'react'
import { formatTimeRange } from '../lib/eventTime'
import { sortedSources, isSafeHttpUrl } from '../lib/sources'
import EventModal from './EventModal'
import EventActionButtons from './EventActionButtons'
import CostBadge from './CostBadge'

export default function EventCard({ event }) {
  const [modalOpen, setModalOpen] = useState(false)
  const sources = sortedSources(event.sources)
  const primaryUrl = isSafeHttpUrl(sources[0]?.source_url) ? sources[0].source_url : null

  return (
    <>
      <div
        tabIndex={0}
        className="bg-white rounded-lg border border-gray-200 px-4 py-3 shadow-sm flex flex-col cursor-pointer hover:border-gray-300 hover:shadow transition select-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1"
        onClick={() => setModalOpen(true)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setModalOpen(true) } }}
      >
        <div className="flex items-start justify-between mb-0.5">
          <div className="flex items-center gap-1.5">
            <p className="text-xs text-gray-400">{formatTimeRange(event.start_at, event.end_at)}</p>
            <CostBadge description={event.description} />
          </div>
          <div className="flex items-center gap-0.5 ml-2 flex-shrink-0">
            <EventActionButtons event={event} />
          </div>
        </div>
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
          <p className="text-sm text-gray-600 mt-2 line-clamp-2 whitespace-pre-line">
            {event.description}
          </p>
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
        {sources.length > 0 && (
          <div className="mt-auto pt-2 flex flex-wrap gap-2">
            {sources.map((s) => (
              isSafeHttpUrl(s.source_url) ? (
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
              ) : (
                <span key={s.source_name} className="text-xs text-gray-500">
                  {s.source_name}
                </span>
              )
            ))}
          </div>
        )}
      </div>

      {modalOpen && <EventModal event={event} onClose={() => setModalOpen(false)} />}
    </>
  )
}
