"""Canonical event category taxonomy.

Closed set of category tags. Events have zero or more categories; tagging is
performed by an LLM pass after ingest (Step 4), constrained to this vocabulary.
The descriptions are intended as guidance for that prompt.

When changing the taxonomy, also update the matching list in
`docs/EVENT_SOURCES.md`.
"""

CATEGORIES: list[str] = [
    "Music",
    "Open Mic & Comedy",
    "Theater & Stage",
    "Visual Art",
    "Dance",
    "Trivia & Games",
    "Food & Drink",
    "Health & Wellness",
    "Outdoors & Nature",
    "Sports & Recreation",
    "Talks & Learning",
    "Civic & Politics",
    "Family & Kids",
    "Community & Clubs",
    "Volunteer & Causes",
]

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "Music": "Live music — concerts, jams, DJ sets, songwriter circles. Excludes open mics.",
    "Open Mic & Comedy": "Open mics (any genre) and stand-up / improv comedy shows.",
    "Theater & Stage": "Plays, staged readings, performance art, and dance performances meant to be watched (not joined).",
    "Visual Art": "Gallery exhibits, museum events, artist talks, studio tours, visual art openings.",
    "Dance": "Social and participatory dance — salsa, tango, contra, swing, ballroom, folk dance practices.",
    "Trivia & Games": "Pub trivia, bingo, board game nights, casual game-based gatherings.",
    "Food & Drink": "Farmers' markets, food festivals, tastings, brewery and restaurant special events.",
    "Health & Wellness": "Yoga, meditation, group fitness, group walks, mental-health gatherings.",
    "Outdoors & Nature": "Birding, hikes, conservation work, park events, gardening.",
    "Sports & Recreation": "Pickup games, recreational leagues, races, fitness meetups, sports-watch parties, organized athletic events.",
    "Talks & Learning": "Lectures, panels, classes, workshops, book clubs, author readings.",
    "Civic & Politics": "Government meetings, town halls, candidate forums, advocacy and political events.",
    "Family & Kids": "Story hours, kid-targeted programming, family-oriented events.",
    "Community & Clubs": "Hobby clubs, social meetups, identity-based gatherings, networking, Toastmasters.",
    "Volunteer & Causes": "Volunteer work days, blood drives, fundraisers, charity events.",
}
