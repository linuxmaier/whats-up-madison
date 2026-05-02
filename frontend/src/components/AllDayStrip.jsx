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
  const primary = event.sources?.[0]
  const Inner = (
    <>
      <h3 className="text-sm font-semibold text-gray-900 leading-snug line-clamp-2">
        {event.title}
      </h3>
      {event.venue_name && (
        <p className="text-xs text-gray-500 mt-1 truncate">{event.venue_name}</p>
      )}
      {event.all_day && event.description && (
        <p className="text-xs text-gray-400 mt-1 line-clamp-1">{event.description}</p>
      )}
    </>
  )
  if (primary?.source_url) {
    return (
      <a
        href={primary.source_url}
        target="_blank"
        rel="noopener noreferrer"
        className="block bg-white rounded-md border border-gray-200 px-3 py-2 shadow-sm hover:border-emerald-300 hover:shadow transition"
      >
        {Inner}
      </a>
    )
  }
  return (
    <div className="bg-white rounded-md border border-gray-200 px-3 py-2 shadow-sm">
      {Inner}
    </div>
  )
}
