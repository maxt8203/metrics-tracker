"""Labelled event titles that the keyword list doesn't match."""

CASES: list[tuple[str, str]] = [
    ("Board games at Jo's", "social"),
    ("Birthday meal - Lena", "social"),
    ("Coffee catch-up with Priya", "social"),
    ("Pottery class", "hobby"),
    ("Guitar practice", "hobby"),
    ("5k parkrun", "other-sport"),
    ("Swim session", "other-sport"),
    ("Statistics coursework deadline", "study"),
    ("Weekend in Bristol", "trip"),
    ("Train to London", "ignore"),
    ("Car MOT", "ignore"),
    ("Pay council tax", "ignore"),
]
