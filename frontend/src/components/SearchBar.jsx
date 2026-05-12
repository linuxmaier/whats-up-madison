import { useEffect, useRef } from 'react'
import { Search, X } from 'lucide-react'

export default function SearchBar({ value, onChange }) {
  const inputRef = useRef(null)

  useEffect(() => {
    if (!value) return
    function handleKey(e) {
      if (e.key === 'Escape' && document.activeElement === inputRef.current) {
        onChange('')
        inputRef.current?.blur()
      }
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [value, onChange])

  return (
    <div className="relative flex items-center">
      <Search
        size={14}
        className="absolute left-2 text-gray-400 pointer-events-none"
        aria-hidden="true"
      />
      <input
        ref={inputRef}
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search events…"
        aria-label="Search events"
        className="border border-gray-300 rounded-md pl-7 pr-7 py-1 text-sm text-gray-900 placeholder-gray-400 w-44 sm:w-56 focus:outline-none focus:ring-2 focus:ring-brand transition-colors"
      />
      {value && (
        <button
          type="button"
          onClick={() => { onChange(''); inputRef.current?.focus() }}
          aria-label="Clear search"
          className="absolute right-1.5 p-0.5 text-gray-400 hover:text-gray-700 cursor-pointer"
        >
          <X size={14} />
        </button>
      )}
    </div>
  )
}
