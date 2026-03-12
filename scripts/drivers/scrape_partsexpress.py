#!/usr/bin/env python3
"""
Parts-express.com speaker driver scraper.

Extracts T/S parameters and specifications from parts-express.com product
pages and outputs conforming driver YAML files for the speaker driver database.

Usage examples:
    # Scrape woofers category, limit to 3 drivers
    python scrape_partsexpress.py --type woofer --limit 3

    # Scrape a specific category URL
    python scrape_partsexpress.py --category-url "https://www.parts-express.com/speaker-components/hi-fi-woofers-subwoofers-midranges-tweeters/woofers" --limit 5

    # Scrape with custom delay and output directory
    python scrape_partsexpress.py --type subwoofer --delay 3 --output-dir /tmp/drivers --limit 10

Dependencies: requests, beautifulsoup4, PyYAML (+ stdlib)
"""

import argparse
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.robotparser

import requests
import yaml
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.parts-express.com"
USER_AGENT = (
    "pi4-audio-workstation-scraper/1.0 "
    "(+https://github.com/gabriela-bogk/pi4-audio-workstation; "
    "speaker driver database; respectful crawling)"
)
DEFAULT_DELAY = 2.0  # seconds between requests
DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "configs",
    "drivers",
)

# Category URL patterns for driver types.
# The old /cat/<name>/<id> URLs redirect to these new paths.
CATEGORY_URLS = {
    "woofer": "/speaker-components/hi-fi-woofers-subwoofers-midranges-tweeters/woofers",
    "midrange": "/speaker-components/hi-fi-woofers-subwoofers-midranges-tweeters/midranges",
    "tweeter": "/speaker-components/hi-fi-woofers-subwoofers-midranges-tweeters/tweeters",
    "subwoofer": "/speaker-components/hi-fi-woofers-subwoofers-midranges-tweeters/subwoofers",
    "full-range": "/speaker-components/hi-fi-woofers-subwoofers-midranges-tweeters/full-range-speakers",
}

# Maps parts-express spec table labels to (schema_field, section, unit_converter).
# section is "thiele_small", "metadata", "metadata.mounting", or None (skip).
# unit_converter is a callable or None (use raw parsed float).

_INCHES_TO_MM = 25.4
_FT3_TO_LITERS = 28.3168466
_LBS_TO_KG = 0.45359237


def _parse_float(text):
    """Extract a float from text, stripping units and symbols."""
    if text is None:
        return None
    # Remove common unit suffixes, symbols, HTML entities
    cleaned = text.strip()
    cleaned = re.sub(r"[Ωω°]", "", cleaned)
    cleaned = re.sub(r"\s*(Hz|mH|mm|cm[²2]|g|T[·.]m|ft[³3]|mm/N|dB|Watts?|lbs?|kg|in|"
                     r"W|ohm|Ohm|liters?).*$", "", cleaned, flags=re.I)
    cleaned = cleaned.replace(",", "").strip()
    # Handle fractions like "1/2" in "6-1/2" (already in the slug, not usually in values)
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_sensitivity(text):
    """Parse sensitivity string like '86.8dB 2.83V/1m' -> float."""
    if text is None:
        return None
    match = re.search(r"([\d.]+)\s*dB", text)
    if match:
        return float(match.group(1))
    return None


def _convert_inches_to_mm(val):
    """Convert inches to mm."""
    return round(val * _INCHES_TO_MM, 2) if val is not None else None


def _convert_ft3_to_liters(val):
    """Convert cubic feet to liters."""
    return round(val * _FT3_TO_LITERS, 2) if val is not None else None


def _convert_mm_per_n_to_m_per_n(val):
    """Convert mm/N to m/N."""
    return round(val / 1000.0, 6) if val is not None else None


def _convert_lbs_to_kg(val):
    """Convert pounds to kg."""
    return round(val * _LBS_TO_KG, 2) if val is not None else None


# Cone material mapping: parts-express value -> schema enum value.
# Per AE review: do NOT map treated/composite variants that differ materially.
# Unmapped values are set to null and the raw string is preserved in notes.
CONE_MATERIAL_MAP = {
    "aluminum": "aluminum",
    "paper": "paper",
    "polypropylene": "polypropylene",
    "poly": "polypropylene",
    "kevlar": "kevlar",
    "carbon fiber": "carbon-fiber",
}

