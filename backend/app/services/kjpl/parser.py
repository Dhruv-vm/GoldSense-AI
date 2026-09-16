import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .schemas import KJPLRate


def _extract_number(text: str) -> float | None:
    match = re.search(r"\d[\d,]*(?:\.\d+)?", text)

    if not match:
        return None

    return float(match.group(0).replace(",", ""))


def _extract_gold_with_gst(soup: BeautifulSoup) -> float | None:
    """
    Extract the published GOLD MJDTA rate including GST
    directly from the KJPL HTML.
    """

    headings = soup.find_all("strong")

    for heading in headings:
        text = heading.get_text(" ", strip=True).upper()

        if "MJDTA RATE (WITH GST)" not in text:
            continue

        table = heading.find_parent("table")

        if not table:
            continue

        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])

            if not cells:
                continue

            row_text = " ".join(
                cell.get_text(" ", strip=True)
                for cell in cells
            ).upper()

            if "GOLD" not in row_text:
                continue

            # Extract numbers from the row.
            values = []

            for cell in cells:
                value = _extract_number(
                    cell.get_text(" ", strip=True)
                )

                if value is not None:
                    values.append(value)

            if values:
                return values[-1]

    return None
def parse_kjpl_html(html: str) -> KJPLRate:
    soup = BeautifulSoup(html, "html.parser")

    gold_element = soup.select_one(".gold-rate")
    silver_element = soup.select_one(".silver-rate")
    time_element = soup.select_one(".mjdma_data")

    if not gold_element:
        raise ValueError(
            "KJPL MJDTA gold rate not found. "
            "The website structure may have changed."
        )

    gold_mjdta = _extract_number(
        gold_element.get_text(" ", strip=True)
    )

    if gold_mjdta is None or gold_mjdta <= 0:
        raise ValueError("Invalid KJPL MJDTA gold rate.")

    silver_mjdta = None

    if silver_element:
        silver_mjdta = _extract_number(
            silver_element.get_text(" ", strip=True)
        )

    source_updated_time = None

    if time_element:
        source_updated_time = time_element.get_text(
            " ",
            strip=True,
        )

    gold_with_gst = _extract_gold_with_gst(soup)

    return KJPLRate(
        gold_mjdta=gold_mjdta,
        silver_mjdta=silver_mjdta,
        gold_with_gst=gold_with_gst,
        source_updated_time=source_updated_time,
        observed_at=datetime.now(ZoneInfo("Asia/Kolkata")),
    )