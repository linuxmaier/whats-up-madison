import { useMemo } from 'react'
import EventCard from './EventCard'
import { formatLocalDate, localYMD } from '../lib/eventTime'

function todayLocalYMD() {
  return new Date().toLocaleDateString('en-CA')
}

function groupByDate(events) {
  const today = todayLocalYMD()
  const groups = new Map()
  for (const event of events) {
    // Multi-day event in progress: bucket under today rather than its start date.
    let key = localYMD(event.start_at)
    if (key < today) key = today
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(event)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([ymd, evs]) => ({ ymd, events: evs }))
}

export default function SearchResults({ query, events, loading, error, stickyTop }) {
  const groups = useMemo(() => groupByDate(events), [events])

  if (loading) return <p className="text-gray-400 text-sm">Searching…</p>
  if (error) return <p className="text-red-500 text-sm">Error: {error}</p>
  if (events.length === 0) {
    return (
      <p className="text-gray-400 text-sm">
        No upcoming events match “{query}”.
      </p>
    )
  }

  return (
    <>
      <p className="text-gray-500 text-xs mb-2">
        {events.length} matching event{events.length === 1 ? '' : 's'}
      </p>
      {groups.map(({ ymd, events: evs }) => (
        <section key={ymd} className="mt-6 first:mt-2">
          <h2
            style={{ top: stickyTop }}
            className="sticky z-10 bg-blue-50 border border-blue-200 text-blue-900 rounded-md px-3 py-1.5 text-sm font-semibold flex items-center justify-between"
          >
            <span>{formatLocalDate(`${ymd}T12:00:00Z`)}</span>
            <span className="text-xs font-normal opacity-70">
              {evs.length} event{evs.length === 1 ? '' : 's'}
            </span>
          </h2>
          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 items-start">
            {evs.map((event) => (
              <EventCard key={event.id} event={event} />
            ))}
          </div>
        </section>
      ))}
    </>
  )
}
