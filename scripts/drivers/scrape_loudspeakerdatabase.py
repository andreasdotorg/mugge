#!/usr/bin/env python3
"""
Scraper for loudspeakerdatabase.com — extracts speaker driver T/S parameters
and outputs conforming driver YAML files.

Usage:
    python scripts/drivers/scrape_loudspeakerdatabase.py --limit 3
    python scripts/drivers/scrape_loudspeakerdatabase.py --manufacturer "Dayton Audio"
    python scripts/drivers/scrape_loudspeakerdatabase.py --type woofer --limit 10
    python scripts/drivers/scrape_loudspeakerdatabase.py --delay 3 --output-dir /tmp/drivers

Requires: requests, beautifulsoup4, PyYAML
"""

import argparse
import html as htmlmod
import json
import logging
import os
import re
import sys
import time
import urllib.robotparser
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.loudspeakerdatabase.com"
SEARCH_API = BASE_URL + "/search_api"
NEXT_PAGE_API = BASE_URL + "/next_page_api"
ROBOTS_URL = BASE_URL + "/robots.txt"
USER_AGENT = "pi4-audio-workstation-scraper/1.0 (+https://github.com/gabriela-bogk/pi4-audio-workstation)"

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "configs" / "drivers"
DEFAULT_DELAY = 2.0  # seconds between requests
PAGE_SIZE = 40  # cards per API page (site returns 40 unique cards)

# Mapping from loudspeakerdatabase.com type values to our schema driver_type
TYPE_MAP = {
    "Subwoofer": "subwoofer",
    "Shallow_Subwoofer": "subwoofer",
    "Woofer": "woofer",
    "Shallow_Woofer": "woofer",
    "Mid_Bass": "woofer",
    "Shallow_Mid-Woofer": "woofer",
    "Mid-range": "midrange",
    "Full-range": "full-range",
    "Coaxial": "coaxial",
    "2_Way": "coaxial",
    "2_Way_Kit": "coaxial",
    "3_Way": "coaxial",
    "Triaxial": "coaxial",
    # These don't map cleanly to our schema — default to woofer
    "Bass_Guitar_Speaker": "woofer",
    "Guitar_Speaker": "full-range",
    "Low_frequency": "woofer",
    "Miniature": "full-range",
}

# Mapping from loudspeakerdatabase.com brand values to display names.
# Populated dynamically from the homepage dropdown.
BRAND_VALUE_TO_NAME = {}
BRAND_NAME_TO_VALUE = {}

