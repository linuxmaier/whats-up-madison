const SOURCE_PRIORITY = ['Isthmus', 'Visit Madison']

export function sortedSources(sources) {
  if (!sources) return []
  return [...sources].sort((a, b) => {
    const ai = SOURCE_PRIORITY.indexOf(a.source_name)
    const bi = SOURCE_PRIORITY.indexOf(b.source_name)
    return (ai === -1 ? Infinity : ai) - (bi === -1 ? Infinity : bi)
  })
}

export function isSafeHttpUrl(url) {
  try {
    const u = new URL(url)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
}
