import EventCard from './EventCard'
import { localHour } from '../lib/eventTime'

const TINTS = {
  morning: 'bg-amber-50 border-amber-200 text-amber-900',
  afternoon: 'bg-sky-50 border-sky-200 text-sky-900',
  evening: 'bg-indigo-50 border-indigo-200 text-indigo-900',
  night: 'bg-slate-100 border-slate-300 text-slate-800',
}

export default function BucketSection({ id, label, events }) {
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
    <section id={id} className="scroll-mt-32 mt-6 first:mt-2">
      <h2
        className={`sticky top-32 z-10 ${tint} border rounded-md px-3 py-1.5 text-sm font-semibold flex items-center justify-between`}
      >
        <span>{label}</span>
        <span className="text-xs font-normal opacity-70">
          {events.length} event{events.length === 1 ? '' : 's'}
        </span>
      </h2>
      {hourGroups.map(({ hour, events: hEvents }) => (
        <div key={hour}>
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
