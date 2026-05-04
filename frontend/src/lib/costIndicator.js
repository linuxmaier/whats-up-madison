export function getCostIndicator(description) {
  if (!description) return null
  if (/\bfree\b/i.test(description)) return 'free'
  if (/\$/.test(description)) return 'paid'
  return null
}
