import feedparser
import logging
from typing import List

class NewsScraper:
    def __init__(self):
        # Menggunakan sumber RSS yang populer (CoinTelegraph)
        self.rss_urls = [
            "https://cointelegraph.com/rss"
        ]
        
    def fetch_latest_news(self, limit: int = 3) -> List[str]:
        """Mengambil judul-judul berita terbaru."""
        headlines = []
        for url in self.rss_urls:
            try:
                feed = feedparser.parse(url)
                # Ambil beberapa berita teratas dari tiap feed
                for entry in feed.entries[:limit]:
                    headlines.append(entry.title)
            except Exception as e:
                logging.error(f"Gagal menarik berita dari {url}: {e}")
        return headlines

if __name__ == "__main__":
    scraper = NewsScraper()
    news = scraper.fetch_latest_news()
    print("Berita Terbaru:")
    for n in news:
        print("-", n)
