import { forwardRef, useCallback, useEffect, useRef } from 'react'

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

// Must match the gradient stops in App.jsx
const STOPS = [
  { t: 0.00, r: 252, g: 228, b: 236 }, // #fce4ec — flamingo pink
  { t: 0.12, r: 227, g: 242, b: 253 }, // #e3f2fd — pale blue
  { t: 0.28, r: 187, g: 222, b: 251 }, // #bbdefb — clear sky
  { t: 0.58, r: 144, g: 164, b: 212 }, // #90a4d4 — periwinkle
  { t: 0.85, r:  40, g:  53, b: 147 }, // #283593 — deep indigo
  { t: 1.00, r:  26, g:  35, b: 126 }, // #1a237e — midnight
]

function sampleRGB(t) {
  t = Math.max(0, Math.min(1, t))
  let lo = STOPS[0], hi = STOPS[STOPS.length - 1]
  for (let i = 0; i < STOPS.length - 1; i++) {
    if (t >= STOPS[i].t && t <= STOPS[i + 1].t) {
      lo = STOPS[i]; hi = STOPS[i + 1]; break
    }
  }
  const f = hi.t === lo.t ? 0 : (t - lo.t) / (hi.t - lo.t)
  return {
    r: Math.round(lo.r + f * (hi.r - lo.r)),
    g: Math.round(lo.g + f * (hi.g - lo.g)),
    b: Math.round(lo.b + f * (hi.b - lo.b)),
  }
}

function toRgbStr({ r, g, b }) { return `rgb(${r},${g},${b})` }

function luminance({ r, g, b }) {
  return 0.2126 * r / 255 + 0.7152 * g / 255 + 0.0722 * b / 255
}

const DensityRail = forwardRef(function DensityRail({ hourCounts, onJumpToHour, stickyTop }, ref) {
  const max = Math.max(1, ...hourCounts)
  const total = hourCounts.reduce((a, b) => a + b, 0)

  const elRef = useRef(null)
  const combinedRef = useCallback((el) => {
    elRef.current = el
    if (typeof ref === 'function') ref(el)
    else if (ref) ref.current = el
  }, [ref])

  useEffect(() => {
    function update() {
      const el = elRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const docH = document.documentElement.scrollHeight
      const tTop = (rect.top + window.scrollY) / docH
      const tBot = (rect.bottom + window.scrollY) / docH
      const colorTop = sampleRGB(tTop)
      const colorMid = sampleRGB((tTop + tBot) / 2)
      el.style.background = `linear-gradient(to bottom, ${toRgbStr(colorTop)}, ${toRgbStr(sampleRGB(tBot))})`
      el.style.color = luminance(colorMid) > 0.35 ? 'rgba(55,65,81,0.85)' : 'rgba(255,255,255,0.7)'
    }
    update()
    window.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update, { passive: true })
    return () => {
      window.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [])

  if (total === 0) return null

  return (
    <div
      ref={combinedRef}
      style={{ top: stickyTop }}
      className="sticky z-20 -mx-4 px-4 pt-2"
    >
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
              className={`flex-1 relative h-full min-w-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand focus-visible:outline-offset-1 ${
                isEmpty ? 'cursor-default' : 'cursor-pointer group'
              }`}
            >
              <div
                className={`absolute bottom-0 left-0 right-0 rounded-t-sm transition-colors ${
                  isEmpty
                    ? 'bg-black/10'
                    : 'bg-accent group-hover:opacity-80'
                }`}
                style={{ height: isEmpty ? '1px' : `${Math.max(6, heightPct)}%` }}
              />
            </button>
          )
        })}
      </div>
      <div className="relative h-3 mt-1 text-[10px]">
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
