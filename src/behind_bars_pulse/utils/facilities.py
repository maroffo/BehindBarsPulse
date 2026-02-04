# ABOUTME: Italian prison facility name normalization.
# ABOUTME: Maps variations to canonical names for deduplication.


# Canonical facility names mapped from common variations
# Format: "Canonical Name (City)" for clarity
FACILITY_ALIASES: dict[str, list[str]] = {
    "Due Palazzi (Padova)": [
        "due palazzi",
        "padova",
        "casa circondariale due palazzi",
        "casa di reclusione due palazzi",
        "casa circondariale di padova",
        "carcere di padova",
    ],
    "Sollicciano (Firenze)": [
        "sollicciano",
        "firenze",
        "casa circondariale di sollicciano",
        "casa circondariale mario gozzini",
        "carcere di firenze",
    ],
    "Canton Mombello (Brescia)": [
        "canton mombello",
        "brescia",
        "brescia canton mombello",
        "brescia - canton mombello",
        "brescia nerio fischione",
        "nerio fischione",
        "casa circondariale di brescia",
        "casa circondariale canton mombello",
        "carcere di brescia",
    ],
    "Cremona": [
        "cremona",
        "casa circondariale di cremona",
        "carcere di cremona",
    ],
    "Rebibbia (Roma)": [
        "rebibbia",
        "casa circondariale di rebibbia",
        "rebibbia nuovo complesso",
        "rebibbia femminile",
        "carcere di rebibbia",
    ],
    "Regina Coeli (Roma)": [
        "regina coeli",
        "casa circondariale regina coeli",
        "carcere regina coeli",
    ],
    "San Vittore (Milano)": [
        "san vittore",
        "casa circondariale di san vittore",
        "carcere di san vittore",
        "milano san vittore",
    ],
    "Poggioreale (Napoli)": [
        "poggioreale",
        "casa circondariale di poggioreale",
        "carcere di poggioreale",
        "napoli poggioreale",
    ],
    "Santa Maria Capua Vetere": [
        "santa maria capua vetere",
        "casa circondariale di santa maria capua vetere",
        "smcv",
        "capua vetere",
    ],
    "Secondigliano (Napoli)": [
        "secondigliano",
        "casa circondariale di secondigliano",
        "carcere di secondigliano",
    ],
    "Asti": [
        "asti",
        "casa circondariale di asti",
        "carcere di asti",
    ],
    "Opera (Milano)": [
        "opera",
        "casa di reclusione di opera",
        "carcere di opera",
        "milano opera",
    ],
    "Bollate (Milano)": [
        "bollate",
        "casa di reclusione di bollate",
        "carcere di bollate",
        "milano bollate",
    ],
}

# Build reverse lookup for fast matching
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for canonical, aliases in FACILITY_ALIASES.items():
    for alias in aliases:
        _ALIAS_TO_CANONICAL[alias.lower()] = canonical


def normalize_facility_name(name: str | None) -> str | None:
    """Normalize a facility name to its canonical form.

    Args:
        name: Raw facility name from article/AI extraction.

    Returns:
        Canonical facility name, or cleaned original if no match found.
        Returns None if input is None.
    """
    if not name:
        return None

    # Clean and lowercase for matching
    cleaned = name.lower().strip()

    # Remove common prefixes for matching
    prefixes_to_strip = [
        "casa circondariale di ",
        "casa circondariale ",
        "casa di reclusione di ",
        "casa di reclusione ",
        "carcere di ",
        "istituto penitenziario di ",
        "istituto penale per minorenni di ",
    ]

    stripped = cleaned
    for prefix in prefixes_to_strip:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
            break

    # Remove quotes and extra spaces
    stripped = stripped.replace("'", "").replace('"', "").strip()

    # Direct match on alias
    if cleaned in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[cleaned]

    # Match on stripped name
    if stripped in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[stripped]

    # Partial match: check if any alias is contained in the name
    for alias, canonical in _ALIAS_TO_CANONICAL.items():
        # Skip very short aliases to avoid false positives
        if len(alias) < 5:
            continue
        if alias in cleaned or alias in stripped:
            return canonical

    # No match found - return cleaned version with consistent capitalization
    # Remove common prefixes and capitalize properly
    result = name.strip()
    for prefix in prefixes_to_strip:
        if result.lower().startswith(prefix):
            result = result[len(prefix) :]
            break

    return result.strip().title() if result else None


def get_facility_region(facility: str | None) -> str | None:
    """Infer region from normalized facility name.

    Args:
        facility: Normalized facility name.

    Returns:
        Italian region name, or None if unknown.
    """
    if not facility:
        return None

    facility_lower = facility.lower()

    # Known mappings
    region_map = {
        "padova": "Veneto",
        "due palazzi": "Veneto",
        "venezia": "Veneto",
        "verona": "Veneto",
        "firenze": "Toscana",
        "sollicciano": "Toscana",
        "prato": "Toscana",
        "milano": "Lombardia",
        "san vittore": "Lombardia",
        "opera": "Lombardia",
        "bollate": "Lombardia",
        "cremona": "Lombardia",
        "brescia": "Lombardia",
        "canton mombello": "Lombardia",
        "roma": "Lazio",
        "rebibbia": "Lazio",
        "regina coeli": "Lazio",
        "napoli": "Campania",
        "poggioreale": "Campania",
        "secondigliano": "Campania",
        "santa maria capua vetere": "Campania",
        "asti": "Piemonte",
        "torino": "Piemonte",
    }

    for keyword, region in region_map.items():
        if keyword in facility_lower:
            return region

    return None
