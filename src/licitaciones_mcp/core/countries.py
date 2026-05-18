"""Country code helpers used at source and storage boundaries."""

from __future__ import annotations

_ISO3_TO_ISO2 = {
    "AUT": "AT",
    "BEL": "BE",
    "BGR": "BG",
    "CHE": "CH",
    "CYP": "CY",
    "CZE": "CZ",
    "DEU": "DE",
    "DNK": "DK",
    "ESP": "ES",
    "EST": "EE",
    "FIN": "FI",
    "FRA": "FR",
    "GBR": "GB",
    "GRC": "GR",
    "HRV": "HR",
    "HUN": "HU",
    "IRL": "IE",
    "ISL": "IS",
    "ITA": "IT",
    "LIE": "LI",
    "LTU": "LT",
    "LUX": "LU",
    "LVA": "LV",
    "MLT": "MT",
    "NLD": "NL",
    "NOR": "NO",
    "POL": "PL",
    "PRT": "PT",
    "ROU": "RO",
    "SVK": "SK",
    "SVN": "SI",
    "SWE": "SE",
}
_ISO2_TO_ISO3 = {value: key for key, value in _ISO3_TO_ISO2.items()}
_COUNTRY_NAMES = {
    "espana": "ES",
    "españa": "ES",
    "spain": "ES",
    "france": "FR",
    "francia": "FR",
    "germany": "DE",
    "alemania": "DE",
    "italy": "IT",
    "italia": "IT",
    "portugal": "PT",
}


def normalize_country_code(value: str | None) -> str | None:
    """Normalize common country inputs to ISO-2 codes."""

    if value is None:
        return None
    clean = value.strip()
    if not clean:
        return None
    upper = clean.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    if len(upper) == 3 and upper.isalpha() and upper in _ISO3_TO_ISO2:
        return _ISO3_TO_ISO2[upper]
    folded = clean.casefold()
    if folded in _COUNTRY_NAMES:
        return _COUNTRY_NAMES[folded]
    raise ValueError(f"Unsupported country code: {value}")


def ted_country_code(value: str | None) -> str | None:
    """Return the ISO-3 country code expected by TED search."""

    iso2 = normalize_country_code(value)
    if iso2 is None:
        return None
    return _ISO2_TO_ISO3.get(iso2)
