"""Name comparison as a NEGATIVE signal only (REBUILD_DESIGN §3.2).

`name_disagrees` answers exactly one question: do two names clearly belong to
different people? It never selects a candidate. A name that passes proves
nothing; a name that fails is grounds to refuse a mapping.

Rule: same surname AND same first initial, over every name form nflverse gives
(display, first/last, common first, football name). Normalisation folds
accents, punctuation, hyphens, Jr/Sr/II/III/IV/V and Saint->St, because v1
duplicated a player over "John Saint Clair" vs "John St. Clair".
"""
import re
import unicodedata

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def tokens(name: str | None) -> list[str]:
    if not name:
        return []
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'`’\-]", "", s)          # D.J. -> dj, O'Neil -> oneil, Bako-Bewele -> bakobewele
    out = [t for t in re.split(r"[\s,]+", s) if t and t not in SUFFIXES]
    return ["st" if t == "saint" else t for t in out]


def _surname_ok(cand: list[str], last_name: str | None) -> bool:
    last = "".join(tokens(last_name))
    if not last:
        return True  # nothing to compare against: cannot disagree
    # A hyphenated surname may be recorded by one part ("Robey" for "Robey-Coleman").
    parts = {last} | {"".join(tokens(p)) for p in re.split(r"-", last_name or "") if p.strip()}
    return any("".join(cand[-k:]) in parts for k in range(1, len(cand)))


def name_disagrees(candidate: str, person: dict) -> bool:
    """person: a players row (display_name, first_name, last_name, and optionally
    common_first_name / football_name)."""
    cand = tokens(candidate)
    if len(cand) < 2:
        return False  # a one-word name cannot be checked, so it cannot be rejected
    lasts = {person.get("last_name")} | {" ".join(tokens(person.get("display_name"))[1:])}
    if not any(_surname_ok(cand, l) for l in lasts if l):
        return True
    initials = {t[0] for key in ("first_name", "common_first_name", "football_name", "display_name")
                for t in tokens(person.get(key))[:1]}
    return bool(initials) and cand[0][0] not in initials


def surname_agrees(candidate: str, person: dict) -> bool:
    cand = tokens(candidate)
    if len(cand) < 2:
        return True
    lasts = {person.get("last_name")} | {" ".join(tokens(person.get("display_name"))[1:])}
    return any(_surname_ok(cand, l) for l in lasts if l)
