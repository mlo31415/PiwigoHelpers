"""
DateUtils.py
Shared date-parsing utilities for Piwigo-connected applications.

Public API
----------
    MONTH_MAP       : dict[str, int]  — month name/abbreviation → month number
    TWO_DIGIT_CUTOFF: int             — yy <= cutoff → 2000s; yy > cutoff → 1900s
    DATE_MIN_YEAR   : int             — earliest accepted 4-digit year
    DATE_MAX_YEAR   : int             — latest accepted year (= 2000 + TWO_DIGIT_CUTOFF)

    expand_year(yy)         → int
    parse_date(text)        → datetime | None
"""

import re
from datetime import datetime

MONTH_MAP: dict[str, int] = {
    'jan': 1, 'january': 1,
    'feb': 2, 'february': 2,
    'mar': 3, 'march': 3,
    'apr': 4, 'april': 4,
    'may': 5,
    'jun': 6, 'june': 6,
    'jul': 7, 'july': 7,
    'aug': 8, 'august': 8,
    'sep': 9, 'sept': 9, 'september': 9,
    'oct': 10, 'october': 10,
    'nov': 11, 'november': 11,
    'dec': 12, 'december': 12,
}

# Two-digit year cutoff: yy <= TWO_DIGIT_CUTOFF → 2000s, yy > cutoff → 1900s.
# e.g. "36" → 1936, "35" → 2035.  2-digit input cannot produce years before 1936.
# DATE_MIN_YEAR is intentionally set earlier (1926) to allow full 4-digit years
# for historical photos pre-dating the 2-digit expansion range.
TWO_DIGIT_CUTOFF: int = 35   # 00–35 → 2000–2035; 36–99 → 1936–1999
DATE_MIN_YEAR:    int = 1926
DATE_MAX_YEAR:    int = 2000 + TWO_DIGIT_CUTOFF  # = 2035


def expand_year(yy: int) -> int:
    """00–35 → 2000+yy; 36–99 → 1900+yy (historical photos)."""
    return (2000 if yy <= TWO_DIGIT_CUTOFF else 1900) + yy


def parse_date(text: str) -> "datetime | None":
    """Parse a user-supplied date string.  Returns a datetime or None.

    Accepted formats (mm/dd both accept 1 or 2 digits; year accepts
    4 digits or 2 digits with century inferred by expand_year):
      mm/dd/yyyy   mm/dd/yy   (dd/mm tried as fallback)
      dd month yyyy           (e.g. 15 Dec 2023)
      month dd, yyyy          (e.g. December 15, 2023)
      mm/yyyy   mm/yy         (day defaults to 1)
      month yyyy              (e.g. Dec 2023 — day defaults to 1)
      yyyy                    (month/day default to 1)
      EXIF: YYYY:MM:DD HH:MM:SS  and  YYYY:MM:DD
      IPTC: YYYYMMDD           (no separators)
    """
    text = re.sub(r'\s+', ' ', text.strip())
    if not text:
        return None

    def yr(s: str) -> int:
        v = int(s)
        return v if len(s) == 4 else expand_year(v)

    def make(year: int, month: int, day: int = 1) -> "datetime | None":
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    # EXIF native: YYYY:MM:DD HH:MM:SS  or  YYYY:MM:DD
    # ISO 8601:   YYYY-MM-DD HH:MM:SS  or  YYYY-MM-DD
    for fmt in ('%Y:%m:%d %H:%M:%S', '%Y:%m:%d',
                '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass

    # IPTC native: YYYYMMDD (no separators)
    m = re.fullmatch(r'(\d{4})(\d{2})(\d{2})', text)
    if m:
        return make(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # mm/dd/yyyy  or  mm-dd-yyyy  (with optional 2-digit year)
    m = re.fullmatch(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4}|\d{2})', text)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), yr(m.group(3))
        return make(y, a, b) or make(y, b, a)  # mm/dd then dd/mm fallback

    # mm/yyyy  or  mm/yy  (month + year, no day)
    m = re.fullmatch(r'(\d{1,2})[/\-](\d{4}|\d{2})', text)
    if m:
        return make(yr(m.group(2)), int(m.group(1)))

    # yyyy alone
    m = re.fullmatch(r'(\d{4})', text)
    if m:
        return make(int(m.group(1)), 1)

    # dd month yyyy  — e.g. "15 December 2023" or "15 Dec 23"
    m = re.fullmatch(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4}|\d{2})', text)
    if m:
        month = MONTH_MAP.get(m.group(2).lower())
        if month:
            return make(yr(m.group(3)), month, int(m.group(1)))

    # month dd, yyyy  — e.g. "December 15, 2023" or "Dec 15 23"
    m = re.fullmatch(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4}|\d{2})', text)
    if m:
        month = MONTH_MAP.get(m.group(1).lower())
        if month:
            return make(yr(m.group(3)), month, int(m.group(2)))

    # month yyyy  — e.g. "December 2023" or "Dec 23"
    m = re.fullmatch(r'([A-Za-z]+)\s+(\d{4}|\d{2})', text)
    if m:
        month = MONTH_MAP.get(m.group(1).lower())
        if month:
            return make(yr(m.group(2)), month)

    return None