SURROUND_MATERIAL_MAP = {
    "rubber": "rubber",
    "butyl rubber": "rubber",
    "nbr": "rubber",
    "foam": "foam",
    "cloth": "cloth",
}

MAGNET_MATERIAL_MAP = {
    "ferrite": "ferrite",
    "ceramic": "ferrite",
    "neodymium": "neodymium",
    "alnico": "alnico",
}

# Approximate weight ranges by nominal diameter (inches) for sanity checking.
# Values outside these ranges trigger a warning but are still imported.
WEIGHT_KG_RANGES = {
    (0, 4):   (0.1, 1.0),
    (4, 6):   (0.3, 1.5),
    (6, 9):   (1.0, 4.0),
    (9, 13):  (3.0, 8.0),
    (13, 20): (5.0, 15.0),
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scrape_partsexpress")

# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------


def _create_session():
    """Create a requests session with appropriate headers."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    return session


def _check_robots_txt(session):
    """Parse robots.txt and return a RobotFileParser. Logs warnings on failure."""
    rp = urllib.robotparser.RobotFileParser()
    robots_url = BASE_URL + "/robots.txt"
    try:
        resp = session.get(robots_url, timeout=10)
        resp.raise_for_status()
        rp.parse(resp.text.splitlines())
        log.info("Parsed robots.txt from %s", robots_url)
    except Exception as exc:
        log.warning("Failed to fetch robots.txt: %s — proceeding cautiously", exc)
        # Return a permissive parser on failure
        rp.parse([])
    return rp


def _fetch_page(session, url, delay, robots_parser):
    """Fetch a URL, respecting delay and robots.txt. Returns response or None."""
    if not robots_parser.can_fetch(USER_AGENT, url):
        # Also check with wildcard agent
        if not robots_parser.can_fetch("*", url):
            log.warning("Blocked by robots.txt: %s", url)
            return None
    time.sleep(delay)
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        log.error("Failed to fetch %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Category page scraping
# ---------------------------------------------------------------------------


def discover_product_urls(session, category_url, delay, robots_parser, limit=None):
    """
    Crawl a category listing page (with pagination) and return product URLs.

    Product URLs match the pattern: /<Brand-Model-Name-PartNumber>
    where PartNumber is digits like 295-356.
    """
    product_urls = []
    page = 1
    seen = set()

    while True:
        if page == 1:
            url = category_url
        else:
            sep = "&" if "?" in category_url else "?"
            url = f"{category_url}{sep}page={page}"

        # Ensure full URL
        if not url.startswith("http"):
            url = BASE_URL + url

        log.info("Fetching category page %d: %s", page, url)
        resp = _fetch_page(session, url, delay, robots_parser)
        if resp is None:
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        # Find product links: pattern is href="/Brand-Model-Name-NNN-NNN"
        # where the last segment is a part number like 295-356
        found_on_page = 0
        for link in soup.find_all("a", href=True):
            href = link["href"]
            # Match product URL pattern: starts with /, contains text, ends with digits
            if re.match(r"^/[A-Z].*-\d{3,}-\d{3,}$", href):
                full_url = BASE_URL + href
                if full_url not in seen:
                    seen.add(full_url)
                    product_urls.append(full_url)
                    found_on_page += 1

                    if limit and len(product_urls) >= limit:
                        log.info(
                            "Reached limit of %d products", limit
                        )
                        return product_urls

        log.info(
            "Found %d new products on page %d (total: %d)",
            found_on_page, page, len(product_urls),
        )

        if found_on_page == 0:
            break

        # Check for next page link
        next_link = soup.find("link", rel="next")
        if next_link is None:
            # Also check for pagination links
            has_next = any(
                re.search(r"[?&]page=" + str(page + 1), a.get("href", ""))
                for a in soup.find_all("a", href=True)
            )
            if not has_next:
                break

        page += 1

    return product_urls


# ---------------------------------------------------------------------------
# Product page parsing
# ---------------------------------------------------------------------------


def _parse_spec_tables(soup):
    """
    Parse all specification tables from a product page.

    Returns a dict mapping table header (e.g., "Thiele-Small Parameters")
    to a dict of {label: raw_value_text}.
    """
    tables = {}
    for table in soup.find_all("table", class_="product-information-specifications-table"):
        header_el = table.find("h4")
        header = header_el.get_text(strip=True) if header_el else "Unknown"
        rows = {}
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) == 2:
                label = cells[0].get_text(strip=True)
                value = cells[1].get_text(strip=True)
                rows[label] = value
        tables[header] = rows
    return tables


def _extract_json_ld(soup):
    """Extract JSON-LD product data if available."""
    import json
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get("@type") == "Product":
                return data
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _map_material(raw_value, mapping, field_name):
    """Map a raw material string to a schema enum value using the given mapping.

    Returns (enum_value_or_None, raw_value). The raw value is always returned
    so callers can preserve it in notes when the mapping yields None.
    """
    if raw_value is None:
        return None, None
    key = raw_value.lower().strip()
    if key in mapping:
        return mapping[key], raw_value
    # No match — log for auditability
    log.info("Unmapped %s value: %r (set to null, raw preserved)", field_name, raw_value)
    return None, raw_value


def _parse_nominal_diameter(raw_value):
    """Parse nominal diameter like '8\"' or '6-1/2\"' -> float inches."""
    if raw_value is None:
        return None
    cleaned = raw_value.replace('"', "").replace("'", "").strip()
    # Handle fractions like "6-1/2"
    match = re.match(r"(\d+)-(\d+)/(\d+)", cleaned)
    if match:
        whole = int(match.group(1))
        num = int(match.group(2))
        denom = int(match.group(3))
        return whole + num / denom
    return _parse_float(cleaned)


def _make_driver_id(manufacturer, model):
    """Create a filesystem-safe driver ID from manufacturer and model."""
    combined = f"{manufacturer}-{model}"
    # Lowercase, replace spaces and special chars with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", combined.lower())
    slug = slug.strip("-")
    # Collapse multiple hyphens
    slug = re.sub(r"-+", "-", slug)
    return slug


def _determine_driver_type(product_url, category_type=None):
    """Determine the driver type from the URL or category context."""
    if category_type:
        return category_type

    url_lower = product_url.lower()
    if "subwoofer" in url_lower or "sub" in url_lower:
        return "subwoofer"
    if "tweeter" in url_lower:
        return "tweeter"
    if "midrange" in url_lower:
        return "midrange"
    if "full-range" in url_lower:
        return "full-range"
    if "woofer" in url_lower:
        return "woofer"
    return None


def _parse_vas(raw_value):
    """Parse Vas value that may be in ft^3 or liters. Returns (liters, unit_note).

    unit_note describes how the unit was determined, for auditability.
    """
    if raw_value is None:
        return None, None

    text = raw_value.strip()
    has_ft3 = bool(re.search(r"ft[³3\^]?", text, re.I))
    has_liters = bool(re.search(r"liter", text, re.I))

    val = _parse_float(text)
    if val is None:
        return None, None

    if has_ft3 and has_liters:
        # Both units present — prefer liters value, but this is unusual.
        # The _parse_float will have grabbed the first number; log a warning.
        log.warning("Vas has both ft^3 and liters in %r — using parsed value as liters", raw_value)
        return val, "ambiguous-both-units-present"

    if has_liters:
        return val, "explicit-liters"

    if has_ft3:
        return _convert_ft3_to_liters(val), "explicit-ft3"

    # No explicit unit — assume ft^3 (PE is a US retailer) but log the assumption
    log.info("Vas unit not explicit in %r — assuming ft^3 (US convention)", raw_value)
    return _convert_ft3_to_liters(val), "assumed-ft3"


def _check_weight_sanity(weight_kg, nominal_diameter_in):
    """Warn if weight seems unreasonable for the driver size. Returns weight_kg unchanged."""
    if weight_kg is None or nominal_diameter_in is None:
        return weight_kg
    for (lo, hi), (wt_lo, wt_hi) in WEIGHT_KG_RANGES.items():
        if lo <= nominal_diameter_in < hi:
            if weight_kg < wt_lo or weight_kg > wt_hi:
                log.warning(
                    "Weight %.2f kg seems unusual for a %.1f\" driver "
                    "(expected %.1f-%.1f kg) — verify manually",
                    weight_kg, nominal_diameter_in, wt_lo, wt_hi,
                )
            return weight_kg
    return weight_kg


def _parse_impedance(raw_value):
    """Parse impedance like '8Ω' or '8 Ohm' -> int."""
    if raw_value is None:
        return None
    val = _parse_float(raw_value)
    if val is not None:
        # Nominal impedance is always a standard value
        return int(round(val))
    return None


def parse_product_page(soup, product_url, category_type=None):
    """
    Parse a product page and return a driver data dict conforming to the schema.

    Returns None if the page lacks T/S parameters (not a driver component page).
    """
    tables = _parse_spec_tables(soup)
    json_ld = _extract_json_ld(soup)

    # Extract data from each table section
    details = tables.get("Product Details", {})
    specs = tables.get("Product Specifications", {})
    ts_params = tables.get("Thiele-Small Parameters", {})
    materials = tables.get("Materials of Construction", {})
    mounting = tables.get("Mounting Information", {})

    # We need at least the Thiele-Small Parameters table to proceed
    if not ts_params:
        log.info("No T/S parameters found on %s — skipping", product_url)
        return None

    # Extract manufacturer and model
    manufacturer = details.get("Brand", "")
    model = details.get("Model", "")

    if not manufacturer and json_ld:
        brand = json_ld.get("brand", {})
        if isinstance(brand, dict):
            manufacturer = brand.get("name", "")

    if not model and json_ld:
        model = json_ld.get("mpn", "")

    if not manufacturer or not model:
        log.warning("Missing manufacturer/model on %s", product_url)
        return None

    driver_id = _make_driver_id(manufacturer, model)

    # Parse T/S parameters
    fs_hz = _parse_float(ts_params.get("Resonant Frequency (Fs)"))
    re_ohm = _parse_float(ts_params.get("DC Resistance (Re)"))
    le_mh = _parse_float(ts_params.get("Voice Coil Inductance (Le)"))
    qms = _parse_float(ts_params.get("Mechanical Q (Qms)"))
    qes = _parse_float(ts_params.get("Electromagnetic Q (Qes)"))
    qts = _parse_float(ts_params.get("Total Q (Qts)"))
    vas_raw = ts_params.get("Compliance Equivalent Volume (Vas)")
    vas_liters, vas_unit_note = _parse_vas(vas_raw)
    cms_raw = _parse_float(ts_params.get("Mechanical Compliance of Suspension (Cms)"))
    cms_m_per_n = _convert_mm_per_n_to_m_per_n(cms_raw)
    bl_tm = _parse_float(ts_params.get("BL Product (BL)"))
    mms_g = _parse_float(ts_params.get("Diaphragm Mass Inc. Airload (Mms)"))
    xmax_mm = _parse_float(ts_params.get("Maximum Linear Excursion (Xmax)"))
    sd_cm2 = _parse_float(ts_params.get("Surface Area of Cone (Sd)"))

    # Also check for "Diaphragm Mass Excl. Airload (Mmd)" if available
    mmd_g = _parse_float(ts_params.get("Diaphragm Mass Excl. Airload (Mmd)"))

    # Check for efficiency
    eta0_raw = ts_params.get("Reference Efficiency (η0)")
    eta0_percent = _parse_float(eta0_raw)

    # Check for Vd
    vd_raw = ts_params.get("Maximum Volume Displacement (Vd)")
    vd_cm3 = _parse_float(vd_raw)

    # Parse product specifications
    z_nom_ohm = _parse_impedance(specs.get("Impedance"))
    sensitivity_text = specs.get("Sensitivity")
    sensitivity_db_2v83_1m = _parse_sensitivity(sensitivity_text)
    nominal_diameter_raw = specs.get("Nominal Diameter")
    nominal_diameter_in = _parse_nominal_diameter(nominal_diameter_raw)
    vc_diameter_raw = specs.get("Voice Coil Diameter")
    vc_diameter_in = _parse_nominal_diameter(vc_diameter_raw)
    voice_coil_diameter_mm = _convert_inches_to_mm(vc_diameter_in)

    # Power handling
    pe_max_raw = specs.get("Power Handling (RMS)")
    pe_max_watts = _parse_float(pe_max_raw)
    pe_peak_raw = specs.get("Power Handling (MAX)")
    pe_peak_watts = _parse_float(pe_peak_raw)

    # Bolt circle diameter from product specs (inches, unitless)
    bolt_circle_raw = specs.get("Bolt Circle Diameter")
    bolt_circle_in = _parse_float(bolt_circle_raw)
    bolt_circle_diameter_mm = _convert_inches_to_mm(bolt_circle_in)

    # Weight from product details (parts-express uses lbs for US site)
    weight_raw = details.get("Weight")
    weight_val = _parse_float(weight_raw)
    weight_kg = _convert_lbs_to_kg(weight_val)

    # Materials (map to schema enum; preserve raw values for unmapped materials)
    cone_material, cone_raw = _map_material(
        materials.get("Cone Material"), CONE_MATERIAL_MAP, "cone_material")
    surround_material, surround_raw = _map_material(
        materials.get("Surround Material"), SURROUND_MATERIAL_MAP, "surround_material")
    magnet_material, magnet_raw = _map_material(
        materials.get("Magnet Material"), MAGNET_MATERIAL_MAP, "magnet_material")

    # Mounting information (all in inches, convert to mm)
    flange_raw = mounting.get("Overall Outside Diameter")
    flange_in = _parse_nominal_diameter(flange_raw)
    flange_diameter_mm = _convert_inches_to_mm(flange_in)

    cutout_raw = mounting.get("Baffle Cutout Diameter")
    cutout_in = _parse_nominal_diameter(cutout_raw)
    cutout_diameter_mm = _convert_inches_to_mm(cutout_in)

    depth_raw = mounting.get("Depth")
    depth_in = _parse_nominal_diameter(depth_raw)
    overall_depth_mm = _convert_inches_to_mm(depth_in)

    bolt_count_raw = mounting.get("# Mounting Holes")
    bolt_count = None
    if bolt_count_raw:
        try:
            bolt_count = int(_parse_float(bolt_count_raw))
        except (TypeError, ValueError):
            pass

    # Weight sanity check
    weight_kg = _check_weight_sanity(weight_kg, nominal_diameter_in)

    # Determine driver type
    driver_type = _determine_driver_type(product_url, category_type)

    # Required T/S fields check: if we're missing all 4 required fields, skip
    if fs_hz is None and re_ohm is None and z_nom_ohm is None and qts is None:
        log.warning("All required T/S fields are null for %s — skipping", product_url)
        return None

    # Build notes with raw material values preserved for unmapped fields
    note_parts = [f"Scraped from parts-express.com. Part number: {details.get('Part Number', 'unknown')}."]
    unmapped = []
    if cone_material is None and cone_raw:
        unmapped.append(f"cone={cone_raw}")
    if surround_material is None and surround_raw:
        unmapped.append(f"surround={surround_raw}")
    if magnet_material is None and magnet_raw:
        unmapped.append(f"magnet={magnet_raw}")
    if unmapped:
        note_parts.append(f"Unmapped materials (raw): {', '.join(unmapped)}.")
    if vas_unit_note and vas_unit_note.startswith("assumed"):
        note_parts.append(f"Vas unit {vas_unit_note} (raw: {vas_raw!r}).")
    notes_text = " ".join(note_parts)

    # Build the driver data dict
    driver_data = {
        "schema_version": 1,
        "metadata": {
            "id": driver_id,
            "manufacturer": manufacturer,
            "model": model,
            "driver_type": driver_type,
            "nominal_diameter_in": nominal_diameter_in,
            "actual_diameter_mm": None,
            "magnet_type": magnet_material,
            "cone_material": cone_material,
            "surround_material": surround_material,
            "voice_coil_diameter_mm": voice_coil_diameter_mm,
            "weight_kg": weight_kg,
            "mounting": {
                "cutout_diameter_mm": cutout_diameter_mm,
                "bolt_circle_diameter_mm": bolt_circle_diameter_mm,
                "bolt_count": bolt_count,
                "overall_depth_mm": overall_depth_mm,
                "flange_diameter_mm": flange_diameter_mm,
            },
            "datasheet_url": product_url,
            "datasheet_file": None,
            "ts_parameter_source": "manufacturer",
            "ts_measurement_date": None,
            "ts_measurement_notes": "",
            "notes": notes_text,
            "quantity_owned": None,
            "serial_numbers": [],
            "purchase_date": None,
            "condition": None,
        },
        "thiele_small": {
            "fs_hz": fs_hz,
            "re_ohm": re_ohm,
            "z_nom_ohm": z_nom_ohm,
            "qts": qts,
            "qes": qes,
            "qms": qms,
            "vas_liters": vas_liters,
            "cms_m_per_n": cms_m_per_n,
            "xmax_mm": xmax_mm,
            "xmech_mm": None,
            "le_mh": le_mh,
            "bl_tm": bl_tm,
            "mms_g": mms_g,
            "mmd_g": mmd_g,
            "sd_cm2": sd_cm2,
            "sensitivity_db_1w1m": None,
            "sensitivity_db_2v83_1m": sensitivity_db_2v83_1m,
            "pe_max_watts": pe_max_watts,
            "pe_peak_watts": pe_peak_watts,
            "power_handling_note": "",
            "eta0_percent": eta0_percent,
            "vd_cm3": vd_cm3,
        },
        "measurements": {
            "impedance_curve": {
                "source": None,
                "date": None,
                "conditions": "",
                "data_file": None,
            },
            "frequency_response": {
                "source": None,
                "date": None,
                "conditions": "",
                "reference_distance_m": None,
                "data_file": None,
            },
            "nearfield_response": {
                "source": None,
                "date": None,
                "data_file": None,
            },
            "distortion": {
                "data_file": None,
                "test_level_db_spl": None,
            },
        },
        "application_notes": [],
    }

    return driver_data


def find_datasheet_urls(soup):
    """Find datasheet PDF and tech doc URLs on a product page."""
    urls = {"spec_pdf": None, "tech_docs": None}
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "pedocs/specs" in href and href.endswith(".pdf"):
            urls["spec_pdf"] = href
        elif "pedocs/tech-docs" in href:
            urls["tech_docs"] = href
    return urls


# ---------------------------------------------------------------------------
# File download
# ---------------------------------------------------------------------------


def download_file(session, url, dest_path, delay, robots_parser):
    """Download a file to dest_path. Returns True on success."""
    if os.path.exists(dest_path):
        log.info("File already exists, skipping download: %s", dest_path)
        return True

    resp = _fetch_page(session, url, delay, robots_parser)
    if resp is None:
        return False

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        log.info("Downloaded: %s -> %s", url, dest_path)
        return True
    except OSError as exc:
        log.error("Failed to write %s: %s", dest_path, exc)
        return False


# ---------------------------------------------------------------------------
# YAML output
# ---------------------------------------------------------------------------


class _LiteralStr(str):
    """String subclass that forces YAML literal block style."""


def _literal_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(_LiteralStr, _literal_representer)


def _none_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:null", "null")


yaml.add_representer(type(None), _none_representer)


def write_driver_yaml(driver_data, output_dir):
    """
    Write a driver YAML file to output_dir/<driver_id>/driver.yml.

    Idempotent: overwrites existing file for the same driver_id.
    """
    driver_id = driver_data["metadata"]["id"]
    driver_dir = os.path.join(output_dir, driver_id)
    os.makedirs(driver_dir, exist_ok=True)

    yaml_path = os.path.join(driver_dir, "driver.yml")
    log.info("Writing %s", yaml_path)

    with open(yaml_path, "w") as f:
        yaml.dump(
            driver_data,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )

    return yaml_path


# ---------------------------------------------------------------------------
# Main scraping logic
# ---------------------------------------------------------------------------


def scrape_driver(session, product_url, output_dir, delay, robots_parser,
                  category_type=None):
    """
    Scrape a single driver product page and write its YAML file.

    Returns (driver_id, yaml_path) on success, or (None, error_msg) on failure.
    """
    log.info("Scraping product: %s", product_url)
    resp = _fetch_page(session, product_url, delay, robots_parser)
    if resp is None:
        return None, f"Failed to fetch {product_url}"

    soup = BeautifulSoup(resp.text, "html.parser")
    driver_data = parse_product_page(soup, product_url, category_type)
    if driver_data is None:
        return None, f"No valid driver data on {product_url}"

    driver_id = driver_data["metadata"]["id"]

    # Download datasheet PDFs and tech docs
    datasheet_urls = find_datasheet_urls(soup)
    data_dir = os.path.join(output_dir, driver_id, "data")

    if datasheet_urls["spec_pdf"]:
        pdf_url = datasheet_urls["spec_pdf"]
        pdf_filename = os.path.basename(urllib.parse.urlparse(pdf_url).path)
        pdf_path = os.path.join(data_dir, pdf_filename)
        if download_file(session, pdf_url, pdf_path, delay, robots_parser):
            driver_data["metadata"]["datasheet_file"] = f"data/{pdf_filename}"

    # Write YAML
    yaml_path = write_driver_yaml(driver_data, output_dir)
    return driver_id, yaml_path


def scrape_category(session, category_url, output_dir, delay, robots_parser,
                    category_type=None, limit=None):
    """
    Scrape all drivers from a category listing page.

    Returns (successes, failures) where each is a list of (driver_id, detail).
    """
    log.info("Discovering products from category: %s", category_url)
    product_urls = discover_product_urls(
        session, category_url, delay, robots_parser, limit=limit
    )
    log.info("Found %d product URLs", len(product_urls))

    successes = []
    failures = []

    for i, url in enumerate(product_urls, 1):
        log.info("Processing %d/%d: %s", i, len(product_urls), url)
        try:
            driver_id, result = scrape_driver(
                session, url, output_dir, delay, robots_parser,
                category_type=category_type,
            )
            if driver_id:
                successes.append((driver_id, result))
            else:
                failures.append((url, result))
        except Exception as exc:
            log.error("Unexpected error scraping %s: %s", url, exc)
            failures.append((url, str(exc)))

    return successes, failures


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Scrape speaker driver T/S parameters from parts-express.com",
    )
    parser.add_argument(
        "--type",
        choices=["woofer", "midrange", "tweeter", "subwoofer", "full-range"],
        help="Driver type category to scrape",
    )
    parser.add_argument(
        "--category-url",
        help="Direct category URL to scrape (overrides --type)",
    )
    parser.add_argument(
        "--search",
        help="Search query (not supported — parts-express search is JS-rendered; "
             "use --type or --category-url instead)",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for driver YAML files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of drivers to scrape",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"Minimum delay between requests in seconds (default: {DEFAULT_DELAY})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.verbose:
        log.setLevel(logging.DEBUG)

    if args.search:
        log.error(
            "The --search option is not supported because parts-express.com "
            "search results are JavaScript-rendered. Use --type or --category-url "
            "to scrape from a category listing page instead."
        )
        return 1

    # Determine category URL
    if args.category_url:
        category_url = args.category_url
        category_type = args.type  # May be None
    elif args.type:
        path = CATEGORY_URLS.get(args.type)
        if path is None:
            log.error("Unknown type: %s", args.type)
            return 1
        category_url = BASE_URL + path
        category_type = args.type
    else:
        log.error("Either --type or --category-url is required (--search is not supported)")
        return 1

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    log.info("Output directory: %s", output_dir)
    log.info("Delay between requests: %.1fs", args.delay)

    session = _create_session()
    robots_parser = _check_robots_txt(session)

    successes, failures = scrape_category(
        session, category_url, output_dir, args.delay, robots_parser,
        category_type=category_type, limit=args.limit,
    )

    # Summary
    print("\n" + "=" * 60)
    print("SCRAPE SUMMARY")
    print("=" * 60)
    print(f"  Successful: {len(successes)}")
    for driver_id, yaml_path in successes:
        print(f"    {driver_id} -> {yaml_path}")
    print(f"  Failed:     {len(failures)}")
    for url, error in failures:
        print(f"    {url}: {error}")
    print("=" * 60)

    if failures:
        return 1
    if not successes:
        log.error("No drivers were scraped")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
