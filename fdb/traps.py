"""Identity tripwires (REBUILD_DESIGN §9). Each is a real case that broke v1.
They run inside the identity build; any failure rolls the build back.

Each trap asserts an EXACT fact about the real world, so a source that starts
getting one of these people wrong is caught the next time it is loaded."""

# (source, source_id, expected gsis_id or None for "must NOT map to", forbidden gsis, why)
ID_TRAPS = [
    ("pff", "10778", "00-0033011", None, "Connor McGovern, C b.1993 (Missouri) - v1 merged two McGoverns"),
    ("pff", "41714", "00-0035679", None, "Connor McGovern, G b.1997 (Penn State)"),
    ("pff", "124393", "00-0039164", None, "Anthony Richardson QB - v1 put his stats on Antonio's slug"),
    ("pff", "9114", "00-0030941", None, "Antonio Richardson OT"),
    ("pff", "83119", "00-0036874", None, "Pat Surtain II - v1 split him across two slugs"),
    ("pff", "358", "00-0015915", None, "Patrick Surtain (father)"),
    ("pff", "3619", "00-0025390", None, "Joe Thomas OT b.1984"),
    ("pff", "9272", "00-0030761", None, "Joe Thomas LB b.1991"),
    ("pff", "26634", "00-0036363", None, "Josh Jones OT - v1 matched the guard onto a safety"),
    ("pff", "11816", "00-0033903", None, "Josh Jones S"),
    ("pff", "2282", "00-0023500", None, "Frank Gore Sr."),
    ("pff", "121457", "00-0039471", None, "Frank Gore Jr. - v1 filed his rows on his father"),
    ("pff", "57337", "00-0036924", None, "Michael Carter RB"),
    ("pff", "60644", "00-0036501", None, "Michael Carter II CB - v1 merged a back's receiving into a CB"),
    ("pff", "7530", "00-0029435", None, "Damaris Johnson - nflverse 2016 weekly roster gives him Dennis Johnson's ids"),
    ("pff", "47124", "00-0034270", None, "Tyler Conklin - weekly rosters flip his pff id between seasons"),
    ("mfl", "12459", None, "00-0031320", "DynastyProcess puts Kevin Smith's gsis on MFL 'Fred Williams'"),
    ("mfl", "12483", None, "00-0022888", "DynastyProcess puts DE Bobby McCray's gsis on punter Jake Schum"),
    ("mfl", "11361", None, "00-0028488", "DynastyProcess puts Mana Silva's gsis on 'Duke Williams'"),
]

# (gsis_id, column, expected, why)
PLAYER_TRAPS = [
    ("00-0031279", "draft_pick_overall", 6, "Jake Matthews: draft_pick is OVERALL (v1 mixed within-round and overall)"),
    ("00-0031279", "draft_year", 2014, "Jake Matthews: v1 had 2012 from a map with no linemen"),
    ("00-0030941", "position", "OT", "Antonio Richardson is a tackle, not a QB"),
]


def check(conn) -> list[str]:
    fails = []
    for src, sid, want, forbid, why in ID_TRAPS:
        row = conn.execute("SELECT gsis_id FROM player_ids WHERE source = ? AND source_id = ?", (src, sid)).fetchone()
        got = row[0] if row else None
        if want and got != want:
            fails.append(f"trap {src}:{sid} -> {got}, expected {want} ({why})")
        if forbid and got == forbid:
            fails.append(f"trap {src}:{sid} maps to forbidden {forbid} ({why})")
    for g, col, want, why in PLAYER_TRAPS:
        row = conn.execute(f"SELECT {col} FROM players WHERE gsis_id = ?", (g,)).fetchone()
        if not row or row[0] != want:
            fails.append(f"trap players[{g}].{col} = {row[0] if row else None}, expected {want} ({why})")
    return fails
