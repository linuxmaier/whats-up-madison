import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { formatTimeRange } from '../lib/eventTime'
import { sortedSources } from '../lib/sources'
import EventActionButtons from './EventActionButtons'

export default function EventModal({ event, onClose }) {
  const sources = sortedSources(event.sources)
  const primaryUrl = sources[0]?.source_url
  const dialogRef = useRef(null)

  useEffect(() => {
    function handleKey(e) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onClose])

  useEffect(() => {
    const previousFocus = document.activeElement
    dialogRef.current?.focus()
    return () => { previousFocus?.focus() }
  }, [])

  return createPortal(
    <div
      className="fixed inset-0 flex items-center justify-center p-4"
      style={{ zIndex: 10000 }}
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/30" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="event-modal-title"
        tabIndex={-1}
        className="relative bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[80vh] overflow-y-auto focus:outline-none"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-4 flex flex-col gap-2">
          <div className="flex items-start justify-between gap-2">
            {event.all_day ? (
              <div className="flex-1 min-w-0">
                {primaryUrl ? (
                  <a
                    id="event-modal-title"
                    href={primaryUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-lg font-semibold text-gray-900 leading-snug hover:underline"
                  >
                    {event.title}
                  </a>
                ) : (
                  <h3 id="event-modal-title" className="text-lg font-semibold text-gray-900 leading-snug">{event.title}</h3>
                )}
              </div>
            ) : (
              <p className="text-xs text-gray-400 mt-0.5">{formatTimeRange(event.start_at, event.end_at)}</p>
            )}
            <div className="flex items-center gap-0.5 flex-shrink-0">
              <EventActionButtons event={event} />
              <button
                className="text-gray-400 hover:text-gray-600 p-1 rounded cursor-pointer ml-1"
                onClick={onClose}
                title="Close"
              >
                <X size={14} />
              </button>
            </div>
          </div>
          {!event.all_day && (
            primaryUrl ? (
              <a
                id="event-modal-title"
                href={primaryUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-lg font-semibold text-gray-900 leading-snug hover:underline"
              >
                {event.title}
              </a>
            ) : (
              <h2 id="event-modal-title" className="text-lg font-semibold text-gray-900 leading-snug">{event.title}</h2>
            )
          )}
          {event.venue_name && (
            <p className="text-sm text-gray-500">{event.venue_name}</p>
          )}
          {event.description && (
            <div className="mt-1 space-y-2">
              {event.description.split('\n\n').map((para, i) => (
                <p key={i} className="text-sm text-gray-600 whitespace-pre-line">{para}</p>
              ))}
            </div>
          )}
          {event.categories?.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
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
            <div className="pt-2 flex flex-wrap gap-2 border-t border-gray-100 mt-1">
              {sources.map((s) => (
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
      </div>
    </div>,
    document.body
  )
}
