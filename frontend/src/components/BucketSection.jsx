import EventCard from './EventCard'
import { localHour } from '../lib/eventTime'

const TINTS = {
  morning: 'bg-amber-100 border-amber-300 text-amber-800 shadow-sm',
  afternoon: 'bg-sky-100 border-sky-300 text-sky-800 shadow-sm',
  evening: 'bg-indigo-100 border-indigo-300 text-indigo-800 shadow-sm',
  night: 'bg-slate-200 border-slate-400 text-slate-900 shadow-sm',
}

function formatHour(h) {
  if (h === 0) return '12 AM'
  if (h === 12) return '12 PM'
  return h < 12 ? `${h} AM` : `${h - 12} PM`
}

export default function BucketSection({ id, label, events, stickyTop }) {
  if (!events || events.length === 0) return null

  const tint = TINTS[id] ?? 'bg-gray-100 border-gray-200 text-gray-800'

  const hourGroups = []
  for (const event of events) {
    const h = localHour(event.start_at)
    const last = hourGroups[hourGroups.length - 1]
    if (last && last.hour === h) last.events.push(event)
    else hourGroups.push({ hour: h, events: [event] })
  }

  return (
    <section id={id} style={{ scrollMarginTop: stickyTop }} className="mt-6 first:mt-2">
      <h2
        style={{ top: stickyTop }}
        className={`sticky z-10 ${tint} border rounded-md px-3 py-1.5 text-sm font-semibold flex items-center justify-between`}
      >
        <span>{label}</span>
        <span className="text-xs font-normal opacity-70">
          {events.length} event{events.length === 1 ? '' : 's'}
        </span>
      </h2>
      {hourGroups.map(({ hour, events: hEvents }, i) => (
        <div key={hour}>
          {i > 0 && (
            <div className="flex items-center gap-3 mt-4 mb-1">
              <div className="flex-1 border-t border-blue-100" />
              <span className="text-xs text-gray-500">{formatHour(hour)}</span>
              <div className="flex-1 border-t border-blue-100" />
            </div>
          )}
          <div id={`hour-${hour}`} className="scroll-mt-40" />
          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 items-start">
            {hEvents.map((event) => (
              <EventCard key={event.id} event={event} />
            ))}
          </div>
        </div>
      ))}
    </section>
  )
}
