#!/usr/bin/env python3
"""
soundimports.eu speaker driver scraper.

Extracts T/S parameters and specifications from soundimports.eu product
pages and outputs conforming driver YAML files for the speaker driver database.

Usage examples:
    # Scrape subwoofer category, limit to 3 drivers
    python scrape_soundimports.py --type subwoofer --limit 3

    # Scrape a specific category URL
    python scrape_soundimports.py --category-url "https://www.soundimports.eu/en/audio-components/woofers/subwoofer/" --limit 5

    # Scrape only Dayton Audio drivers from the woofer category
    python scrape_soundimports.py --type woofer --manufacturer "Dayton Audio" --limit 10

    # Scrape with custom delay and output directory
    python scrape_soundimports.py --type tweeter --delay 3 --output-dir /tmp/drivers --limit 10

Dependencies: requests, beautifulsoup4, PyYAML (+ stdlib)
"""

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.robotparser

import requests
import yaml
from bs4 import BeautifulSoup, NavigableString

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.soundimports.eu"
USER_AGENT = (
    "pi4-audio-workstation-scraper/1.0 "
    "(+https://github.com/gabriela-bogk/pi4-audio-workstation; "
    "speaker driver database; respectful crawling)"
)
DEFAULT_DELAY = 2.0  # seconds between requests (matches robots.txt Crawl-delay: 2)
DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "configs",
    "drivers",
)

# Category URL paths for each driver type.
# soundimports.eu uses /en/audio-components/ structure.
CATEGORY_URLS = {
    "woofer": "/en/audio-components/woofers/bass-mid-woofer/",
    "midrange": "/en/audio-components/woofers/mid-range-woofer/",
    "tweeter": "/en/audio-components/tweeters/",
    "subwoofer": "/en/audio-components/woofers/subwoofer/",
    "full-range": "/en/audio-components/woofers/full-range-woofer/",
    "coaxial": "/en/audio-components/woofers/coaxial-woofer/",
}

# Unit conversion constants
_INCHES_TO_MM = 25.4
_FT3_TO_LITERS = 28.3168466

# Cone material mapping: soundimports value -> schema enum value
CONE_MATERIAL_MAP = {
    "aluminum": "aluminum",
    "aluminium": "aluminum",
    "paper": "paper",
    "treated paper": "paper",
    "coated paper": "paper",
    "polypropylene": "polypropylene",
    "pp": "polypropylene",
    "kevlar": "kevlar",
    "carbon fiber": "carbon-fiber",
    "carbon fibre": "carbon-fiber",
    "carbon fiber composite": "carbon-fiber",
}

SURROUND_MATERIAL_MAP = {
    "rubber": "rubber",
    "butyl rubber": "rubber",
    "santoprene": "rubber",
    "nbr": "rubber",
    "foam": "foam",
    "cloth": "cloth",
    "treated cloth": "cloth",
}