# Our schema type filter values mapped to site type values
SCHEMA_TYPE_TO_SITE_TYPES = {
    "woofer": ["Woofer", "Shallow_Woofer", "Mid_Bass", "Shallow_Mid-Woofer",
               "Bass_Guitar_Speaker", "Low_frequency"],
    "midrange": ["Mid-range"],
    "tweeter": [],  # loudspeakerdatabase.com does not seem to list tweeters
    "full-range": ["Full-range", "Guitar_Speaker", "Miniature"],
    "subwoofer": ["Subwoofer", "Shallow_Subwoofer"],
    "coaxial": ["Coaxial", "2_Way", "2_Way_Kit", "3_Way", "Triaxial"],
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scrape_ldb")


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def create_session():
    """Create a requests session with appropriate headers."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    return session


def check_robots_txt(session):
    """Check robots.txt to confirm scraping is allowed for our user agent."""
    rp = urllib.robotparser.RobotFileParser()
    try:
        resp = session.get(ROBOTS_URL, timeout=10)
        resp.raise_for_status()
        rp.parse(resp.text.splitlines())
    except requests.RequestException as exc:
        log.warning("Could not fetch robots.txt: %s — proceeding cautiously", exc)
        return True

    allowed = rp.can_fetch(USER_AGENT, BASE_URL + "/")
    if not allowed:
        log.error("robots.txt disallows scraping for user agent %s", USER_AGENT)
    else:
        log.info("robots.txt allows scraping for our user agent")
    return allowed


# ---------------------------------------------------------------------------
# Brand/type discovery from homepage
# ---------------------------------------------------------------------------

def discover_brands_and_types(session, delay):
    """Fetch the homepage and extract brand/type dropdown mappings."""
    resp = session.get(BASE_URL + "/", timeout=30)
    resp.raise_for_status()
    raw_html = resp.text

    # Parse brand dropdown: <span value="CODE">Display Name</span>
    idx_brand = raw_html.find('data-dropdown="brand"')
    idx_type = raw_html.find('data-dropdown="type"')
    idx_avail = raw_html.find('data-dropdown="available_on"')

    brands = {}
    if idx_brand >= 0 and idx_type >= 0:
        brand_section = raw_html[idx_brand:idx_type]
        for val, text in re.findall(
            r'<span value="([^"]*)"[^>]*>([^<]*)</span>', brand_section
        ):
            display = htmlmod.unescape(text).strip()
            brands[val] = display

    types = {}
    if idx_type >= 0 and idx_avail >= 0:
        type_section = raw_html[idx_type:idx_avail]
        for val, text in re.findall(
            r'<span value="([^"]*)"[^>]*>([^<]*)</span>', type_section
        ):
            display = htmlmod.unescape(text).strip()
            types[val] = display

    log.info("Discovered %d brands, %d types from homepage", len(brands), len(types))
    time.sleep(delay)
    return brands, types


# ---------------------------------------------------------------------------
# Card enumeration via search/next_page APIs
# ---------------------------------------------------------------------------

def _parse_cards_from_html(raw_html):
    """
    Extract driver cards from search API HTML response.

    Returns list of dicts with keys:
        woofer_id, url, brand_value, brand_display, model, driver_type_raw, ts_data
    """
    cards = []
    seen_ids = set()

    # Find all woofer_card elements
    # Pattern: class="woofer_card ..." data-woofer-id="NNN" data-woofer="{...}"
    for match in re.finditer(
        r'class="woofer_card[^"]*"[^>]*'
        r'data-woofer-id="(\d+)"[^>]*'
        r'data-woofer="([^"]*)"[^>]*>'
        r'(.*?)(?=class="woofer_card|<script class="count"|<script class="histograms_data"|$)',
        raw_html,
        re.DOTALL,
    ):
        wid = match.group(1)
        if wid in seen_ids:
            continue
        seen_ids.add(wid)

        wdata_raw = htmlmod.unescape(match.group(2))
        card_html = match.group(3)

        try:
            ts_data = json.loads(wdata_raw)
        except json.JSONDecodeError:
            log.warning("Failed to parse JSON for card id=%s", wid)
            continue

        # Extract URL from first link in card
        link_match = re.search(r'href="(/([^/"]+)/([^"]+))"', card_html)
        if not link_match:
            continue

        url = link_match.group(1)
        brand_value = link_match.group(2)
        model_slug = link_match.group(3)

        # Extract display text (brand name and model)
        soup = BeautifulSoup(card_html[:1000], "html.parser")
        texts = [t.strip() for t in soup.stripped_strings]
        brand_display = texts[0] if texts else brand_value
        model_display = texts[1] if len(texts) > 1 else model_slug

        # Extract driver type from card text
        driver_type_raw = None
        for t in texts[2:]:
            # Types typically appear after the impedance/size info
            clean = t.replace(" ", "_")
            if clean in TYPE_MAP:
                driver_type_raw = clean
                break

        cards.append({
            "woofer_id": wid,
            "url": url,
            "brand_value": brand_value,
            "brand_display": brand_display,
            "model_display": model_display,
            "model_slug": model_slug,
            "driver_type_raw": driver_type_raw,
            "ts_data": ts_data,
        })

    return cards


def _get_total_count(raw_html):
    """Extract total result count from search API response."""
    match = re.search(r'<script class="count">(\d+)</script>', raw_html)
    if match:
        return int(match.group(1))
    return None


def enumerate_drivers(session, delay, manufacturer=None, driver_type=None, limit=None):
    """
    Enumerate all drivers matching the given filters.

    Parameters
    ----------
    session : requests.Session
    delay : float
        Seconds between requests.
    manufacturer : str or None
        Brand filter value (the dropdown value code, e.g. "Dayton").
    driver_type : str or None
        Site type filter value (e.g. "Subwoofer").
    limit : int or None
        Maximum number of drivers to return.

    Returns
    -------
    list of dict
        Card data for each driver.
    """
    # Build search URL path
    url_parts = []
    if manufacturer:
        url_parts.append(f"brand={manufacturer}")
    if driver_type:
        url_parts.append(f"type={driver_type}")
    url_path = "/" + "/".join(url_parts) if url_parts else ""

    # First request to search_api
    search_url = SEARCH_API + url_path
    log.info("Fetching search results: %s", search_url)
    resp = session.get(search_url, timeout=30)
    resp.raise_for_status()

    all_cards = _parse_cards_from_html(resp.text)
    total_count = _get_total_count(resp.text)

    if total_count is not None:
        log.info("Total results: %d, got %d cards in first page", total_count, len(all_cards))
    else:
        log.info("Got %d cards in first page (total unknown)", len(all_cards))

    if limit and len(all_cards) >= limit:
        return all_cards[:limit]

    # Paginate through remaining results
    offset = PAGE_SIZE
    max_cards = min(total_count or 5000, 5000)  # Safety cap
    if limit:
        max_cards = min(max_cards, limit)

    while len(all_cards) < max_cards:
        time.sleep(delay)
        next_url = NEXT_PAGE_API + url_path + f"/offset={offset}"
        log.info("Fetching next page: offset=%d (%d/%d)", offset, len(all_cards), max_cards)

        try:
            resp = session.get(next_url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Failed to fetch offset=%d: %s", offset, exc)
            break

        page_cards = _parse_cards_from_html(resp.text)
        if not page_cards:
            log.info("No more cards at offset=%d, stopping pagination", offset)
            break

        all_cards.extend(page_cards)
        offset += PAGE_SIZE

        if limit and len(all_cards) >= limit:
            return all_cards[:limit]

    log.info("Enumerated %d drivers total", len(all_cards))
    return all_cards[:limit] if limit else all_cards


# ---------------------------------------------------------------------------
# Driver detail page parsing
# ---------------------------------------------------------------------------

def _extract_spec_value(text):
    """
    Parse a numeric value from spec text like '33 Hz', '0.63', '14.5 mm'.
    Returns float or None.
    """
    if not text:
        return None
    # Remove unit suffixes and whitespace
    cleaned = re.sub(r'\s*(Hz|dB|mm|mH|cm[²³]|g|kg|N/A|N[·.]s/m|[µu]m/N|N/mm|L|W|Ω|″|°).*$', '', text.strip())
    cleaned = cleaned.replace(",", ".").replace("±", "").replace("\u200a", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_text_value(text):
    """Extract a cleaned text value."""
    if not text:
        return None
    return text.strip() or None


def parse_driver_detail(raw_html, driver_url):
    """
    Parse a driver detail page and extract all available T/S parameters.

    Returns a dict with keys mapping to our schema fields.
    """
    result = {}

    # Extract page title for brand/model
    title_match = re.search(r'<title>(.*?)</title>', raw_html)
    if title_match:
        result["_title"] = htmlmod.unescape(title_match.group(1))

    # Get the main data-woofer JSON (first instance is the featured driver)
    woofer_match = re.search(r'data-woofer="([^"]*)"', raw_html)
    if woofer_match:
        try:
            card_data = json.loads(htmlmod.unescape(woofer_match.group(1)))
            result["_card_data"] = card_data
        except json.JSONDecodeError:
            pass

    # Parse the detail page text line by line
    # The page has a structured spec section with labels and values
    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove script and style
    for tag in soup(["script", "style"]):
        tag.decompose()

    body = soup.find("body")
    if not body:
        return result

    # Strategy: find the Specifications section and parse label-value pairs
    # The page uses a flat structure with parameter names and values in
    # adjacent elements within spec table cells.

    # First, try to find all table rows with two cells
    all_specs = {}
    for table in body.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) == 2:
                label = cells[0].get_text(separator=" ", strip=True)
                value = cells[1].get_text(separator=" ", strip=True)
                if label and value:
                    all_specs[label] = value

    # Also parse from the full text content, which has a more complete
    # structure. The detail section has patterns like:
    # "Resonance frequency (free air)"
    # "f S" (subscript)
    # "33"
    # "Hz"
    full_text = body.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    # Build a line-based parser for the specification section
    spec_section_started = False
    i = 0
    while i < len(lines):
        line = lines[i]

        if line == "Specifications":
            spec_section_started = True
            i += 1
            continue

        if not spec_section_started:
            i += 1
            continue

        # Stop at known non-spec sections (including "Similar X to Y" section
        # which lists OTHER drivers and would overwrite our parsed values)
        if (line in ("As an Amazon Associate", "About Loudspeaker Database")
                or line.startswith("Similar")):
            break

        # Match known spec patterns
        # Sensitivity
        if line.startswith("Sensitivity") and "1W" in line:
            result["_section"] = "sensitivity"
        elif line == "SPL" and i + 2 < len(lines) and lines[i + 1] == "1W":
            val = _extract_spec_value(lines[i + 2])
            if val:
                result["sensitivity_db_1w1m"] = val
            i += 3
            continue

        # Thiele & Small parameters section
        elif "Thiele" in line and "Small" in line:
            result["_section"] = "ts"

        # Resonance frequency
        elif line.startswith("Resonance frequency"):
            # Next lines: "f" "S" value "Hz"
            j = i + 1
            while j < len(lines) and lines[j] in ("f", "S", "s"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["fs_hz"] = val
            i = j + 1
            continue

        # Mechanical quality factor (Qms)
        elif line.startswith("Mechanical quality factor"):
            j = i + 1
            while j < len(lines) and lines[j] in ("Q", "MS", "ms"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["qms"] = val
            i = j + 1
            continue

        # Electrical quality factor (Qes)
        elif line.startswith("Electrical quality factor"):
            j = i + 1
            while j < len(lines) and lines[j] in ("Q", "ES", "es"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["qes"] = val
            i = j + 1
            continue

        # Total quality factor (Qts)
        elif line.startswith("Total quality factor"):
            j = i + 1
            while j < len(lines) and lines[j] in ("Q", "TS", "ts"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["qts"] = val
            i = j + 1
            continue

        # Maximum linear excursion
        elif line.startswith("Maximum linear excursion"):
            j = i + 1
            while j < len(lines) and lines[j] in ("x", "max", "X"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["xmax_mm"] = val
            i = j + 1
            continue

        # Maximum excursion before damage
        elif line.startswith("Maximum excursion before damage"):
            j = i + 1
            while j < len(lines) and lines[j] in ("x", "lim", "X"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["xmech_mm"] = val
            i = j + 1
            continue

        # Air volume displaced (Vd)
        elif line.startswith("Air volume displaced"):
            j = i + 1
            while j < len(lines) and lines[j] in ("max", "V", "D", "x"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["vd_cm3"] = val
            i = j + 1
            continue

        # Power handling (continuous)
        elif line == "Power handling":
            j = i + 1
            while j < len(lines) and lines[j] in ("P",):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["pe_max_watts"] = val
            i = j + 1
            continue

        # Program power
        elif line == "Program power":
            j = i + 1
            while j < len(lines) and lines[j] in ("P", "max"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["pe_peak_watts"] = val
            i = j + 1
            continue

        # Nominal impedance
        elif line == "Nominal impedance":
            j = i + 1
            while j < len(lines) and lines[j] in ("Z",):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["z_nom_ohm"] = val
            i = j + 1
            continue

        # DC resistance
        elif line == "DC resistance":
            j = i + 1
            while j < len(lines) and lines[j] in ("R", "E", "e"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["re_ohm"] = val
            i = j + 1
            continue

        # Inductance
        elif line.startswith("Inductance"):
            j = i + 1
            while j < len(lines) and lines[j] in ("L", "E", "e"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["le_mh"] = val
            i = j + 1
            continue

        # VC Diameter
        elif line == "VC Diameter":
            if i + 1 < len(lines):
                val = _extract_spec_value(lines[i + 1])
                if val:
                    result["voice_coil_diameter_mm"] = val
            i += 2
            continue

        # Force factor (Bl)
        elif line == "Force factor":
            j = i + 1
            while j < len(lines) and lines[j] in ("Bl",):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["bl_tm"] = val
            i = j + 1
            continue

        # Magnet weight
        elif line == "Weight" and result.get("_section_magnet"):
            if i + 1 < len(lines):
                val = _extract_spec_value(lines[i + 1])
                if val:
                    result["weight_kg"] = val
            i += 2
            continue

        # Magnet section marker
        elif line == "Magnet":
            result["_section_magnet"] = True

        # Diaphragm section marker
        elif line == "Diaphragm":
            result["_section_magnet"] = False
            result["_section_diaphragm"] = True

        # Effective diameter
        elif line == "Effective diameter" and result.get("_section_diaphragm"):
            if i + 1 < len(lines):
                val = _extract_spec_value(lines[i + 1])
                if val:
                    result["actual_diameter_mm"] = val
            i += 2
            continue

        # Effective area (Sd)
        elif line == "Effective area":
            j = i + 1
            while j < len(lines) and lines[j] in ("S", "D", "d"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["sd_cm2"] = val
            i = j + 1
            continue

        # Moving mass including air load (Mms)
        elif line.startswith("Moving mass") and "air load" in line:
            j = i + 1
            while j < len(lines) and lines[j] in ("M", "MS", "ms"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["mms_g"] = val
            i = j + 1
            continue

        # Moving mass without air load (Mmd)
        elif line == "Moving mass":
            j = i + 1
            while j < len(lines) and lines[j] in ("M", "MD", "md"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["mmd_g"] = val
            i = j + 1
            continue

        # Cone material
        elif line == "Material" and result.get("_section_diaphragm"):
            if i + 1 < len(lines):
                result["cone_material_raw"] = lines[i + 1]
            i += 2
            continue

        # Surround material
        elif line == "Surround material":
            if i + 1 < len(lines):
                result["surround_material_raw"] = lines[i + 1]
            i += 2
            continue

        # Suspensions section
        elif line == "Suspensions":
            result["_section_diaphragm"] = False
            result["_section_magnet"] = False

        # Compliance (Cms)
        elif line == "Compliance":
            j = i + 1
            while j < len(lines) and lines[j] in ("C", "MS", "ms"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    # Site gives Cms in µm/N, schema wants m/N
                    # µm/N = 1e-6 m/N, but let's check: 97 µm/N = 97e-6 m/N
                    # Actually the schema field is cms_m_per_n and the value
                    # 97 µm/N might need conversion. Let's store the raw value
                    # and check units from the page.
                    result["cms_um_per_n"] = val
            i = j + 1
            continue

        # Equivalent volume (Vas)
        elif line.startswith("Equivalent volume"):
            j = i + 1
            while j < len(lines) and lines[j] in ("V", "AS", "as"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["vas_liters"] = val
            i = j + 1
            continue

        # Dimensions section
        elif line == "Dimensions":
            result["_section_dimensions"] = True
            result["_section_diaphragm"] = False
            result["_section_magnet"] = False

        # Nominal diameter (in dimensions section)
        elif line == "Nominal diameter" and result.get("_section_dimensions"):
            # Next line may be the inch value, then mm value
            if i + 1 < len(lines):
                val = _extract_spec_value(lines[i + 1])
                if val:
                    result["nominal_diameter_in"] = val
            # Look for mm value too
            if i + 2 < len(lines):
                mm_val = _extract_spec_value(lines[i + 2])
                # Skip, we use inches from title
            i += 3
            continue

        # Overall diameter
        elif line == "Overall diameter":
            if i + 1 < len(lines):
                val = _extract_spec_value(lines[i + 1])
                if val:
                    result["flange_diameter_mm"] = val
            i += 2
            continue

        # Baffle cutout diameter
        elif line == "Baffle cutout diameter":
            if i + 1 < len(lines):
                val = _extract_spec_value(lines[i + 1])
                if val:
                    result["cutout_diameter_mm"] = val
            i += 2
            continue

        # Overall depth / Mounting depth
        elif line in ("Overall depth", "Mounting depth"):
            if i + 1 < len(lines):
                val = _extract_spec_value(lines[i + 1])
                if val:
                    result["overall_depth_mm"] = val
            i += 2
            continue

        # Bolt circle diameter
        elif "bolt" in line.lower() and "circle" in line.lower():
            if i + 1 < len(lines):
                val = _extract_spec_value(lines[i + 1])
                if val:
                    result["bolt_circle_diameter_mm"] = val
            i += 2
            continue

        # Bolt count / number of holes
        elif "bolt" in line.lower() or "screw hole" in line.lower():
            if i + 1 < len(lines):
                val = _extract_spec_value(lines[i + 1])
                if val:
                    result["bolt_count"] = int(val)
            i += 2
            continue

        # Net weight
        elif line in ("Net weight", "Weight") and result.get("_section_dimensions"):
            if i + 1 < len(lines):
                val = _extract_spec_value(lines[i + 1])
                if val:
                    result["weight_kg"] = val
            i += 2
            continue

        # Efficiency / eta0
        elif line.startswith("Reference efficiency") or line.startswith("Efficiency"):
            j = i + 1
            while j < len(lines) and lines[j] in ("η", "0", "n"):
                j += 1
            if j < len(lines):
                val = _extract_spec_value(lines[j])
                if val:
                    result["eta0_percent"] = val
            i = j + 1
            continue

        i += 1

    # Clean up internal tracking keys
    for key in list(result.keys()):
        if key.startswith("_section"):
            del result[key]

    return result


# ---------------------------------------------------------------------------
# Mapping to schema
# ---------------------------------------------------------------------------

def _normalize_cone_material(raw):
    """Map cone material text to schema enum value."""
    if not raw:
        return None
    raw_lower = raw.lower()
    if "paper" in raw_lower:
        return "paper"
    if "polypropylene" in raw_lower or "pp" in raw_lower:
        return "polypropylene"
    if "aluminum" in raw_lower or "aluminium" in raw_lower:
        return "aluminum"
    if "kevlar" in raw_lower or "aramid" in raw_lower:
        return "kevlar"
    if "carbon" in raw_lower:
        return "carbon-fiber"
    return None


def _normalize_surround_material(raw):
    """Map surround material text to schema enum value."""
    if not raw:
        return None
    raw_lower = raw.lower()
    if "rubber" in raw_lower or "butyl" in raw_lower or "nbr" in raw_lower:
        return "rubber"
    if "foam" in raw_lower:
        return "foam"
    if "cloth" in raw_lower or "textile" in raw_lower:
        return "cloth"
    return None


def make_driver_id(brand_display, model_display):
    """Generate a filesystem-safe driver ID slug."""
    combined = f"{brand_display}-{model_display}"
    # Normalize to lowercase, replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", combined.lower())
    slug = slug.strip("-")
    # Collapse multiple hyphens
    slug = re.sub(r"-+", "-", slug)
    return slug


def build_driver_yaml(card, detail, driver_url):
    """
    Build a driver YAML dict conforming to the project schema.

    Parameters
    ----------
    card : dict
        Card data from search enumeration.
    detail : dict
        Detailed spec data from driver page.
    driver_url : str
        Full URL of the driver page.

    Returns
    -------
    dict
        Driver data conforming to schema_version 1.
    """
    brand_display = BRAND_VALUE_TO_NAME.get(
        card["brand_value"], card["brand_display"]
    )
    model_display = card["model_display"]
    driver_id = make_driver_id(brand_display, model_display)

    # Merge card T/S data with detail page data (detail takes precedence)
    ts_card = card.get("ts_data", {})

    # Get values — prefer detail page, fall back to card JSON
    fs_hz = detail.get("fs_hz") or ts_card.get("fs")
    re_ohm = detail.get("re_ohm") or ts_card.get("re")
    z_nom_ohm = detail.get("z_nom_ohm") or ts_card.get("z")
    qts = detail.get("qts") or ts_card.get("qts")
    qes = detail.get("qes")
    qms = detail.get("qms")
    vas_liters = detail.get("vas_liters")
    xmax_mm = detail.get("xmax_mm") or ts_card.get("xmax")
    xmech_mm = detail.get("xmech_mm")
    le_mh = detail.get("le_mh") or ts_card.get("le")
    bl_tm = detail.get("bl_tm") or ts_card.get("bl")
    mms_g = detail.get("mms_g")
    mmd_g = detail.get("mmd_g") or ts_card.get("mmd")
    sd_cm2 = detail.get("sd_cm2") or ts_card.get("sd")
    spl_1w = detail.get("sensitivity_db_1w1m") or ts_card.get("spl1w")
    pe_max = detail.get("pe_max_watts")
    pe_peak = detail.get("pe_peak_watts") or ts_card.get("pmax")
    eta0 = detail.get("eta0_percent")
    vd_cm3 = detail.get("vd_cm3")
    voice_coil_mm = detail.get("voice_coil_diameter_mm")
    weight_kg = detail.get("weight_kg")

    # Cms conversion: site gives µm/N, schema wants m/N
    cms_m_per_n = None
    cms_raw = detail.get("cms_um_per_n") or ts_card.get("cms")
    if cms_raw is not None:
        # The card JSON "cms" value is in µm/N (same unit as the detail page)
        cms_m_per_n = cms_raw * 1e-6

    # Map driver type
    driver_type_raw = card.get("driver_type_raw")
    driver_type = TYPE_MAP.get(driver_type_raw) if driver_type_raw else None
    # If not found from card, try extracting from title
    if not driver_type:
        title = detail.get("_title", "")
        title_lower = title.lower()
        if "subwoofer" in title_lower:
            driver_type = "subwoofer"
        elif "woofer" in title_lower:
            driver_type = "woofer"
        elif "mid-range" in title_lower or "midrange" in title_lower:
            driver_type = "midrange"
        elif "full-range" in title_lower:
            driver_type = "full-range"
        elif "coaxial" in title_lower:
            driver_type = "coaxial"
        elif "tweeter" in title_lower:
            driver_type = "tweeter"

    # Nominal diameter from detail or title
    nominal_in = detail.get("nominal_diameter_in")
    if not nominal_in:
        title = detail.get("_title", "")
        inch_match = re.search(r'(\d+(?:\.\d+)?)\s*[″"]', title)
        if inch_match:
            nominal_in = float(inch_match.group(1))

    # Materials
    cone_material = _normalize_cone_material(detail.get("cone_material_raw"))
    surround_material = _normalize_surround_material(detail.get("surround_material_raw"))

    driver_data = {
        "schema_version": 1,
        "metadata": {
            "id": driver_id,
            "manufacturer": brand_display,
            "model": model_display,
            "driver_type": driver_type,
            "nominal_diameter_in": nominal_in,
            "actual_diameter_mm": detail.get("actual_diameter_mm"),
            "magnet_type": None,
            "cone_material": cone_material,
            "surround_material": surround_material,
            "voice_coil_diameter_mm": voice_coil_mm,
            "weight_kg": weight_kg,
            "mounting": {
                "cutout_diameter_mm": detail.get("cutout_diameter_mm"),
                "bolt_circle_diameter_mm": detail.get("bolt_circle_diameter_mm"),
                "bolt_count": detail.get("bolt_count"),
                "overall_depth_mm": detail.get("overall_depth_mm"),
                "flange_diameter_mm": detail.get("flange_diameter_mm"),
            },
            "datasheet_url": driver_url,
            "datasheet_file": None,
            "ts_parameter_source": "manufacturer",
            "ts_measurement_date": None,
            "ts_measurement_notes": "",
            "notes": f"Scraped from loudspeakerdatabase.com on {time.strftime('%Y-%m-%d')}",
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
            "xmech_mm": xmech_mm,
            "le_mh": le_mh,
            "bl_tm": bl_tm,
            "mms_g": mms_g,
            "mmd_g": mmd_g,
            "sd_cm2": sd_cm2,
            "sensitivity_db_1w1m": spl_1w,
            "sensitivity_db_2v83_1m": None,
            "pe_max_watts": pe_max,
            "pe_peak_watts": pe_peak,
            "power_handling_note": "",
            "eta0_percent": eta0,
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


# ---------------------------------------------------------------------------
# YAML output
# ---------------------------------------------------------------------------

def _yaml_representer_none(dumper, data):
    """Represent None as null in YAML."""
    return dumper.represent_scalar("tag:yaml.org,2002:null", "null")


def _yaml_representer_str(dumper, data):
    """Use plain style for short strings, literal for multiline."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def write_driver_yaml(driver_data, output_dir):
    """
    Write a driver YAML file.

    Creates {output_dir}/{driver_id}/driver.yml
    """
    driver_id = driver_data["metadata"]["id"]
    driver_dir = Path(output_dir) / driver_id
    driver_dir.mkdir(parents=True, exist_ok=True)
    driver_file = driver_dir / "driver.yml"

    dumper = yaml.Dumper
    dumper.add_representer(type(None), _yaml_representer_none)

    with open(driver_file, "w") as f:
        yaml.dump(
            driver_data,
            f,
            Dumper=dumper,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )

    return driver_file


# ---------------------------------------------------------------------------
# Main scraper logic
# ---------------------------------------------------------------------------

def resolve_manufacturer_filter(manufacturer_input):
    """
    Resolve a manufacturer name to the site's brand filter value.

    Accepts either the dropdown value code (e.g. "Dayton") or the
    display name (e.g. "Dayton Audio").
    """
    if not manufacturer_input:
        return None

    # Direct match on value code
    if manufacturer_input in BRAND_VALUE_TO_NAME:
        return manufacturer_input

    # Match on display name (case-insensitive)
    input_lower = manufacturer_input.lower()
    for value, display in BRAND_VALUE_TO_NAME.items():
        if display.lower() == input_lower:
            return value

    # Partial match
    for value, display in BRAND_VALUE_TO_NAME.items():
        if input_lower in display.lower() or input_lower in value.lower():
            return value

    log.error(
        "Manufacturer '%s' not found in database. Available: %s",
        manufacturer_input,
        ", ".join(sorted(BRAND_VALUE_TO_NAME.values())),
    )
    return None


def resolve_type_filter(type_input):
    """
    Resolve a type name to site type filter values.

    Accepts our schema type names (woofer, midrange, etc.) or
    site type names (Subwoofer, Mid_Bass, etc.).
    """
    if not type_input:
        return None

    # Check if it's a schema type name
    input_lower = type_input.lower()
    if input_lower in SCHEMA_TYPE_TO_SITE_TYPES:
        site_types = SCHEMA_TYPE_TO_SITE_TYPES[input_lower]
        if site_types:
            return ",".join(site_types)
        log.warning("Type '%s' has no matching site types", type_input)
        return None

    # Check if it's a direct site type
    for site_type in TYPE_MAP:
        if site_type.lower() == input_lower or site_type == type_input:
            return site_type

    log.error(
        "Type '%s' not recognized. Use one of: %s",
        type_input,
        ", ".join(sorted(set(list(SCHEMA_TYPE_TO_SITE_TYPES.keys()) + list(TYPE_MAP.keys())))),
    )
    return None


def scrape(args):
    """Main scrape function."""
    session = create_session()

    # Check robots.txt
    if not check_robots_txt(session):
        log.error("Aborting: robots.txt disallows scraping")
        return 1

    time.sleep(args.delay)

    # Discover brands and types from homepage
    global BRAND_VALUE_TO_NAME, BRAND_NAME_TO_VALUE
    brands, types = discover_brands_and_types(session, args.delay)
    BRAND_VALUE_TO_NAME = brands
    BRAND_NAME_TO_VALUE = {v: k for k, v in brands.items()}

    # Resolve filters
    brand_filter = resolve_manufacturer_filter(args.manufacturer)
    if args.manufacturer and brand_filter is None:
        return 1

    type_filter = resolve_type_filter(args.type)
    if args.type and type_filter is None:
        return 1

    # Enumerate drivers
    cards = enumerate_drivers(
        session, args.delay,
        manufacturer=brand_filter,
        driver_type=type_filter,
        limit=args.limit,
    )

    if not cards:
        log.warning("No drivers found matching filters")
        return 0

    log.info("Will scrape %d driver detail pages", len(cards))

    # Scrape each driver detail page
    output_dir = Path(args.output_dir)
    successes = 0
    failures = []
    skipped = 0

    for idx, card in enumerate(cards):
        driver_url = BASE_URL + card["url"]
        brand = BRAND_VALUE_TO_NAME.get(card["brand_value"], card["brand_display"])
        model = card["model_display"]

        # Check if already exists (idempotent: update existing)
        driver_id = make_driver_id(brand, model)
        existing_file = output_dir / driver_id / "driver.yml"

        log.info(
            "[%d/%d] Scraping %s %s (%s)",
            idx + 1, len(cards), brand, model, driver_url,
        )

        time.sleep(args.delay)

        try:
            resp = session.get(driver_url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.error("Failed to fetch %s: %s", driver_url, exc)
            failures.append({"brand": brand, "model": model, "url": driver_url, "error": str(exc)})
            continue

        try:
            detail = parse_driver_detail(resp.text, driver_url)
        except Exception as exc:
            log.error("Failed to parse %s: %s", driver_url, exc)
            failures.append({"brand": brand, "model": model, "url": driver_url, "error": str(exc)})
            continue

        try:
            driver_data = build_driver_yaml(card, detail, driver_url)
        except Exception as exc:
            log.error("Failed to build YAML for %s %s: %s", brand, model, exc)
            failures.append({"brand": brand, "model": model, "url": driver_url, "error": str(exc)})
            continue

        # Validate: at minimum fs_hz, re_ohm, z_nom_ohm, qts should be present
        ts = driver_data["thiele_small"]
        missing_required = [
            f for f in ("fs_hz", "re_ohm", "z_nom_ohm", "qts")
            if ts.get(f) is None
        ]
        if missing_required:
            log.warning(
                "  %s %s: missing required T/S fields: %s — writing anyway",
                brand, model, ", ".join(missing_required),
            )

        try:
            out_file = write_driver_yaml(driver_data, output_dir)
            if existing_file.exists():
                log.info("  Updated: %s", out_file)
            else:
                log.info("  Created: %s", out_file)
            successes += 1
        except Exception as exc:
            log.error("Failed to write YAML for %s %s: %s", brand, model, exc)
            failures.append({"brand": brand, "model": model, "url": driver_url, "error": str(exc)})

    # Summary
    log.info("")
    log.info("=" * 60)
    log.info("SCRAPE SUMMARY")
    log.info("=" * 60)
    log.info("Total attempted: %d", len(cards))
    log.info("Successes:       %d", successes)
    log.info("Failures:        %d", len(failures))
    if skipped:
        log.info("Skipped:         %d", skipped)

    if failures:
        log.info("")
        log.info("Failed drivers:")
        for f in failures:
            log.info("  %s %s — %s", f["brand"], f["model"], f["error"])

    return 1 if failures else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape loudspeakerdatabase.com for speaker driver T/S parameters",
    )
    parser.add_argument(
        "--manufacturer",
        help="Filter by manufacturer name (e.g. 'Dayton Audio', 'ESX')",
    )
    parser.add_argument(
        "--type",
        help="Filter by driver type (woofer/midrange/tweeter/subwoofer/full-range/coaxial)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of drivers to scrape (for testing)",
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

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.delay < 2.0:
        log.warning("Delay %.1fs is below minimum 2.0s — using 2.0s", args.delay)
        args.delay = 2.0

    return scrape(args)


if __name__ == "__main__":
    sys.exit(main())
