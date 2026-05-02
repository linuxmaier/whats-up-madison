export default function DatePicker({ value, onChange }) {
  function shift(days) {
    const d = new Date(value + 'T12:00:00')
    d.setDate(d.getDate() + days)
    onChange(d.toLocaleDateString('en-CA'))
  }

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => shift(-1)}
        className="px-2 py-1 text-sm text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded transition-colors"
      >
        ← <span className="hidden sm:inline">Yesterday</span>
      </button>
      <input
        id="date-input"
        type="date"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="border border-gray-300 rounded-md px-2 py-1 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      <button
        type="button"
        onClick={() => shift(1)}
        className="px-2 py-1 text-sm text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded transition-colors"
      >
        <span className="hidden sm:inline">Tomorrow</span> →
      </button>
    </div>
  )
}
