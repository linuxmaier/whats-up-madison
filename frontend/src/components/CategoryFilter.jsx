import { useEffect, useRef, useState } from 'react'
import {
  CATEGORIES,
  DEFAULT_SELECTED,
  defaultFilterState,
  isDefaultFilterState,
} from '../lib/categories'

export default function CategoryFilter({
  selected,
  includeUncategorized,
  onChange,
}) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)

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

  function toggleCategory(c) {
    const next = new Set(selected)
    if (next.has(c)) next.delete(c)
    else next.add(c)
    onChange({ selected: next, includeUncategorized })
  }

  function setIncludeUncategorized(v) {
    onChange({ selected, includeUncategorized: v })
  }

  function selectAll() {
    onChange({ selected: new Set(CATEGORIES), includeUncategorized: true })
  }

  function clearAll() {
    onChange({ selected: new Set(), includeUncategorized: false })
  }

  function resetDefaults() {
    onChange(defaultFilterState())
  }

  const isDefault = isDefaultFilterState({ selected, includeUncategorized })
  const hiddenCount =
    CATEGORIES.length - selected.size + (includeUncategorized ? 0 : 1)
  const showBadge = !isDefault

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`px-2 py-1 text-sm rounded border transition-colors flex items-center gap-1 ${
          showBadge
            ? 'border-blue-500 text-blue-700 bg-blue-50 hover:bg-blue-100'
            : 'border-gray-400 bg-white text-gray-800 font-medium hover:bg-gray-50'
        }`}
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        <svg
          className="w-3.5 h-3.5 flex-shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 4h18M7 8h10M11 12h2M11 16h2" />
        </svg>
        <span className="hidden sm:inline">Categories</span>
        {showBadge && (
          <span className="text-[10px] px-1 py-0.5 rounded-full bg-blue-600 text-white leading-none">
            {hiddenCount} hidden
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Filter by category"
          className="absolute left-0 sm:left-auto sm:right-0 mt-2 w-80 sm:w-96 bg-white border border-gray-200 rounded-lg shadow-lg p-3 z-40"
        >
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">
              Categories
            </p>
            <div className="flex gap-2 text-xs">
              <button
                type="button"
                onClick={selectAll}
                className="text-blue-600 hover:underline"
              >
                Select all
              </button>
              <span className="text-gray-300">·</span>
              <button
                type="button"
                onClick={clearAll}
                className="text-blue-600 hover:underline"
              >
                Clear
              </button>
              <span className="text-gray-300">·</span>
              <button
                type="button"
                onClick={resetDefaults}
                className="text-blue-600 hover:underline"
              >
                Reset
              </button>
            </div>
          </div>

          <div className="flex flex-wrap gap-1.5 mb-3">
            {CATEGORIES.map((c) => {
              const active = selected.has(c)
              const isDefaultExcluded = !DEFAULT_SELECTED.has(c)
              return (
                <button
                  key={c}
                  type="button"
                  onClick={() => toggleCategory(c)}
                  className={`text-xs px-2 py-1 rounded-full border transition-colors ${
                    active
                      ? 'bg-blue-600 border-blue-600 text-white hover:bg-blue-700'
                      : `bg-white text-gray-600 hover:bg-gray-50 ${
                          isDefaultExcluded
                            ? 'border-dashed border-gray-300'
                            : 'border-gray-300'
                        }`
                  }`}
                  aria-pressed={active}
                  title={
                    isDefaultExcluded && !active
                      ? 'Hidden by default'
                      : undefined
                  }
                >
                  {c}
                </button>
              )
            })}
          </div>

          <label className="flex items-center gap-2 text-sm text-gray-700 pt-2 border-t border-gray-100">
            <input
              type="checkbox"
              checked={includeUncategorized}
              onChange={(e) => setIncludeUncategorized(e.target.checked)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <span>Show uncategorized events</span>
          </label>
          <p className="text-[11px] text-gray-400 mt-1 pl-6">
            Many events aren't tagged yet. Hide them once tagging is more
            complete.
          </p>
        </div>
      )}
    </div>
  )
}
