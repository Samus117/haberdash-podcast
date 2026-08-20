"""Shared helpers for language-code handling.

Open Library (and MARC records generally) use two overlapping code sets for
a handful of major languages: an older "bibliographic" 3-letter code and a
newer "terminology" one (e.g. German is "ger" under MARC/bibliographic but
"deu" under ISO 639-2/T). Which one shows up in a given catalogue record
varies by source and by era, so this module treats each such pair as one
language everywhere in the pipeline rather than let a code mismatch produce
a false "gap" (a book reported as missing from German because the record
said "deu" while our reference table said "ger", or vice versa).
"""

ALIAS_GROUPS = [
    {"ger", "deu"}, {"fre", "fra"}, {"gre", "ell"}, {"chi", "zho"},
    {"per", "fas"}, {"rum", "ron"}, {"arm", "hye"}, {"geo", "kat"},
    {"alb", "sqi"}, {"mac", "mkd"}, {"baq", "eus"}, {"wel", "cym"},
    {"ice", "isl"}, {"bur", "mya"}, {"may", "msa"}, {"slo", "slk"},
    {"tib", "bod"}, {"dut", "nld"}, {"cze", "ces"},
]

_ALIAS_MAP = {}
for _group in ALIAS_GROUPS:
    for _code in _group:
        _ALIAS_MAP[_code] = _group


def equivalent_codes(code):
    """Return the set of 3-letter codes considered the same language as `code`."""
    code = (code or "").strip().lower()
    return _ALIAS_MAP.get(code, {code})


def language_present(code, known_codes):
    """True if `code` (or a known bibliographic/terminology alias of it) is in known_codes."""
    return bool(equivalent_codes(code) & set(known_codes))
