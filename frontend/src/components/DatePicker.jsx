export default function DatePicker({ value, onChange }) {
  return (
    <div className="flex items-center gap-3">
      <label htmlFor="date-input" className="text-sm font-medium text-gray-700">
        Date
      </label>
      <input
        id="date-input"
        type="date"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="border border-gray-300 rounded-md px-3 py-1.5 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </div>
  )
}
