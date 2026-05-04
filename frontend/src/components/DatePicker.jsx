import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

const DAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

function parseDate(str) {
  const [y, m, d] = str.split('-').map(Number)
  return { year: y, month: m - 1, day: d }
}

function toDateStr(year, month, day) {
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function getDaysInMonth(year, month) {
  return new Date(year, month + 1, 0).getDate()
}

function getFirstDayOfWeek(year, month) {
  return new Date(year, month, 1).getDay()
}

export default function DatePicker({ value, onChange }) {
  const [open, setOpen] = useState(false)
  const [viewYear, setViewYear] = useState(null)
  const [viewMonth, setViewMonth] = useState(null)
  const containerRef = useRef(null)

  const { year: selYear, month: selMonth } = parseDate(value)

  function openCalendar() {
    setViewYear(selYear)
    setViewMonth(selMonth)
    setOpen((v) => !v)
  }

  useEffect(() => {
    if (!open) return
    function handleClick(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  useEffect(() => {
    if (!open) return
    function handleKey(e) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [open])

  function shift(days) {
    const d = new Date(value + 'T12:00:00')
    d.setDate(d.getDate() + days)
    onChange(d.toLocaleDateString('en-CA'))
  }

  function prevMonth() {
    if (viewMonth === 0) { setViewMonth(11); setViewYear((y) => y - 1) }
    else setViewMonth((m) => m - 1)
  }

  function nextMonth() {
    if (viewMonth === 11) { setViewMonth(0); setViewYear((y) => y + 1) }
    else setViewMonth((m) => m + 1)
  }

  function selectDay(day) {
    onChange(toDateStr(viewYear, viewMonth, day))
    setOpen(false)
  }

  const label = new Date(value + 'T12:00:00').toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
  })

  const today = new Date()
  const todayStr = toDateStr(today.getFullYear(), today.getMonth(), today.getDate())

  const daysInMonth = viewYear !== null ? getDaysInMonth(viewYear, viewMonth) : 0
  const firstDay = viewYear !== null ? getFirstDayOfWeek(viewYear, viewMonth) : 0

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => shift(-1)}
        className="px-2 py-1 text-sm text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded transition-colors"
      >
        ← <span className="hidden sm:inline">Previous</span>
      </button>

      <div ref={containerRef} className="relative">
        <button
          type="button"
          onClick={openCalendar}
          className="border border-gray-300 rounded-md px-2 py-1 text-sm text-gray-900 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
        >
          {label}
        </button>

        {open && viewYear !== null && (
          <div className="absolute top-full mt-1 right-0 z-50 bg-white border border-gray-200 rounded-lg shadow-lg p-3 w-64">
            <div className="flex items-center justify-between mb-2">
              <button
                type="button"
                onClick={prevMonth}
                className="p-1 rounded hover:bg-gray-100 text-gray-600 hover:text-gray-900 transition-colors"
              >
                <ChevronLeft size={16} />
              </button>
              <span className="text-sm font-medium text-gray-900">
                {MONTHS[viewMonth]} {viewYear}
              </span>
              <button
                type="button"
                onClick={nextMonth}
                className="p-1 rounded hover:bg-gray-100 text-gray-600 hover:text-gray-900 transition-colors"
              >
                <ChevronRight size={16} />
              </button>
            </div>

            <div className="grid grid-cols-7 text-center mb-1">
              {DAYS.map((d) => (
                <div key={d} className="text-xs text-gray-400 py-1">{d}</div>
              ))}
            </div>

            <div className="grid grid-cols-7 text-center">
              {Array.from({ length: firstDay }, (_, i) => (
                <div key={`e${i}`} />
              ))}
              {Array.from({ length: daysInMonth }, (_, i) => {
                const day = i + 1
                const dateStr = toDateStr(viewYear, viewMonth, day)
                const isSelected = dateStr === value
                const isToday = dateStr === todayStr
                return (
                  <button
                    key={day}
                    type="button"
                    onClick={() => selectDay(day)}
                    className={[
                      'w-8 h-8 mx-auto flex items-center justify-center rounded-full text-sm transition-colors',
                      isSelected
                        ? 'bg-blue-600 text-white'
                        : isToday
                          ? 'ring-1 ring-blue-400 text-blue-700 hover:bg-blue-50'
                          : 'text-gray-700 hover:bg-gray-100',
                    ].join(' ')}
                  >
                    {day}
                  </button>
                )
              })}
            </div>

            <div className="mt-2 pt-2 border-t border-gray-100 text-center">
              <button
                type="button"
                onClick={() => { onChange(todayStr); setViewYear(today.getFullYear()); setViewMonth(today.getMonth()); setOpen(false) }}
                className="text-xs text-blue-600 hover:text-blue-800 hover:underline transition-colors"
              >
                Today
              </button>
            </div>
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => shift(1)}
        className="px-2 py-1 text-sm text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded transition-colors"
      >
        <span className="hidden sm:inline">Next</span> →
      </button>
    </div>
  )
}
