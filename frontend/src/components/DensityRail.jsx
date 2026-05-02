import { forwardRef } from 'react'

const HOUR_TICKS = [
  { hour: 5, label: '5a' },
  { hour: 8, label: '8a' },
  { hour: 12, label: '12p' },
  { hour: 15, label: '3p' },
  { hour: 18, label: '6p' },
  { hour: 21, label: '9p' },
  { hour: 1, label: '1a' },
]

const ORDER = [...Array(19).keys()].map((i) => i + 5).concat([0, 1, 2, 3, 4])

const DensityRail = forwardRef(function DensityRail({ hourCounts, onJumpToHour, stickyTop }, ref) {
  const max = Math.max(1, ...hourCounts)
  const total = hourCounts.reduce((a, b) => a + b, 0)
  if (total === 0) return null

  return (
    <div ref={ref} style={{ top: stickyTop }} className="sticky z-20 bg-gray-50 backdrop-blur border-b border-gray-200 -mx-4 px-4 py-2">
      <div className="relative flex gap-px h-12">
        {ORDER.map((h) => {
          const count = hourCounts[h]
          const heightPct = count === 0 ? 0 : (count / max) * 100
          const isEmpty = count === 0
          return (
            <button
              key={h}
              type="button"
              onClick={() => onJumpToHour(h)}
              disabled={isEmpty}
              aria-label={`${count} event${count === 1 ? '' : 's'} starting at ${formatHourLabel(h)}`}
              title={`${formatHourLabel(h)}: ${count} event${count === 1 ? '' : 's'}`}
              className={`flex-1 relative h-full min-w-0 ${
                isEmpty ? 'cursor-default' : 'cursor-pointer group'
              }`}
            >
              <div
                className={`absolute bottom-0 left-0 right-0 rounded-t-sm transition-colors ${
                  isEmpty
                    ? 'bg-gray-200'
                    : 'bg-blue-400 group-hover:bg-blue-500'
                }`}
                style={{ height: isEmpty ? '1px' : `${Math.max(6, heightPct)}%` }}
              />
            </button>
          )
        })}
      </div>
      <div className="relative h-3 mt-1 text-[10px] text-gray-400">
        {HOUR_TICKS.map((tick) => {
          const idx = ORDER.indexOf(tick.hour)
          const leftPct = (idx / ORDER.length) * 100 + 0.5 / ORDER.length * 100
          return (
            <span
              key={tick.hour}
              className="absolute -translate-x-1/2"
              style={{ left: `${leftPct}%` }}
            >
              {tick.label}
            </span>
          )
        })}
      </div>
    </div>
  )
})

export default DensityRail

function formatHourLabel(h) {
  if (h === 0) return '12a'
  if (h === 12) return '12p'
  if (h < 12) return `${h}a`
  return `${h - 12}p`
}