MAGNET_MATERIAL_MAP = {
    "ferrite": "ferrite",
    "ceramic": "ferrite",
    "neodymium": "neodymium",
    "alnico": "alnico",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scrape_soundimports")

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
        rp.parse([])
    return rp


def _fetch_page(session, url, delay, robots_parser):
    """Fetch a URL, respecting delay and robots.txt. Returns response or None."""
    if not robots_parser.can_fetch(USER_AGENT, url):
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
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_float(text):
    """Extract a float from text, stripping units and symbols."""
    if text is None:
        return None
    cleaned = text.strip()
    # Remove common HTML entities and unit symbols
    cleaned = cleaned.replace("&#937;", "").replace("&Omega;", "")
    cleaned = re.sub(r"[Ωω°²³]", "", cleaned)
    # Remove unit suffixes
    cleaned = re.sub(
        r"\s*(Hz|mH|mm|cm2?|g|T[·.]?m|ft\.?[³3]?|mm/N|dB|Watts?|lbs?|kg|in|"
        r"W|ohms?|Ohms?|liters?|L)\b.*$",
        "", cleaned, flags=re.I,
    )
    # Handle European decimal comma vs. thousand separator:
    # - A comma followed by exactly 1 or 2 digits at end-of-string is a decimal
    #   separator (e.g. "1,22" -> "1.22", "2,5" -> "2.5").
    # - A comma followed by 3+ digits is a thousand separator (e.g. "1,000" -> "1000").
    cleaned = re.sub(r",(\d{1,2})$", r".\1", cleaned)
    cleaned = cleaned.replace(",", "").strip()
    # Handle fractions like "6-1/2"
    match = re.match(r"(\d+)-(\d+)/(\d+)", cleaned)
    if match:
        whole = int(match.group(1))
        num = int(match.group(2))
        denom = int(match.group(3))
        return whole + num / denom
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_sensitivity(text):
    """Parse sensitivity string like '86.8 dB' -> float."""
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


def _parse_vas(raw_value):
    """Parse Vas value that may be in ft^3 or liters. Returns liters."""
    if raw_value is None:
        return None
    text = raw_value.strip()

    # Check if value is in ft^3 / ft.³
    if re.search(r"ft[.³3\^]?", text, re.I):
        val = _parse_float(text)
        return _convert_ft3_to_liters(val)

    # Check if it's in liters (L or liters)
    if re.search(r"\bL\b|liter", text, re.I):
        return _parse_float(text)

    # Try to infer from magnitude: values in liters are typically > 0.5
    # while values in ft^3 are typically < 20 and often < 2
    val = _parse_float(text)
    if val is None:
        return None

    # If no unit specified and value is very small, likely ft^3
    if val < 0.5:
        return _convert_ft3_to_liters(val)
    # Otherwise assume liters (soundimports.eu is European, uses metric)
    return val


def _parse_impedance(raw_value):
    """Parse impedance like '8 ohms' or '4 Ω' -> int."""
    if raw_value is None:
        return None
    val = _parse_float(raw_value)
    if val is not None:
        return int(round(val))
    return None


def _parse_nominal_diameter(raw_value):
    """Parse nominal diameter like '8\"' or '25 mm | 1\"' -> float inches."""
    if raw_value is None:
        return None
    text = raw_value.strip()

    # Handle format like '25 mm | 1"' — prefer inches value
    if "|" in text:
        parts = text.split("|")
        for part in parts:
            part = part.strip()
            if '"' in part or "'" in part or re.search(r'\d+["\u201D]', part):
                cleaned = re.sub(r'["\u201D\'\u2019]', '', part).strip()
                return _parse_float(cleaned)
        # If no inch part found, use first part and check for mm
        first = parts[0].strip()
        if "mm" in first.lower():
            mm_val = _parse_float(first)
            if mm_val is not None:
                return round(mm_val / _INCHES_TO_MM, 2)
        return _parse_float(first)

    # Handle pure inch values with quote marks
    if '"' in text:
        cleaned = text.replace('"', '').strip()
        return _parse_float(cleaned)

    return _parse_float(text)


def _parse_dimension_to_mm(raw_value):
    """Parse a dimension that may be in mm or inches. Returns mm."""
    if raw_value is None:
        return None
    text = raw_value.strip()

    # Check if explicitly in mm
    if "mm" in text.lower():
        return _parse_float(text)

    # Check if explicitly in inches (has " or 'in')
    if '"' in text or re.search(r'\bin\b', text, re.I):
        # Strip inch marks before parsing
        cleaned = text.replace('"', '').replace('\u201D', '').strip()
        val = _parse_float(cleaned)
        return _convert_inches_to_mm(val)

    # Try to infer from magnitude: typical driver dimensions
    val = _parse_float(text)
    if val is None:
        return None
    # Values > 20 are almost certainly mm; values < 20 are likely inches
    if val < 20:
        return _convert_inches_to_mm(val)
    return val


def _parse_bolt_circle(raw_value):
    """
    Parse bolt circle diameter.

    soundimports.eu sometimes stores this as a hole diameter (e.g., "Ø 5.2 mm")
    rather than a circle diameter. We extract the numeric value and return mm.
    """
    if raw_value is None:
        return None
    text = raw_value.strip()
    # Remove diameter symbol
    text = text.replace("Ø", "").replace("⌀", "").strip()
    return _parse_dimension_to_mm(text)


def _parse_weight_to_kg(raw_value):
    """Parse weight that may be in kg or g. Returns kg."""
    if raw_value is None:
        return None
    text = raw_value.strip()
    if re.search(r'\bkg\b', text, re.I):
        return _parse_float(text)
    if re.search(r'\bg\b', text, re.I):
        val = _parse_float(text)
        if val is not None:
            return round(val / 1000.0, 3)
    val = _parse_float(text)
    if val is not None:
        # If > 20, likely grams; otherwise kg
        if val > 20:
            return round(val / 1000.0, 3)
        return val
    return None


def _map_material(raw_value, material_map):
    """Map a material string to schema enum using a mapping dict."""
    if raw_value is None:
        return None
    key = raw_value.lower().strip()
    if key in material_map:
        return material_map[key]
    for pattern, enum_val in material_map.items():
        if pattern in key or key in pattern:
            return enum_val
    return None


def _make_driver_id(manufacturer, model):
    """Create a filesystem-safe driver ID from manufacturer and model."""
    combined = f"{manufacturer}-{model}"
    slug = re.sub(r"[^a-z0-9]+", "-", combined.lower())
    slug = slug.strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug


def _determine_driver_type(specs, category_type=None):
    """
    Determine the driver type from the spec fields or category context.

    soundimports.eu has 'Woofer Type' or 'Tweeter Type' fields in specs.
    """
    if category_type:
        return category_type

    # Check spec fields
    woofer_type = specs.get("Woofer Type", "").lower()
    tweeter_type = specs.get("Tweeter Type", "").lower()

    if tweeter_type:
        return "tweeter"
    if "subwoofer" in woofer_type:
        return "subwoofer"
    if "full" in woofer_type and "range" in woofer_type:
        return "full-range"
    if "mid" in woofer_type and "range" in woofer_type:
        return "midrange"
    if "coaxial" in woofer_type:
        return "coaxial"
    if woofer_type:
        return "woofer"

    return None


# ---------------------------------------------------------------------------
# Category page scraping
# ---------------------------------------------------------------------------


def discover_product_urls(session, category_url, delay, robots_parser,
                          limit=None, manufacturer_filter=None):
    """
    Crawl a category listing page (with pagination) and return product URLs.

    Product URLs are discovered via data-url attributes on product cards.
    Pagination uses the page{N}.html pattern.
    """
    product_urls = []
    page = 1
    seen = set()

    while True:
        if page == 1:
            url = category_url
        else:
            # soundimports.eu pagination: append page{N}.html
            url = category_url.rstrip("/") + f"/page{page}.html"

        if not url.startswith("http"):
            url = BASE_URL + url

        log.info("Fetching category page %d: %s", page, url)
        resp = _fetch_page(session, url, delay, robots_parser)
        if resp is None:
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        # Find product cards via data-url attribute
        found_on_page = 0
        product_divs = soup.find_all("div", attrs={"data-url": True})

        for div in product_divs:
            data_url = div.get("data-url", "")
            # data-url has format: https://.../<slug>.html?format=json
            # Extract the product page URL by removing the query string
            parsed = urllib.parse.urlparse(data_url)
            if not parsed.path.endswith(".html"):
                continue
            product_url = urllib.parse.urlunparse(
                (parsed.scheme, parsed.netloc, parsed.path, "", "", "")
            )

            if product_url in seen:
                continue
            seen.add(product_url)

            # If manufacturer filter is set, check the product title on the card
            if manufacturer_filter:
                title_el = div.find("h3") or div.find("a", class_="title")
                card_text = title_el.get_text(strip=True) if title_el else ""
                if not card_text:
                    # Try the full card text
                    card_text = div.get_text(strip=True)
                if manufacturer_filter.lower() not in card_text.lower():
                    continue

            product_urls.append(product_url)
            found_on_page += 1

            if limit and len(product_urls) >= limit:
                log.info("Reached limit of %d products", limit)
                return product_urls

        # Also find product links via anchor tags as a fallback
        if found_on_page == 0:
            for link in soup.find_all("a", href=True):
                href = link["href"]
                # Match product page URLs: /en/<slug>.html
                if re.match(r"https://www\.soundimports\.eu/en/[a-z0-9][a-z0-9-]+\.html$", href):
                    if href in seen:
                        continue
                    # Exclude category/page links
                    if "/page" in href or "/audio-components/" in href:
                        continue
                    seen.add(href)

                    if manufacturer_filter:
                        link_text = link.get_text(strip=True)
                        if manufacturer_filter.lower() not in link_text.lower():
                            continue

                    product_urls.append(href)
                    found_on_page += 1

                    if limit and len(product_urls) >= limit:
                        log.info("Reached limit of %d products", limit)
                        return product_urls

        log.info(
            "Found %d new products on page %d (total: %d)",
            found_on_page, page, len(product_urls),
        )

        if found_on_page == 0:
            break

        # Check for next page: look for pagination links
        has_next = False
        next_page_url = category_url.rstrip("/") + f"/page{page + 1}.html"
        for a_tag in soup.find_all("a", href=True):
            if f"page{page + 1}" in a_tag["href"]:
                has_next = True
                break

        if not has_next:
            break

        page += 1

    return product_urls


# ---------------------------------------------------------------------------
# Product page parsing
# ---------------------------------------------------------------------------


def _parse_spec_dl(soup):
    """
    Parse the specification definition list from a product page.

    soundimports.eu uses <section id="specs"> containing a <dl> with
    <dt>/<dd> pairs wrapped in <div> elements.

    Returns a dict mapping {label: raw_value_text}.
    """
    specs = {}
    specs_section = soup.find("section", id="specs")
    if specs_section is None:
        return specs

    dl = specs_section.find("dl")
    if dl is None:
        return specs

    # The dl contains <div> elements each with a <dt> and <dd>.
    # CAVEAT: some dt elements have malformed HTML where the <dd> is nested
    # inside the <dt> (no closing </dt> tag). We extract only the direct
    # text content of <dt> to avoid including the <dd> value in the label.
    for div in dl.find_all("div", recursive=False):
        dt = div.find("dt")
        dd = div.find("dd")
        if dt and dd:
            # Get only direct text nodes of dt (not child element text)
            label = "".join(
                str(c) for c in dt.children if isinstance(c, NavigableString)
            ).strip()
            value = dd.get_text(strip=True)
            if label and value:
                specs[label] = value

    # Fallback: if no div wrappers, try direct dt/dd pairs
    if not specs:
        current_dt = None
        for child in dl.children:
            if hasattr(child, "name"):
                if child.name == "dt":
                    current_dt = "".join(
                        str(c) for c in child.children
                        if isinstance(c, NavigableString)
                    ).strip()
                elif child.name == "dd" and current_dt:
                    specs[current_dt] = child.get_text(strip=True)
                    current_dt = None

    return specs


def _extract_json_ld(soup):
    """Extract JSON-LD product data if available.

    soundimports.eu JSON-LD sometimes contains HTML tags (e.g., <br />) and
    unescaped newlines in review descriptions. We sanitize the string and
    use strict=False to handle embedded control characters.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string
        if raw is None:
            continue
        # Sanitize: remove HTML tags that appear inside JSON string values
        sanitized = re.sub(r"<[^>]+>", "", raw)
        try:
            data = json.loads(sanitized, strict=False)
        except (json.JSONDecodeError, TypeError):
            continue

        # JSON-LD can be a dict or a list of dicts
        if isinstance(data, dict) and data.get("@type") == "Product":
            return data
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    return item
    return None


def parse_product_page(soup, product_url, category_type=None):
    """
    Parse a product page and return a driver data dict conforming to the schema.

    Returns None if the page lacks required T/S parameters.
    """
    specs = _parse_spec_dl(soup)
    json_ld = _extract_json_ld(soup)

    if not specs:
        log.info("No specifications found on %s — skipping", product_url)
        return None

    # Extract manufacturer from JSON-LD or infer from product title
    manufacturer = ""
    if json_ld:
        brand = json_ld.get("brand", {})
        if isinstance(brand, dict):
            manufacturer = brand.get("name", "")
        elif isinstance(brand, str):
            manufacturer = brand

    # Extract model from Article number spec field
    model = specs.get("Article number", "")

    # If model is empty, try to extract from product title
    if not model:
        title_el = soup.find("h1")
        if title_el:
            title = title_el.get_text(strip=True)
            # Try to extract model by removing manufacturer prefix
            if manufacturer and title.lower().startswith(manufacturer.lower()):
                model = title[len(manufacturer):].strip()
            else:
                model = title

    if not manufacturer or not model:
        log.warning("Missing manufacturer (%r) or model (%r) on %s",
                    manufacturer, model, product_url)
        return None

    driver_id = _make_driver_id(manufacturer, model)

    # --- Parse T/S parameters ---
    fs_hz = _parse_float(specs.get("Resonant Frequency (Fs)"))
    re_ohm = _parse_float(specs.get("DC Resistance (Re)"))
    le_mh = _parse_float(specs.get("Voice Coil Inductance (Le)"))
    qms = _parse_float(specs.get("Mechanical Q (Qms)"))
    qes = _parse_float(specs.get("Electromagnetic Q (Qes)"))
    qts = _parse_float(specs.get("Total Q (Qts)"))
    vas_liters = _parse_vas(specs.get("Compliance Equivalent Volume (Vas)"))
    cms_raw = _parse_float(specs.get("Mechanical Compliance of Suspension (Cms)"))
    cms_m_per_n = _convert_mm_per_n_to_m_per_n(cms_raw)
    bl_tm = _parse_float(specs.get("BL Product (BL)"))
    mms_g = _parse_float(specs.get("Diaphragm Mass Inc. Airload (Mms)"))
    mmd_g = _parse_float(specs.get("Diaphragm Mass Excl. Airload (Mmd)"))
    xmax_mm = _parse_float(specs.get("Maximum Linear Excursion (Xmax)"))
    sd_cm2 = _parse_float(specs.get("Surface Area of Cone (Sd)"))

    # Efficiency
    eta0_raw = specs.get("Reference Efficiency (η0)") or specs.get("Reference Efficiency")
    eta0_percent = _parse_float(eta0_raw)

    # Volume displacement
    vd_raw = specs.get("Maximum Volume Displacement (Vd)")
    vd_cm3 = _parse_float(vd_raw)

    # --- Parse impedance ---
    z_nom_ohm = _parse_impedance(specs.get("Impedance (Z)"))

    # --- Parse sensitivity ---
    sens_raw = specs.get("Sensitivity (SPL at 1m / 2.83V)")
    sensitivity_db_2v83_1m = _parse_sensitivity(sens_raw)

    # --- Parse nominal diameter ---
    diameter_raw = specs.get("Nominal Diameter") or specs.get("Cone / Dome Diameter")
    nominal_diameter_in = _parse_nominal_diameter(diameter_raw)

    # --- Parse voice coil diameter ---
    vc_raw = specs.get("Voice Coil Diameter")
    voice_coil_diameter_mm = None
    if vc_raw:
        voice_coil_diameter_mm = _parse_dimension_to_mm(vc_raw)

    # --- Power handling ---
    pe_max_watts = _parse_float(specs.get("Power Handling (RMS)"))
    pe_peak_watts = _parse_float(specs.get("Power Handling (max)"))

    # --- Materials ---
    cone_material = _map_material(
        specs.get("Cone / Diaphragm Material") or specs.get("Diaphragm Material"),
        CONE_MATERIAL_MAP,
    )
    surround_material = _map_material(
        specs.get("Surround Material"),
        SURROUND_MATERIAL_MAP,
    )
    magnet_material = _map_material(
        specs.get("Magnet Material"),
        MAGNET_MATERIAL_MAP,
    )

    # --- Mounting dimensions ---
    flange_raw = specs.get("Overall Outside Diameter")
    flange_diameter_mm = _parse_dimension_to_mm(flange_raw)

    cutout_raw = specs.get("Baffle Cutout Diameter") or specs.get("Cutout Diameter")
    cutout_diameter_mm = _parse_dimension_to_mm(cutout_raw)

    depth_raw = specs.get("Overall Depth") or specs.get("Depth")
    overall_depth_mm = _parse_dimension_to_mm(depth_raw)

    bolt_circle_raw = specs.get("Bolt Circle Diameter")
    bolt_circle_diameter_mm = _parse_bolt_circle(bolt_circle_raw)

    bolt_count = None
    bolt_count_raw = specs.get("# Mounting Holes")
    if bolt_count_raw:
        try:
            bolt_count = int(_parse_float(bolt_count_raw))
        except (TypeError, ValueError):
            pass

    # --- Weight ---
    weight_raw = specs.get("Weight")
    weight_kg = _parse_weight_to_kg(weight_raw)

    # --- Driver type ---
    driver_type = _determine_driver_type(specs, category_type)

    # --- Required T/S fields check ---
    # We need at least some T/S data to be useful
    if fs_hz is None and re_ohm is None and z_nom_ohm is None and qts is None:
        log.info(
            "All required T/S fields are null for %s (%s %s) — skipping",
            product_url, manufacturer, model,
        )
        return None

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
            "notes": f"Scraped from soundimports.eu.",
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
    """Find datasheet PDF URLs on a product page."""
    pdf_urls = []
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        if href.lower().endswith(".pdf"):
            pdf_urls.append(href)
    return pdf_urls


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

    # Download datasheet PDFs
    pdf_urls = find_datasheet_urls(soup)
    if pdf_urls:
        data_dir = os.path.join(output_dir, driver_id, "data")
        for pdf_url in pdf_urls:
            pdf_filename = os.path.basename(
                urllib.parse.unquote(urllib.parse.urlparse(pdf_url).path)
            )
            pdf_path = os.path.join(data_dir, pdf_filename)
            if download_file(session, pdf_url, pdf_path, delay, robots_parser):
                driver_data["metadata"]["datasheet_file"] = pdf_filename
                break  # Only store first successful PDF

    # Write YAML
    yaml_path = write_driver_yaml(driver_data, output_dir)
    return driver_id, yaml_path


def scrape_category(session, category_url, output_dir, delay, robots_parser,
                    category_type=None, limit=None, manufacturer_filter=None):
    """
    Scrape all drivers from a category listing page.

    Returns (successes, failures) where each is a list of (driver_id, detail).
    """
    log.info("Discovering products from category: %s", category_url)
    product_urls = discover_product_urls(
        session, category_url, delay, robots_parser,
        limit=limit, manufacturer_filter=manufacturer_filter,
    )
    log.info("Found %d product URLs to scrape", len(product_urls))

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
        description="Scrape speaker driver T/S parameters from soundimports.eu",
    )
    parser.add_argument(
        "--manufacturer",
        help="Filter by manufacturer name (case-insensitive substring match)",
    )
    parser.add_argument(
        "--type",
        choices=["woofer", "midrange", "tweeter", "subwoofer", "full-range", "coaxial"],
        help="Driver type category to scrape",
    )
    parser.add_argument(
        "--category-url",
        help="Direct category URL to scrape (overrides --type)",
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
        log.error("Either --type or --category-url is required")
        return 1

    if not category_url.startswith("http"):
        category_url = BASE_URL + category_url

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    log.info("Output directory: %s", output_dir)
    log.info("Delay between requests: %.1fs", args.delay)
    if args.manufacturer:
        log.info("Manufacturer filter: %s", args.manufacturer)

    session = _create_session()
    robots_parser = _check_robots_txt(session)

    successes, failures = scrape_category(
        session, category_url, output_dir, args.delay, robots_parser,
        category_type=category_type, limit=args.limit,
        manufacturer_filter=args.manufacturer,
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
