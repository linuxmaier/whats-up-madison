# Audit Exceptions and Insights

Patterns that the `/audit-event-accuracy` skill should treat as **not a bug** when scoring a sampled event. Read this file at the start of every audit run, and consult it before deciding to file (or append to) a field-accuracy or source-priority issue. If a sampled event matches an entry below, skip it and note the skip in the run summary so the reason is visible.

Entries grow over time. When the maintainer tells the skill that a flagged finding is intentional, propose adding a new entry here — quote the rule plainly, link to any closed issues that motivated it, and date it so a future reader can judge whether the rationale still applies.

Each entry should include:

- **Rule:** what the skill should not flag.
- **Reason:** why this is intentional, in one or two sentences.
- **Applies to:** the source(s) and field(s) the rule covers.
- **Recorded:** ISO date and (when applicable) the issue numbers that motivated the rule.

## Overall

*(No project-wide exceptions yet. Add entries here when an insight applies across every source — e.g., "don't flag missing image_url if the source page also lacks a hero image.")*

## Per-source

### High Noon Saloon

- **Rule:** Do not flag a `description` mismatch when the High Noon source page has a long artist bio that is absent from the ingested description. It is acceptable for High Noon descriptions to contain only the short "FPC LIVE PRESENTS / with <opener>" heading.
  **Reason:** Artist bios on High Noon event pages are typically several paragraphs of promotional copy. Including them in our card descriptions would clutter the UI without adding much signal. The scraper intentionally captures only the heading block.
  **Applies to:** `High Noon Saloon`, field `description`.
  **Recorded:** 2026-05-13 (motivated by #174, #175, #176).

  Still flag High Noon `description` mismatches that are **not** this pattern — e.g., a description that is truncated mid-sentence, contains raw HTML, is overwritten with boilerplate from another source, or is empty when the source has no artist bio either.

### Atwood Music Hall

*(No exceptions yet.)*

### Ticketmaster

*(No exceptions yet.)*

### Our Lives

*(No exceptions yet.)*

### Isthmus

*(No exceptions yet.)*

### Visit Madison

*(No exceptions yet.)*
