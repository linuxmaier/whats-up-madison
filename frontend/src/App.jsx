import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import DatePicker from './components/DatePicker'
import DensityRail from './components/DensityRail'
import AllDayStrip from './components/AllDayStrip'
import BucketSection from './components/BucketSection'
import CategoryFilter from './components/CategoryFilter'
import VenueFilter from './components/VenueFilter'
import MapView from './components/MapView'
import FeedbackModal from './components/FeedbackModal'
import SearchBar from './components/SearchBar'
import SearchResults from './components/SearchResults'
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

function CapitolIcon({ className }) {
  return (
    <svg viewBox="0 0 100 100" className={className} fill="currentColor" aria-hidden="true">
      <path d="M72.6,53.3c-8-1.1-15.1-1.5-22.6-1.5s-14.5,0.4-22.6,1.5c-1.5,0.3-2.5,2.1-2.5,3.4c0,1,0,11.2,0,11.2c0.7-0.1,2-0.2,3.8-0.3v-8.7c0-1.4,1.1-2.6,2.5-2.7c1.3-0.1,2.4,0.9,2.4,2.3v8.8c2.2-0.1,4.8-0.2,7.6-0.3v-9.2c0-1.4,1.1-2.5,2.5-2.5c1.4,0,2.5,1,2.5,2.4v9.2c2.4,0,5.2,0,7.6,0v-9.2c0-1.4,1.1-2.4,2.5-2.4c1.3,0,2.5,1.2,2.5,2.5V67c2.8,0.1,5.4,0.2,7.6,0.3v-8.8c0-1.4,1.1-2.4,2.4-2.3c1.4,0.1,2.5,1.3,2.5,2.7v8.7c1.8,0.1,3.1,0.2,3.8,0.3c0,0,0-10.2,0-11.2C75.3,55.3,74.1,53.6,72.6,53.3z"/>
      <path d="M50,69.4c-20.5,0-34.6,2.4-34.6,2.4V95l2.6-0.1c17.7-0.6,30.1-0.7,32-0.7s14.7,0.1,32.3,0.7l2.3,0.1V71.8C84.6,71.8,70.5,69.4,50,69.4z M27.4,87.8c0,1.3-1.1,2.5-2.5,2.7c-1.3,0.1-2.4-0.8-2.4-2.2c0-3.6,0-7.2,0-10.8c0-1.3,1.1-2.6,2.4-2.7c1.3-0.1,2.5,0.9,2.5,2.2C27.4,80.7,27.4,84.3,27.4,87.8z M39.9,87c0,1.3-1.1,2.5-2.5,2.6c-1.4,0.1-2.5-1-2.5-2.3c0-3.6,0-7.2,0-10.8c0-1.3,1.1-2.5,2.5-2.6c1.4-0.1,2.5,1,2.5,2.3C39.9,79.9,39.9,83.4,39.9,87z M52.5,86.8c0,1.3-1.1,2.4-2.4,2.4c-1.4,0-2.5-1.1-2.5-2.4c0-3.6,0-7.2,0-10.8c0-1.3,1.1-2.5,2.5-2.5s2.4,1.1,2.4,2.5C52.5,79.7,52.5,83.3,52.5,86.8z M65.1,87.3c0,1.3-1.1,2.4-2.5,2.3c-1.4-0.1-2.5-1.2-2.5-2.6c0-3.6,0-7.2,0-10.8c0-1.3,1.1-2.4,2.5-2.3c1.4,0.1,2.5,1.2,2.5,2.6C65.1,80.1,65.1,83.7,65.1,87.3z M77.5,88.3c0,1.3-1.1,2.3-2.4,2.2c-1.3-0.1-2.4-1.3-2.4-2.7c0-3.6,0-7.2,0-10.8c0-1.3,1.1-2.4,2.4-2.2c1.3,0.1,2.4,1.4,2.4,2.7C77.5,81.2,77.5,84.8,77.5,88.3z"/>
      <path d="M72.4,50.5c-0.3-12-8.6-23.2-22.4-23.2S27.9,38.3,27.6,50.5C31.8,49.8,52.5,47.4,72.4,50.5z"/>
      <path d="M57.2,23.3c0-2.6-1.7-4.7-3.7-5.7V8.5C53.5,6.6,51.9,5,50,5s-3.5,1.6-3.5,3.5v9.3c-1.9,1-3.4,3-3.4,5.5c0,0.7-0.2,1.6-0.4,2.5c2.7-0.8,5.2-1,7.4-1c2.2,0,4.7,0.3,7.4,1C57.3,24.9,57.2,24,57.2,23.3z"/>
    </svg>
  )
}

