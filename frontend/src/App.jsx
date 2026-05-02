import { useEffect, useMemo, useState } from 'react'
import DatePicker from './components/DatePicker'
import DensityRail from './components/DensityRail'
import AllDayStrip from './components/AllDayStrip'
import BucketSection from './components/BucketSection'
import CategoryFilter from './components/CategoryFilter'
import VenueFilter from './components/VenueFilter'
import { partitionEvents } from './lib/eventTime'
import {
  filterEvents,
  loadFilterState,
  saveFilterState,
} from './lib/categories'

function toLocalDateString(date) {
  return date.toLocaleDateString('en-CA') // YYYY-MM-DD in local time
}

const BUCKETS = [
  { id: 'morning', label: 'Morning', startHour: 5, endHour: 12 },
  { id: 'afternoon', label: 'Afternoon', startHour: 12, endHour: 17 },
  { id: 'evening', label: 'Evening', startHour: 17, endHour: 21 },
  { id: 'night', label: 'Late Night', startHour: 21, endHour: 29 }, // wraps past midnight
]

function bucketForHour(hour) {
  for (const b of BUCKETS) {
    if (hour >= b.startHour && hour < b.endHour) return b.id
  }
  if (hour < 5) return 'night'
  return 'morning'
}

export default function App() {
  const [selectedDate, setSelectedDate] = useState(toLocalDateString(new Date()))
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState(loadFilterState)
  const [hiddenVenues, setHiddenVenues] = useState(new Set())

  useEffect(() => {
    setLoading(true)
    setError(null)
    setHiddenVenues(new Set())
    fetch(`/events?date=${selectedDate}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((data) => setEvents(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [selectedDate])

  useEffect(() => {
    saveFilterState(filter)
  }, [filter])

  const allVenues = useMemo(() => {
    const names = events.map((e) => e.venue_name).filter(Boolean)
    return [...new Set(names)].sort()
  }, [events])

  const filteredEvents = useMemo(() => {
    let result = filterEvents(events, filter)
    if (hiddenVenues.size > 0) {
      result = result.filter((e) => !!e.venue_name && !hiddenVenues.has(e.venue_name))
    }
    return result
  }, [events, filter, hiddenVenues])

  const partition = useMemo(
    () => partitionEvents(filteredEvents, selectedDate),
    [filteredEvents, selectedDate],
  )

  const handleJumpToHour = (hour) => {
    const el = document.getElementById(`hour-${hour}`) ?? document.getElementById(bucketForHour(hour))
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="sticky top-0 z-30 bg-gray-50/95 backdrop-blur border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 py-2 flex items-center justify-between gap-3">
          <h1 className="text-lg font-bold text-gray-900">What's Up Madison</h1>
          <div className="flex items-center gap-2">
            <CategoryFilter
              selected={filter.selected}
              includeUncategorized={filter.includeUncategorized}
              onChange={setFilter}
            />
            <VenueFilter
              allVenues={allVenues}
              hiddenVenues={hiddenVenues}
              onChange={setHiddenVenues}
            />
            <DatePicker value={selectedDate} onChange={setSelectedDate} />
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 pt-4 pb-6">
        <div>
          {loading && <p className="text-gray-400 text-sm">Loading…</p>}
          {error && <p className="text-red-500 text-sm">Error: {error}</p>}
          {!loading && !error && events.length === 0 && (
            <p className="text-gray-400 text-sm">No events found for this date.</p>
          )}
          {!loading && !error && events.length > 0 && filteredEvents.length === 0 && (
            <p className="text-gray-400 text-sm">
              All {events.length} events for this date are hidden by your filter.
            </p>
          )}
          {!loading && !error && filteredEvents.length > 0 && (
            <>
              <p className="text-gray-500 text-xs mb-2">
                {filteredEvents.length} event{filteredEvents.length !== 1 ? 's' : ''}
                {filteredEvents.length !== events.length && (
                  <span className="text-gray-400"> of {events.length}</span>
                )}
              </p>
              <DensityRail
                hourCounts={partition.hourCounts}
                onJumpToHour={handleJumpToHour}
              />
              <AllDayStrip events={partition.allday} />
              {BUCKETS.map((b) => (
                <BucketSection
                  key={b.id}
                  id={b.id}
                  label={b.label}
                  events={partition[b.id]}
                />
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
