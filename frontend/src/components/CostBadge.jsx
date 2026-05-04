import { getCostIndicator } from '../lib/costIndicator'

export default function CostBadge({ description }) {
  const indicator = getCostIndicator(description)
  if (!indicator) return null

  if (indicator === 'free') {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-100 text-green-700 font-medium leading-none flex-shrink-0">
        Free
      </span>
    )
  }

  return (
    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium leading-none flex-shrink-0">
      $
    </span>
  )
}