export default function App() {
  const [selectedDate, setSelectedDate] = useState(toLocalDateString(new Date()))
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState(loadFilterState)
  const [hiddenVenues, setHiddenVenues] = useState(loadHiddenVenues)
  const [viewMode, setViewMode] = useState(loadViewMode)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState(null)

  const trimmedQuery = searchQuery.trim()
  const isSearching = trimmedQuery.length > 0
  const isMapMode = viewMode === 'map' && !isSearching

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
    if (!isSearching) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSearchResults([])
      setSearchError(null)
      setSearchLoading(false)
      return
    }
    setSearchLoading(true)
    setSearchError(null)
    const controller = new AbortController()
    const timer = setTimeout(() => {
      fetch(`${API_BASE}/events/search?q=${encodeURIComponent(trimmedQuery)}`, {
        signal: controller.signal,
      })
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          return res.json()
        })
        .then((data) => setSearchResults(data))
        .catch((err) => {
          if (err.name === 'AbortError') return
          setSearchError(err.message)
        })
        .finally(() => setSearchLoading(false))
    }, 250)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [isSearching, trimmedQuery])

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
    <div
      className={isMapMode ? 'h-screen flex flex-col overflow-hidden' : 'min-h-screen'}
      style={{ background: 'linear-gradient(to bottom, #fce4ec 0%, #e3f2fd 12%, #bbdefb 28%, #90a4d4 58%, #283593 85%, #1a237e 100%)' }}
    >
      <div
        ref={headerRef}
        className="sticky top-0 z-30 border-b"
        style={{ background: 'var(--c-brand)', borderColor: 'rgba(0,0,0,0.15)' }}
      >
        <div className="max-w-7xl mx-auto px-4 py-2 flex flex-col items-center gap-y-1 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
          <button
            type="button"
            onClick={() => setSelectedDate(toLocalDateString(new Date()))}
            className="flex items-center gap-2 text-lg font-bold hover:opacity-75 cursor-pointer transition-opacity"
          >
            <CapitolIcon className="w-5 h-5 flex-shrink-0 text-accent" />
            <span>
              <span className="text-white">What&apos;s Up </span>
              <span className="text-accent">Madison</span>
            </span>
          </button>
          <div className="flex flex-wrap justify-center sm:flex-nowrap sm:justify-start items-center gap-2">
            <SearchBar value={searchQuery} onChange={setSearchQuery} />
            {!isSearching && (
              <div className="inline-flex border border-white/30 rounded overflow-hidden text-sm">
                <button
                  type="button"
                  onClick={() => setViewMode('list')}
                  className={`px-3 py-1 cursor-pointer transition-colors ${viewMode === 'list' ? 'bg-white text-brand font-medium' : 'bg-white/10 text-white hover:bg-white/20'}`}
                >
                  List
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode('map')}
                  className={`px-3 py-1 cursor-pointer transition-colors ${viewMode === 'map' ? 'bg-white text-brand font-medium' : 'bg-white/10 text-white hover:bg-white/20'}`}
                >
                  Map
                </button>
              </div>
            )}
            <div className="flex items-center gap-2">
              {!isSearching && (
                <>
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
                  <DatePicker value={selectedDate} onChange={setSelectedDate} onDark />
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className={isMapMode ? 'flex-1 min-h-0 flex flex-col w-full max-w-7xl mx-auto px-4 pt-4' : 'max-w-7xl mx-auto px-4 pt-4 pb-6'}>
        <div className={isMapMode ? 'flex-1 min-h-0 flex flex-col' : ''}>
          {isSearching ? (
            <SearchResults
              query={trimmedQuery}
              events={searchResults}
              loading={searchLoading}
              error={searchError}
              stickyTop={headerH}
            />
          ) : (
            <>
              {loading && <p className="text-gray-400 text-base animate-pulse">Warming up the site because we&apos;re using crappy free tier servers...</p>}
              {error && <p className="text-red-500 text-sm">Error: {error}</p>}
              {!loading && !error && events.length === 0 && (
                <p className="text-gray-500 text-sm">No events found for this date.</p>
              )}
              {!loading && !error && events.length > 0 && filteredEvents.length === 0 && (
                <p className="text-gray-500 text-sm">
                  All {events.length} events for this date are hidden by your filter.
                </p>
              )}
              {!loading && !error && filteredEvents.length > 0 && (
                <>
                  {!isMapMode && (
                    <p className="text-gray-500 text-xs mb-2">
                      {filteredEvents.length} event{filteredEvents.length !== 1 ? 's' : ''}
                      {filteredEvents.length !== events.length && (
                        <span className="text-gray-400"> of {events.length}</span>
                      )}
                    </p>
                  )}
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
                    <MapView events={filteredEvents} stickyTop={headerH} fillHeight />
                  )}
                </>
              )}
            </>
          )}
        </div>
      </div>

      <footer className="border-t border-gray-200 mt-4">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3 text-xs text-gray-400">
          <a
            href="https://github.com/linuxmaier/whats-up-madison"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-gray-600 transition-colors"
          >
            Open source
          </a>
          <span aria-hidden="true">·</span>
          <button
            type="button"
            className="hover:text-gray-600 transition-colors cursor-pointer"
            onClick={() => setFeedbackOpen(true)}
          >
            Submit feedback
          </button>
          <span aria-hidden="true">·</span>
          <span>
            Icon by Loren Klein from{' '}
            <a
              href="https://thenounproject.com/browse/icons/term/capitol-building/"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-gray-600 transition-colors"
            >
              Noun Project
            </a>
            {' '}(CC BY 3.0)
          </span>
        </div>
      </footer>

      <FeedbackModal open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />
    </div>
  )
}
