"""Copy to `private_config.py` (gitignored) and edit. Never commit the copy.

Values here override or extend neutral defaults in the public code.
"""

# Calendar keywords checked BEFORE the public list and before the AI classifier.
# Use this for fixed commitments that would otherwise look like activities
# (e.g. a recurring appointment titled with a person's name). Lower-case,
# whole-word match on the event title. Category must be one of config.CATEGORIES.
EXTRA_KEYWORDS: list[tuple[str, str]] = [
    ("dentist", "ignore"),
]

# Time split: events whose title contains one of these (case-insensitive) are
# markers, not time spent, and are left out of the split.
TIME_EXCLUDE_KEYWORDS: tuple[str, ...] = ("phone off",)

# Lower-case substrings the Weekly Review must never contain (eval tone check).
# The realistic failure is the model labelling mood or diagnosing, not insults.
EVAL_BANNED_WORDS: tuple[str, ...] = ("struggling", "you seem", "it sounds like you", "unmotivated", "lazy")
