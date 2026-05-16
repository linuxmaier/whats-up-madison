import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Search, Calendar, Building2, MapPin, BarChart3, X } from 'lucide-react'

function IconCircle({ children }) {
  return (
    <span
      className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-white"
      style={{ background: 'var(--c-brand)' }}
    >
      {children}
    </span>
  )
}

// Same path used by CategoryFilter.jsx so the modal entry visually matches
// the actual control in the header.
function CategoryGlyph() {
  return (
    <svg
      className="w-4 h-4"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 4h18M7 8h10M11 12h2M11 16h2" />
    </svg>
  )
}

// Tiny mock of the List|Map segmented control so the entry is recognizable.
function ListMapVisual() {
  return (
    <span
      className="flex-shrink-0 inline-flex border rounded overflow-hidden text-[10px] leading-none"
      style={{ borderColor: 'var(--c-brand)' }}
      aria-hidden="true"
    >
      <span className="px-1.5 py-1 bg-white" style={{ color: 'var(--c-brand)' }}>List</span>
      <span className="px-1.5 py-1 text-white" style={{ background: 'var(--c-brand)' }}>Map</span>
    </span>
  )
}

const FEATURES = [
  {
    visual: <IconCircle><Search size={16} aria-hidden="true" /></IconCircle>,
    title: 'Search',
    body: 'Type in the search bar to find events by title, description, or venue across all upcoming dates.',
  },
  {
    visual: <IconCircle><Calendar size={16} aria-hidden="true" /></IconCircle>,
    title: 'Date picker',
    body: "Pick any date to see what's happening that day. Click What's Up Madison to jump back to today.",
  },
  {
    visual: <IconCircle><CategoryGlyph /></IconCircle>,
    title: 'Category filter',
    body: 'Narrow events by type — music, food, family, etc. Your selection is remembered between visits.',
  },
  {
    visual: <IconCircle><Building2 size={16} aria-hidden="true" /></IconCircle>,
    title: 'Venue filter',
    body: 'Open this to look up a specific venue, or hide venues you’re not interested in.',
  },
  {
    visual: <ListMapVisual />,
    title: 'List / Map toggle',
    body: 'Browse the day as a time-grouped list or as a map of Madison with clustered pins.',
  },
  {
    visual: <IconCircle><MapPin size={16} aria-hidden="true" /></IconCircle>,
    title: 'Map view',
    body: 'Tap a pin to see what events are happening there; events without a location appear below the map.',
  },
  {
    visual: <IconCircle><BarChart3 size={16} aria-hidden="true" /></IconCircle>,
    title: 'Hour chart',
    body: 'The bar under the header shows event counts by hour — click any segment to jump to that time of day.',
  },
]

export default function HelpModal({ open, onClose, onStartTour }) {
  const dialogRef = useRef(null)

  useEffect(() => {
    if (!open) return
    function handleKey(e) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    const previousFocus = document.activeElement
    dialogRef.current?.focus()
    return () => { previousFocus?.focus() }
  }, [open])

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 flex items-center justify-center p-4"
      style={{ zIndex: 10000 }}
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/30" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="help-modal-title"
        tabIndex={-1}
        className="relative bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col focus:outline-none"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-4 flex items-center justify-between border-b border-gray-100">
          <h2 id="help-modal-title" className="text-base font-semibold text-gray-900">
            How to use What&apos;s Up Madison
          </h2>
          <button
            type="button"
            className="text-gray-400 hover:text-gray-600 p-1 rounded cursor-pointer"
            onClick={onClose}
            title="Close"
            aria-label="Close help"
          >
            <X size={14} />
          </button>
        </div>

        <div className="px-5 py-4 overflow-y-auto flex flex-col gap-3">
          <p className="text-sm text-gray-600">
            What&apos;s Up Madison aggregates events from across the city — here&apos;s a quick rundown of the controls.
          </p>
          <ul className="flex flex-col gap-3">
            {FEATURES.map(({ visual, title, body }) => (
              <li key={title} className="flex items-start gap-3">
                <div className="w-14 flex-shrink-0 flex justify-center">{visual}</div>
                <div className="flex flex-col">
                  <span className="text-sm font-medium text-gray-900">{title}</span>
                  <span className="text-sm text-gray-600">{body}</span>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="px-5 py-3 border-t border-gray-100 flex items-center justify-end gap-3">
          <button
            type="button"
            className="text-sm text-gray-500 hover:text-gray-700 cursor-pointer"
            onClick={onClose}
          >
            Close
          </button>
          <button
            type="button"
            className="text-sm text-white px-4 py-2 rounded-lg hover:opacity-90 cursor-pointer"
            style={{ background: 'var(--c-brand)' }}
            onClick={onStartTour}
          >
            Start interactive tour
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}
