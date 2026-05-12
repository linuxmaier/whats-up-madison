import EventCard from './EventCard'
import { localHour } from '../lib/eventTime'

const TINTS = {
  morning:   'bg-rose-100   border-rose-300   text-rose-900   shadow-sm',
  afternoon: 'bg-sky-100    border-sky-300    text-sky-900    shadow-sm',
  evening:   'bg-violet-300 border-violet-500 text-violet-950 shadow-sm',
  night:     'bg-indigo-900 border-indigo-700 text-indigo-100 shadow-sm',
}

const DIVIDER = {
  morning:   { line: 'border-rose-300/60',   label: 'text-rose-800/70'   },
  afternoon: { line: 'border-sky-300/60',    label: 'text-sky-800/70'    },
  evening:   { line: 'border-white/30',      label: 'text-white/80'      },
  night:     { line: 'border-white/20',      label: 'text-white/70'      },
}

function formatHour(h) {
  if (h === 0) return '12 AM'
  if (h === 12) return '12 PM'
  return h < 12 ? `${h} AM` : `${h - 12} PM`
}

export default function BucketSection({ id, label, events, stickyTop }) {
  if (!events || events.length === 0) return null

  const tint = TINTS[id] ?? 'bg-gray-100 border-gray-200 text-gray-800'
  const divider = DIVIDER[id] ?? { line: 'border-gray-300', label: 'text-gray-500' }

  const hourGroups = []
  for (const event of events) {
    const h = localHour(event.start_at)
    const last = hourGroups[hourGroups.length - 1]
    if (last && last.hour === h) last.events.push(event)
    else hourGroups.push({ hour: h, events: [event] })
  }

  return (
    <section id={id} style={{ scrollMarginTop: stickyTop }} className="mb-6">
      <h2
        style={{ top: stickyTop }}
        className={`sticky z-10 ${tint} border rounded-b-md px-3 py-1.5 text-sm font-semibold flex items-center justify-between`}
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
              <div className={`flex-1 border-t ${divider.line}`} />
              <span className={`text-xs ${divider.label}`}>{formatHour(hour)}</span>
              <div className={`flex-1 border-t ${divider.line}`} />
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
