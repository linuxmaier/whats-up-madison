// Mirror of `backend/app/categories.py`. Keep the two in sync when the
// taxonomy changes.

export const CATEGORIES = [
  'Music',
  'Open Mic & Comedy',
  'Theater & Stage',
  'Visual Art',
  'Dance',
  'Trivia & Games',
  'Food & Drink',
  'Health & Wellness',
  'Outdoors & Nature',
  'Sports & Recreation',
  'Talks & Learning',
  'Civic & Politics',
  'Family & Kids',
  'Community & Clubs',
  'Volunteer & Causes',
]

export const DEFAULT_EXCLUDED = new Set([
  'Volunteer & Causes',
  'Civic & Politics',
  'Community & Clubs',
])

export const DEFAULT_SELECTED = new Set(
  CATEGORIES.filter((c) => !DEFAULT_EXCLUDED.has(c)),
)

const STORAGE_KEY = 'wum.categoryFilter.v1'

export function loadFilterState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return defaultFilterState()
    const parsed = JSON.parse(raw)
    const selected = new Set(
      (parsed.selected || []).filter((c) => CATEGORIES.includes(c)),
    )
    const includeUncategorized = parsed.includeUncategorized !== false
    return { selected, includeUncategorized }
  } catch {
    return defaultFilterState()
  }
}

export function saveFilterState({ selected, includeUncategorized }) {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        selected: [...selected],
        includeUncategorized,
      }),
    )
  } catch {
    // Ignore storage errors (private mode, quota, etc.)
  }
}

export function defaultFilterState() {
  return {
    selected: new Set(DEFAULT_SELECTED),
    includeUncategorized: true,
  }
}

export function isDefaultFilterState({ selected, includeUncategorized }) {
  if (!includeUncategorized) return false
  if (selected.size !== DEFAULT_SELECTED.size) return false
  for (const c of DEFAULT_SELECTED) {
    if (!selected.has(c)) return false
  }
  return true
}

export function filterEvents(events, { selected, includeUncategorized }) {
  return events.filter((e) => {
    if (!e.categories || e.categories.length === 0) {
      return includeUncategorized
    }
    return e.categories.some((c) => selected.has(c))
  })
}
