---
name: audit-event-accuracy
description: This skill should be used when the user asks to "audit event accuracy", "spot-check ingest quality", "audit the events database", "check if scrapers got events right", or wants to verify that titles, dates, venues, descriptions, and categories in production match the primary source pages. Samples events across every integrated source, fetches each event's source URL(s), compares fields, evaluates whether SOURCE_PRIORITY ranks the richest sources highest, and files GitHub issues for each finding.
---

# Audit Event Accuracy

Audit production ingest quality for What's Up Madison by sampling events from the live API, fetching their primary-source pages, and comparing what was ingested against what the source actually publishes. File findings as GitHub issues — grouped per root cause so related events pile into one issue rather than fragmenting across many.

The audit has two distinct goals:

1. **Field accuracy.** Verify that title, start/end times, venue name & address, description, categories, and image URL match the highest-priority source page.
2. **Source-priority sanity.** For multi-source events, judge whether `SOURCE_PRIORITY` (defined in `frontend/src/lib/sources.js` and mirrored in `backend/app/ingest.py`) ranks the richest sources first. If a lower-priority source consistently carries better data than the current top source, propose a re-ranking.

All work runs against the **production deployment** at `https://whats-up-madison.fly.dev` — that's the data users see, and the only thing worth auditing.

## Workflow

### 0. Load the exceptions file

Read `audit-exceptions.md` (sibling to this SKILL.md) **before** sampling. It is the running list of patterns the skill should treat as intentional and skip. Keep its contents in mind during the per-event audit — when a sampled event matches an entry, do not file an issue, and note the skip in the per-source summary line (see step 4) so the suppression is visible.

If the file is missing, proceed as if it had no entries.

### 1. Sample events

Run the bundled sampler against production:

```bash
~/miniconda3/envs/whats-up-madison/bin/python .claude/skills/audit-event-accuracy/scripts/sample_events.py --per-source 3
```

