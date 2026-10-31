import logging
import re
import statistics
from typing import List, Optional
import urllib.parse
from bs4 import BeautifulSoup

from backend.models import EbaySoldStats, VerificationLinks

logger = logging.getLogger(__name__)


class EbayService:
    def __init__(self, default_eur_to_chf: float = 0.94):
        self.default_eur_to_chf = default_eur_to_chf

    def build_verification_links(self, query: str) -> VerificationLinks:
        q = urllib.parse.quote_plus(query.strip())
        return VerificationLinks(
            ebay_sold_url=f"https://www.ebay.de/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1",
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
        
        # Anti-bot detection check
        if "splashui/challenge" in html or "Pardon Our Interruption" in html:
            logger.warning(f"eBay anti-bot challenge detected for query: {query}")
            return EbaySoldStats(query=query, sample_count=0, exchange_rate=rate)

        soup = BeautifulSoup(html, "lxml")
        items = soup.select(".s-item, .s-card")
        prices: List[float] = []

        for item in items:
            title_el = item.select_one(".s-item__title, .s-card__title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if "Shop on eBay" in title or not title:
                continue

            price_el = item.select_one(".s-item__price, .s-card__price")
            if not price_el:
                continue
            price_text = price_el.get_text(strip=True)
            price_val = self._parse_price_text(price_text)
            if price_val is not None:
                prices.append(price_val)

        if not prices:
            return EbaySoldStats(query=query, sample_count=0, exchange_rate=rate)

        min_eur = min(prices)
        max_eur = max(prices)
        sample_count = len(prices)

        # Apply trimming for median calculation if we have enough samples
        calc_prices = sorted(prices)
        if sample_count >= 10:
            trim_k = int(sample_count * 0.10)
            if trim_k > 0:
                calc_prices = calc_prices[trim_k:-trim_k]

        median_eur = round(float(statistics.median(calc_prices)), 2)
        median_chf = round(median_eur * rate, 2)

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

        # Try curl_cffi first for TLS impersonation
        try:
            from curl_cffi.requests import AsyncSession
            async with AsyncSession(impersonate="chrome") as session:
                resp = await session.get(url, headers=headers, timeout=8.0)
                if resp.status_code == 200:
                    return self.parse_sold_html(resp.text, query=query, eur_to_chf=rate)
        except Exception as e:
            logger.debug(f"curl_cffi fetch failed ({e}), trying httpx fallback")

        # Fallback to httpx
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    return self.parse_sold_html(resp.text, query=query, eur_to_chf=rate)
        except Exception as e:
            logger.warning(f"Failed to fetch eBay sold listings for query '{query}': {e}")

        return EbaySoldStats(query=query, sample_count=0, exchange_rate=rate)
