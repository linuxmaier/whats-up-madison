import { useState } from 'react'
import { sortedSources } from '../lib/sources'
import EventModal from './EventModal'
import EventActionButtons from './EventActionButtons'

export default function AllDayStrip({ events, stickyTop }) {
  if (!events || events.length === 0) return null

  return (
    <section id="allday" className="scroll-mt-32 mt-4">
      <h2 className="sticky z-10 bg-emerald-50 border border-emerald-200 text-emerald-900 rounded-md px-3 py-1.5 text-sm font-semibold flex items-center justify-between" style={{ top: stickyTop }}>
        <span>All Day / Time Varies</span>
        <span className="text-xs font-normal opacity-70">
          {events.length} event{events.length === 1 ? '' : 's'}
        </span>
      </h2>
      <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 items-start">
        {events.map((event) => (
          <AllDayCard key={event.id} event={event} />
        ))}
      </div>
    </section>
  )
}

function AllDayCard({ event }) {
  const [modalOpen, setModalOpen] = useState(false)
  const sources = sortedSources(event.sources)
  const primary = sources[0]

  return (
    <>
      <div
        className="bg-white rounded-md border border-gray-200 px-3 py-2 shadow-sm cursor-pointer hover:border-emerald-300 hover:shadow transition select-none"
        onClick={() => setModalOpen(true)}
      >
        <div className="flex items-start justify-between gap-1">
          {primary?.source_url ? (
            <a
              href={primary.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm font-semibold text-gray-900 leading-snug hover:underline line-clamp-2 block flex-1 min-w-0"
              onClick={e => e.stopPropagation()}
            >
              {event.title}
            </a>
          ) : (
            <h3 className="text-sm font-semibold text-gray-900 leading-snug line-clamp-2 flex-1 min-w-0">{event.title}</h3>
          )}
          <div className="flex items-center gap-0.5 flex-shrink-0 ml-1">
            <EventActionButtons event={event} compact />
          </div>
        </div>
        {event.venue_name && (
          <p className="text-xs text-gray-500 mt-1 truncate">{event.venue_name}</p>
        )}
        {event.description && (
          <p className="text-xs text-gray-400 mt-1 whitespace-pre-line line-clamp-1">
            {event.description}
          </p>
        )}
        {event.categories?.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
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
          <div className="mt-1.5 flex flex-wrap gap-2">
            {sources.map((s) => (
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
      </div>

      {modalOpen && <EventModal event={event} onClose={() => setModalOpen(false)} />}
    </>
  )
}