(The script is stdlib-only, so any Python 3.10+ works in principle. Use the conda env's interpreter explicitly — `python` is not reliably on `PATH` on the maintainer's machine and the project convention in `CLAUDE.md` is to use the conda env's full path for all project tooling.)

The script fetches `GET /events?date=` for 7 forward dates spread across the next 14 days, deduplicates by event ID, buckets events by their primary source, and emits JSONL on stdout — one line per sampled event. Each record carries `id`, `title`, `start_at`, `end_at`, `all_day`, `venue_name`, `venue_address`, `categories`, the full `sources` array, a 500-char `description_preview`, and a `description_truncated` flag.

Flags:
- `--per-source N` — sample size per source (default 3, ~18 events total).
- `--base-url URL` — override the API base (default `https://whats-up-madison.fly.dev`).
- `--seed S` — deterministic sampling for reproducible runs.

Stderr carries fetch errors (with a `# fetch error:` prefix) and a final `# summary: {...}` line listing how many events were available per source.

### 2. Audit each sampled event

For every JSONL record:

1. **Fetch every source URL on the event** using WebFetch — not just the highest-priority one. Sources that 4xx/5xx or that have no URL are noted in the finding but do not fail the audit.
2. **Build a per-source observation** of the fields visible on each source page: title, calendar date (in `America/Chicago`), start time (when not all-day), venue name & address, description body, source-declared categories or tags, image presence.
3. **Field-accuracy check.** Compare the stored `Event` against the **highest-priority source's page** (per `SOURCE_PRIORITY` — order: High Noon Saloon, Atwood Music Hall, Ticketmaster, Our Lives, Isthmus, Visit Madison). Apply these rules:
   - **Title:** substring match in either direction is acceptable (the source may include "presented by …" decorations).
   - **Date:** calendar day must match in `America/Chicago`.
   - **Start time:** must match within 5 minutes when `all_day` is false.
   - **Venue name & address:** must be the same physical place. Allow alias differences (e.g., "Overture Center for the Arts" vs "Overture Hall") — these are intentional canonicalization, not bugs.
   - **Description:** do not flag for short descriptions (some sources just have little to say). Do flag descriptions that appear truncated mid-sentence, contain raw HTML, or are dominated by boilerplate / cookie banners.
   - **Categories:** LLM-tagged categories should be plausible given the source content; source-supplied taxonomies (Isthmus, Visit Madison, Ticketmaster) should be reflected. Missing the obvious category (e.g., a music concert tagged as nothing) is flag-worthy; debating between two plausible tags is not.
   - **Image:** flag only if the source clearly has a hero image and the ingested event has none.
4. **Source-priority sanity check.** Only relevant for multi-source events. Qualitatively rank each source page by data richness. Weight these dimensions roughly equally (it's a judgment, not a precise score):
   - description length and specificity (2x)
   - structured fields present (explicit start/end times, venue address, ticket info) (2x)
   - accurate venue + address (1x)
   - source-supplied categories or tags (1x)
   - hero image / visual context (1x)
   - **negative:** boilerplate, paywall, ticket-funnel cruft, missing data (1x)

   If a source ranked **lower** in `SOURCE_PRIORITY` looks materially richer than the current top source (clear difference, not a wash), flag it for a priority-ordering review. Borderline calls — skip; only file when the recommendation is clearly correct.

### 3. File findings as GitHub issues

Two finding kinds, two issue templates. Create the label first if needed:

```bash
gh label create accuracy-audit --color BFD4F2 --description "Findings from /audit-event-accuracy" 2>/dev/null || true
```

#### Field-accuracy issues (one per source × field, append events on repeat)

**Group, don't fragment.** Multiple events showing the same `(primary_source, field)` mismatch almost always share a root cause (one scraper bug, one parsing rule). File them as a single issue with each event as an example, the way the source-priority section does — opening one issue per event creates triage noise (see #174/#175/#176).

The dedup query is by title:

```bash
gh issue list --label accuracy-audit --state open --json number,title,body \
  --jq '.[] | select(.title == "Audit: <field> mismatches on <Source> events")'
```

If no open issue exists, create one:

```bash
gh issue create \
  --label accuracy-audit \
  --title "Audit: <field> mismatches on <Source> events" \
  --body "$(cat <<'EOF'
**Kind:** field-accuracy
**Primary source:** <Source Name>
**Field:** <title|start_at|end_at|venue_name|venue_address|description|categories>

**Pattern:** <one line shared across all examples — e.g. "High Noon descriptions contain only the FPC LIVE heading; the artist bio body is dropped.">

**Hypothesis:** <one line — e.g. "Description-selector in `backend/app/scrapers/high_noon.py` stops at the heading block.">

## Example events

### <event title> (<event-id>)
- Source URL: <source_url>
- Other sources: <list, if any>
- Source page shows: <what the source actually says>
- Ingested as: <what's in the DB>
- API: https://whats-up-madison.fly.dev/events?date=<YYYY-MM-DD>

EOF
)"
```

If an open issue already exists for the `(source, field)` pair, **append** the new example block to its body — same API PATCH dance as the source-priority section below. Before appending, scan the existing examples: if the new finding's root cause clearly differs from the documented Pattern (e.g., the open issue is about truncation but the new event has an HTML-escaping bug), open a new issue with a more specific title like `Audit: <field> mismatches on <Source> events — <pattern qualifier>` rather than mixing causes.

When you do append, also check whether the new example adds information. If the existing issue already has three examples illustrating the same pattern, a fourth identical one is noise — skip it and just count it toward the summary's "duplicates skipped".

#### Source-priority issues (one per source pair, append events on repeat)

**Dedup by source-pair, not by event ID.** Many events can share the same priority recommendation — they should pile into one issue. The dedup query is by title:

```bash
gh issue list --label accuracy-audit --state open --json number,title,body \
  --jq '.[] | select(.title == "Audit: review SOURCE_PRIORITY for <higher> vs <lower>")'
```

If no open issue exists, create one:

```bash
gh issue create \
  --label accuracy-audit \
  --title "Audit: review SOURCE_PRIORITY for <higher> vs <lower>" \
  --body "$(cat <<'EOF'
**Kind:** source-priority
**Current ranking:** <higher> is preferred over <lower> per SOURCE_PRIORITY
**Observation:** <lower> consistently provides richer event data than <higher> in the sample below. Consider swapping these in `SOURCE_PRIORITY` (defined in both `frontend/src/lib/sources.js` and `backend/app/ingest.py` — keep them in sync).

## Example events

### <event title> (<event-id>)
- <higher> (<higher-url>): <brief data summary>
- <lower> (<lower-url>): <brief data summary>
- Verdict: <one line on why lower is richer>

EOF
)"
```

If an open issue already exists for the pair, **append** the new example to its body. Use `gh issue view <n> --json body --jq .body` to read, append the new example block, then write back. The CLAUDE.md gotcha says `gh issue edit --body` and `--body-file` may silently fail; fall back to the API:

```bash
gh api repos/<owner>/<name>/issues/<n> --method PATCH --field body="$NEW_BODY"
```

(Use `gh repo view --json nameWithOwner --jq .nameWithOwner` to get owner/name.)

### 4. Print a summary

After processing all sampled events, output one line per source:

```
Isthmus: 3 audited, 1 field-mismatch, 0 priority concerns, 1 issue filed, 0 duplicates skipped, 0 suppressed by audit-exceptions
Visit Madison: 3 audited, 0 field-mismatches, 1 priority concern, 1 issue filed (appended to existing pair issue), 1 suppressed by audit-exceptions
…
```

Make the `suppressed by audit-exceptions` count visible per source so the maintainer can tell when a rule is doing real work (or when a stale rule is hiding a regression).

### 5. Grow `audit-exceptions.md` when prompted

If during this run — or in a later session — the maintainer says a finding is intentional (e.g., "ignore that, it's by design", "we don't want those bios", a closed issue tagged wontfix), **offer** to add an entry to `audit-exceptions.md` and only write it after confirmation. Follow the file's stated entry format: **Rule / Reason / Applies to / Recorded**. Include the originating issue numbers in **Recorded** when there are any, so a future reader can find the context.

When proposing the new entry, draft the **Rule** narrowly so the skill still catches genuine regressions of the same field on the same source — see the existing High Noon entry for the right level of specificity.

## Conventions and gotchas

- `SOURCE_PRIORITY` is mirrored in two places — `frontend/src/lib/sources.js` and `backend/app/ingest.py`. Any priority-related issue body must call this out so whoever fixes it updates both.
- The events API returns `start_at` and `end_at` in UTC; convert to `America/Chicago` before comparing to a source page's "Saturday, May 17" rendering.
- Some sources (Visit Madison, Our Lives) have all-day recurring entries — those don't have a meaningful "time" to verify; skip the start-time comparison when `all_day` is true.
- WebFetch may return partial pages (paywall walls, JS-heavy sites). If a fetch returns an obviously truncated body, note it in the finding but don't speculate about field mismatches from incomplete data.
- Don't open priority issues on a single example. Only file when at least two events in the sample show the same lower-vs-higher disparity, **or** when the disparity is dramatic on a single event (e.g., one source has a full event description and the other returns 404).

## Files

- **`scripts/sample_events.py`** — fetches and emits the JSONL sample. Stdlib only.
- **`audit-exceptions.md`** — running list of intentional, do-not-flag patterns (overall + per-source). Loaded at step 0 of every audit; grown at step 5 when the maintainer confirms a finding is by design.
