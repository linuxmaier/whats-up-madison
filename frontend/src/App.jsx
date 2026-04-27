import { useEffect, useState } from 'react'
import DatePicker from './components/DatePicker'
import EventCard from './components/EventCard'

function toLocalDateString(date) {
  return date.toLocaleDateString('en-CA') // YYYY-MM-DD in local time
}

export default function App() {
  const [selectedDate, setSelectedDate] = useState(toLocalDateString(new Date()))
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetch(`/events?date=${selectedDate}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((data) => setEvents(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [selectedDate])

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-2xl mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-1">What's Up Madison</h1>
        <p className="text-gray-500 mb-6 text-sm">Events in Madison, WI</p>

        <DatePicker value={selectedDate} onChange={setSelectedDate} />

        <div className="mt-6">
          {loading && (
            <p className="text-gray-400 text-sm">Loading…</p>
          )}
          {error && (
            <p className="text-red-500 text-sm">Error: {error}</p>
          )}
          {!loading && !error && events.length === 0 && (
            <p className="text-gray-400 text-sm">No events found for this date.</p>
          )}
          {!loading && !error && events.length > 0 && (
            <>
              <p className="text-gray-500 text-xs mb-4">
                {events.length} event{events.length !== 1 ? 's' : ''}
              </p>
              <div className="space-y-3">
                {events.map((event) => (
                  <EventCard key={event.id} event={event} />
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
