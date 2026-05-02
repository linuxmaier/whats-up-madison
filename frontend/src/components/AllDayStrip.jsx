import { useState, useRef, useEffect } from 'react'
import { CalendarDays, Send, Check } from 'lucide-react'
import { googleCalendarUrl, downloadIcal, shareCalendarInvite, formatEventText } from '../lib/calendarUtils'

export default function AllDayStrip({ events }) {
  if (!events || events.length === 0) return null

  return (
    <section id="allday" className="scroll-mt-32 mt-4">
      <h2 className="sticky top-32 z-10 bg-emerald-50 border border-emerald-200 text-emerald-900 rounded-md px-3 py-1.5 text-sm font-semibold flex items-center justify-between">
        <span>All Day / Time Varies</span>
        <span className="text-xs font-normal opacity-70">
          {events.length} event{events.length === 1 ? '' : 's'}
        </span>
      </h2>
      <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
        {events.map((event) => (
          <AllDayCard key={event.id} event={event} />
        ))}
      </div>
    </section>
  )
}

function AllDayCard({ event }) {
  const [expanded, setExpanded] = useState(false)
  const [calOpen, setCalOpen] = useState(false)
  const [sendOpen, setSendOpen] = useState(false)
  const [showCheck, setShowCheck] = useState(false)
  const calRef = useRef(null)
  const sendRef = useRef(null)
  const primary = event.sources?.[0]

  useEffect(() => {
    if (!calOpen) return
    function handleOutside(e) {
      if (calRef.current && !calRef.current.contains(e.target)) setCalOpen(false)
    }
    document.addEventListener('mousedown', handleOutside)
    return () => document.removeEventListener('mousedown', handleOutside)
  }, [calOpen])

  useEffect(() => {
    if (!sendOpen) return
    function handleOutside(e) {
      if (sendRef.current && !sendRef.current.contains(e.target)) setSendOpen(false)
    }
    document.addEventListener('mousedown', handleOutside)
    return () => document.removeEventListener('mousedown', handleOutside)
  }, [sendOpen])

  function flashCheck() {
    setShowCheck(true)
    setTimeout(() => setShowCheck(false), 1500)
  }

  async function handleCopyText(e) {
    e.stopPropagation()
    await navigator.clipboard.writeText(formatEventText(event))
    setSendOpen(false)
    flashCheck()
  }

  async function handleSendInvite(e) {
    e.stopPropagation()
    const result = await shareCalendarInvite(event)
    setSendOpen(false)
    if (result?.downloaded) flashCheck()
  }

  return (
    <div
      className="bg-white rounded-md border border-gray-200 px-3 py-2 shadow-sm cursor-pointer hover:border-emerald-300 hover:shadow transition select-none"
      onClick={() => setExpanded(e => !e)}
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
          <div className="relative" ref={calRef}>
            <button
              className="text-gray-400 hover:text-gray-600 p-0.5 rounded cursor-pointer"
              onClick={e => { e.stopPropagation(); setCalOpen(o => !o); setSendOpen(false) }}
              title="Add to calendar"
            >
              <CalendarDays size={13} />
            </button>
            {calOpen && (
              <div className="absolute right-0 top-6 z-10 bg-white border border-gray-200 rounded shadow-md text-sm min-w-max">
                <button
                  className="block w-full text-left px-3 py-2 hover:bg-gray-50 whitespace-nowrap"
                  onClick={e => { e.stopPropagation(); window.open(googleCalendarUrl(event), '_blank'); setCalOpen(false) }}
                >
                  Google Calendar
                </button>
                <button
                  className="block w-full text-left px-3 py-2 hover:bg-gray-50 whitespace-nowrap"
                  onClick={e => { e.stopPropagation(); downloadIcal(event); setCalOpen(false) }}
                >
                  Apple / Outlook (.ics)
                </button>
              </div>
            )}
          </div>
          <div className="relative" ref={sendRef}>
            <button
              className={`p-0.5 rounded cursor-pointer ${showCheck ? 'text-green-600' : 'text-gray-400 hover:text-gray-600'}`}
              onClick={e => { e.stopPropagation(); setSendOpen(o => !o); setCalOpen(false) }}
              title="Send / share event"
            >
              {showCheck ? <Check size={13} /> : <Send size={13} />}
            </button>
            {sendOpen && (
              <div className="absolute right-0 top-6 z-10 bg-white border border-gray-200 rounded shadow-md text-sm min-w-max">
                <button
                  className="block w-full text-left px-3 py-2 hover:bg-gray-50 whitespace-nowrap"
                  onClick={handleCopyText}
                >
                  Copy text
                </button>
                <button
                  className="block w-full text-left px-3 py-2 hover:bg-gray-50 whitespace-nowrap"
                  onClick={handleSendInvite}
                >
                  Calendar invite
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
      {event.venue_name && (
        <p className="text-xs text-gray-500 mt-1 truncate">{event.venue_name}</p>
      )}
      {event.description && (
        <p className={`text-xs text-gray-400 mt-1 whitespace-pre-line ${expanded ? '' : 'line-clamp-1'}`}>
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
      <div className="mt-1 flex justify-end">
        <span className="text-[10px] text-gray-300">{expanded ? '▲' : '▼'}</span>
      </div>
    </div>
  )
}
