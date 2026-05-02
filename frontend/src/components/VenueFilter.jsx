import { useEffect, useRef, useState } from 'react'

export default function VenueFilter({ allVenues, hiddenVenues, onChange }) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const containerRef = useRef(null)
  const searchRef = useRef(null)

  useEffect(() => {
    if (!open) return
    function handleClick(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    function handleKey(e) {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', handleClick)
    window.addEventListener('keydown', handleKey)
    return () => {
      window.removeEventListener('mousedown', handleClick)
      window.removeEventListener('keydown', handleKey)
    }
  }, [open])

  if (allVenues.length === 0) return null

  function openDropdown() {
    setSearch('')
    setOpen(true)
    setTimeout(() => searchRef.current?.focus(), 0)
  }

  function toggleVenue(v) {
    const next = new Set(hiddenVenues)
    if (next.has(v)) next.delete(v)
    else next.add(v)
    onChange(next)
  }

  function showAll() {
    onChange(new Set())
  }

  function hideAll() {
    onChange(new Set(allVenues))
  }

  const showBadge = hiddenVenues.size > 0
  const visibleVenues = search
    ? allVenues.filter((v) => v.toLowerCase().includes(search.toLowerCase()))
    : allVenues

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => (open ? setOpen(false) : openDropdown())}
        className={`px-2 py-1 text-sm rounded border transition-colors flex items-center gap-1 ${
          showBadge
            ? 'border-blue-500 text-blue-700 bg-blue-50 hover:bg-blue-100'
            : 'border-gray-300 text-gray-700 hover:bg-gray-100'
        }`}
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        <span>Venues</span>
        {showBadge && (
          <span className="text-[10px] px-1 py-0.5 rounded-full bg-blue-600 text-white leading-none">
            {hiddenVenues.size} hidden
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Filter by venue"
          className="absolute right-0 mt-2 w-72 sm:w-80 bg-white border border-gray-200 rounded-lg shadow-lg p-3 z-40"
        >
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">
              Venues
            </p>
            <div className="flex gap-2 text-xs">
              <button
                type="button"
                onClick={showAll}
                className="text-blue-600 hover:underline"
              >
                Show all
              </button>
              <span className="text-gray-300">·</span>
              <button
                type="button"
                onClick={hideAll}
                className="text-blue-600 hover:underline"
              >
                Hide all
              </button>
            </div>
          </div>

          <input
            ref={searchRef}
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search venues…"
            className="w-full mb-2 px-2 py-1 text-xs border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-blue-400"
          />

          <div className="flex flex-col gap-1 max-h-56 overflow-y-auto">
            {visibleVenues.length === 0 && (
              <p className="text-xs text-gray-400 px-1">No venues match.</p>
            )}
            {visibleVenues.map((v) => {
              const hidden = hiddenVenues.has(v)
              return (
                <button
                  key={v}
                  type="button"
                  onClick={() => toggleVenue(v)}
                  className={`text-xs px-2 py-1.5 rounded border text-left transition-colors ${
                    hidden
                      ? 'bg-white border-gray-200 text-gray-400 hover:bg-gray-50'
                      : 'bg-blue-600 border-blue-600 text-white hover:bg-blue-700'
                  }`}
                  aria-pressed={!hidden}
                >
                  {v}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
