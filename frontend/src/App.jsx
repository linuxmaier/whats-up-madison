import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import DatePicker from './components/DatePicker'
import DensityRail from './components/DensityRail'
import AllDayStrip from './components/AllDayStrip'
import BucketSection from './components/BucketSection'
import CategoryFilter from './components/CategoryFilter'
import VenueFilter from './components/VenueFilter'
import MapView from './components/MapView'
import { partitionEvents } from './lib/eventTime'
import {
  filterEvents,
  loadFilterState,
  saveFilterState,
  loadHiddenVenues,
  saveHiddenVenues,
} from './lib/categories'

const API_BASE = import.meta.env.VITE_BACKEND_URL || ''

function toLocalDateString(date) {
  return date.toLocaleDateString('en-CA') // YYYY-MM-DD in local time
}

const VIEW_KEY = 'whats-up-madison.viewMode'
function loadViewMode() {
  try {
    return localStorage.getItem(VIEW_KEY) === 'map' ? 'map' : 'list'
  } catch {
    return 'list'
  }
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
  const [hiddenVenues, setHiddenVenues] = useState(loadHiddenVenues)
  const [viewMode, setViewMode] = useState(loadViewMode)

  const headerRef = useRef(null)
  const [railEl, setRailEl] = useState(null)
  const [headerH, setHeaderH] = useState(0)
  const [railH, setRailH] = useState(0)

  useLayoutEffect(() => {
    const el = headerRef.current
    if (!el) return
    setHeaderH(el.offsetHeight)
    const ro = new ResizeObserver(() => setHeaderH(el.offsetHeight))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useLayoutEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!railEl) { setRailH(0); return }
    setRailH(railEl.offsetHeight)
    const ro = new ResizeObserver(() => setRailH(railEl.offsetHeight))
    ro.observe(railEl)
    return () => ro.disconnect()
  }, [railEl])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true)
    setError(null)
    fetch(`${API_BASE}/events?date=${selectedDate}`)
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

  useEffect(() => {
    saveHiddenVenues(hiddenVenues)
  }, [hiddenVenues])

  useEffect(() => {
    try { localStorage.setItem(VIEW_KEY, viewMode) } catch { /* ignore quota */ }
  }, [viewMode])

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
      <div ref={headerRef} className="sticky top-0 z-30 bg-gray-50/95 backdrop-blur border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 py-2 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 sm:gap-3">
          <button
            type="button"
            onClick={() => setSelectedDate(toLocalDateString(new Date()))}
            className="text-lg font-bold text-gray-900 hover:text-gray-600 cursor-pointer transition-colors"
          >
            What's Up Madison
          </button>
          <div className="flex items-center gap-2">
            <div className="inline-flex border border-gray-300 rounded overflow-hidden text-sm">
              <button
                type="button"
                onClick={() => setViewMode('list')}
                className={`px-3 py-1 cursor-pointer ${viewMode === 'list' ? 'bg-gray-800 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'}`}
              >
                List
              </button>
              <button
                type="button"
                onClick={() => setViewMode('map')}
                className={`px-3 py-1 cursor-pointer ${viewMode === 'map' ? 'bg-gray-800 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'}`}
              >
                Map
              </button>
            </div>
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
              {viewMode === 'list' ? (
                <>
                  <DensityRail
                    ref={setRailEl}
                    stickyTop={headerH}
                    hourCounts={partition.hourCounts}
                    onJumpToHour={handleJumpToHour}
                  />
                  <AllDayStrip events={partition.allday} stickyTop={headerH + railH} />
                  {BUCKETS.map((b) => (
                    <BucketSection
                      key={b.id}
                      id={b.id}
                      label={b.label}
                      events={partition[b.id]}
                      stickyTop={headerH + railH}
                    />
                  ))}
                </>
              ) : (
                <MapView events={filteredEvents} stickyTop={headerH} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
