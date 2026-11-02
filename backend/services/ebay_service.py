import logging
import re
import statistics
import sys
from typing import List, Optional
import urllib.parse
from bs4 import BeautifulSoup

from backend.models import EbaySoldStats, VerificationLinks

logger = logging.getLogger("seller.ebay")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


class EbayService:
    def __init__(self, default_eur_to_chf: float = 0.94):
        self.default_eur_to_chf = default_eur_to_chf

    def build_verification_links(self, query: str) -> VerificationLinks:
        q = urllib.parse.quote_plus(query.strip())
        return VerificationLinks(
            ebay_sold_url=f"https://www.ebay.de/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1&LH_ItemCondition=3000",
            kleinanzeigen_search_url=f"https://www.kleinanzeigen.de/s-{q}/k0",
            idealo_url=f"https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={q}",
            ricardo_search_url=f"https://www.ricardo.ch/de/s/{q}",
            toppreise_url=f"https://www.toppreise.ch/produktsuche?q={q}",
            digitec_url=f"https://www.digitec.ch/de/search?q={q}",
        )

    def _parse_price_text(self, text: str) -> Optional[float]:
        # Ignore price ranges (e.g. "EUR 100,00 bis EUR 200,00")
        lower = text.lower()
        if "bis" in lower or " to " in lower or " - " in lower:
            return None

        # Extract numeric price part: e.g. "EUR 150,00" or "160,00 €" or "1.250,50"
        # Match digits, dots, commas
        match = re.search(r"(\d+(?:[.,]\d+)*)", text)
        if not match:
            return None

        num_str = match.group(1)
        # German notation: 1.250,50 -> 1250.50
        if "," in num_str and "." in num_str:
            num_str = num_str.replace(".", "").replace(",", ".")
        elif "," in num_str:
            num_str = num_str.replace(",", ".")

        try:
            val = float(num_str)
            return val if val > 0 else None
        except ValueError:
            return None

    def parse_sold_html(
        self, html: str, query: str, eur_to_chf: Optional[float] = None
    ) -> EbaySoldStats:
        rate = eur_to_chf if eur_to_chf is not None else self.default_eur_to_chf

        soup = BeautifulSoup(html, "lxml")
        page_title = soup.title.get_text(strip=True) if soup.title else "(kein <title>)"

        logger.debug("=" * 70)
        logger.debug("--- [EBAY SOLD PARSER DEBUG START] ---")
        logger.debug(
            f"Query: '{query}' | HTML-Länge: {len(html)} Zeichen | Seitentitel: '{page_title}'"
        )

        # Anti-bot detection check
        if "splashui/challenge" in html or "Pardon Our Interruption" in html:
            logger.warning(
                f"[EbayService] eBay Anti-Bot-Challenge ('splashui/challenge' / Captcha) erkannt für Query: '{query}'"
            )
            logger.debug(
                f"[EbayService] Challenge HTML-Snippet (erste 400 Zeichen): {html[:400]!r}"
            )
            logger.debug("--- [EBAY SOLD PARSER DEBUG END] ---")
            logger.debug("=" * 70)
            return EbaySoldStats(query=query, sample_count=0, exchange_rate=rate)

        items = soup.select(".s-item, .s-card")
        logger.debug(
            f"[EbayService] Gefundene DOM-Elemente ('.s-item, .s-card'): {len(items)}"
        )
        prices: List[float] = []
        skipped_placeholder = 0
        skipped_range_or_invalid = 0

        for item in items:
            title_el = item.select_one(".s-item__title, .s-card__title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if "Shop on eBay" in title or not title:
                skipped_placeholder += 1
                continue

            price_el = item.select_one(".s-item__price, .s-card__price")
            if not price_el:
                continue
            price_text = price_el.get_text(strip=True)
            price_val = self._parse_price_text(price_text)
            if price_val is not None:
                prices.append(price_val)
                logger.debug(
                    f"[EbayService] Treffer #{len(prices)}: '{title[:65]}' -> '{price_text}' ({price_val} EUR)"
                )
            else:
                skipped_range_or_invalid += 1
                logger.debug(
                    f"[EbayService] Übersprungen (Preisspanne/ungültig): '{title[:50]}' -> '{price_text}'"
                )

        if not prices:
            logger.warning(
                f"[EbayService] 0 gültige Verkaufspreise für '{query}' gefunden "
                f"(DOM-Elemente: {len(items)}, Platzhalter übersprungen: {skipped_placeholder}, "
                f"Spannen übersprungen: {skipped_range_or_invalid}, Seitentitel: '{page_title}')."
            )
            logger.debug("--- [EBAY SOLD PARSER DEBUG END] ---")
            logger.debug("=" * 70)
            return EbaySoldStats(query=query, sample_count=0, exchange_rate=rate)

        min_eur = min(prices)
        max_eur = max(prices)
        sample_count = len(prices)

        # Apply trimming for median calculation if >= 4 samples are found
        calc_prices = sorted(prices)
        if sample_count >= 4:
            trim_k = max(1, int(sample_count * 0.10))
            if len(calc_prices) - (2 * trim_k) >= 1:
                calc_prices = calc_prices[trim_k:-trim_k]

        median_eur = round(float(statistics.median(calc_prices)), 2)
        median_chf = round(median_eur * rate, 2)

        logger.info(
            f"[EbayService] Statistik für '{query}': {sample_count} verkaufte Artikel | "
            f"Median: {median_eur} EUR ({median_chf} CHF) | Spanne: {min_eur}–{max_eur} EUR"
        )
        logger.debug(
            f"[EbayService] Extrahierte Rohpreise (sortiert): {sorted(prices)} | "
            f"Nach 10%-Trimming für Median genutzt: {calc_prices}"
        )
        logger.debug("--- [EBAY SOLD PARSER DEBUG END] ---")
        logger.debug("=" * 70)

        return EbaySoldStats(
            query=query,
            sample_count=sample_count,
            min_eur=round(min_eur, 2),
            max_eur=round(max_eur, 2),
            median_eur=median_eur,
            median_chf=median_chf,
            exchange_rate=rate,
        )

    async def fetch_sold_stats(
        self, query: str, eur_to_chf: Optional[float] = None
    ) -> EbaySoldStats:
        rate = eur_to_chf if eur_to_chf is not None else self.default_eur_to_chf
        url = self.build_verification_links(query).ebay_sold_url
        headers = {
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        }

        logger.info(f"[EbayService] Starte eBay-DE Sold-Abfrage für '{query}'...")
        logger.debug(f"[EbayService] Ziel-URL: {url} (Wechselkurs EUR->CHF: {rate})")

        # Try curl_cffi first for TLS impersonation
        try:
            from curl_cffi.requests import AsyncSession
            logger.debug("[EbayService] Versuche Abruf via curl_cffi (impersonate='chrome')...")
            async with AsyncSession(impersonate="chrome") as session:
                resp = await session.get(url, headers=headers, timeout=8.0)
                final_url = getattr(resp, "url", url)
                logger.debug(
                    f"[EbayService] curl_cffi Antwort: HTTP {resp.status_code} | "
                    f"Finale URL: {final_url} | Länge: {len(resp.text)} Zeichen"
                )
                if resp.status_code == 200:
                    return self.parse_sold_html(resp.text, query=query, eur_to_chf=rate)
                logger.warning(
                    f"[EbayService] curl_cffi lieferte HTTP {resp.status_code} (URL: {final_url})"
                )
        except Exception as e:
            logger.debug(f"[EbayService] curl_cffi Abruf fehlgeschlagen ({type(e).__name__}: {e}), versuche httpx Fallback...")

        # Fallback to httpx
        try:
            import httpx
            logger.debug("[EbayService] Versuche Abruf via httpx (follow_redirects=True)...")
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                logger.debug(
                    f"[EbayService] httpx Antwort: HTTP {resp.status_code} | "
                    f"Finale URL: {resp.url} | Länge: {len(resp.text)} Zeichen"
                )
                if resp.status_code == 200:
                    return self.parse_sold_html(resp.text, query=query, eur_to_chf=rate)
                logger.warning(
                    f"[EbayService] httpx lieferte HTTP {resp.status_code} (URL: {resp.url})"
                )
        except Exception as e:
            logger.warning(f"[EbayService] Fehler beim Abruf der eBay-Verkaufsdaten für '{query}': {e}")

        logger.warning(f"[EbayService] Abfrage für '{query}' beendet ohne Daten (sample_count=0).")
        return EbaySoldStats(query=query, sample_count=0, exchange_rate=rate)
