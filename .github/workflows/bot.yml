import urllib.request
import xml.etree.ElementTree as ET
import json
import os

WEBHOOK_URL = "https://discord.com/api/webhooks/1567194433563398264/v9SIVA2FryrdOCx5RlxxbLsCpqbW3MJWI9TdRpePDd4yvg0f0t525Dp03GULH5YnFgzY"
HISTORY_FILE = "sent_news.txt"

RSS_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.skysports.com/rss/12040"
]

def load_sent_news():
    """Wczytuje listę wcześniej wysłanych linków z pliku."""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_sent_news(sent_links):
    """Zapisuje zaktualizowaną listę wysłanych linków."""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for link in sent_links:
            f.write(f"{link}\n")

def send_to_discord(title, link, source):
    """Wysyła powiadomienie na Discorda."""
    message = {
        "content": f"🚨 **NOWY NEWS PIŁKARSKI ({source})**\n\n**{title}**\n🔗 Czytaj więcej: {link}"
    }
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps(message).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    )
    try:
        with urllib.request.urlopen(req) as response:
            if response.status in (200, 204):
                print(f"Pomyślnie wysłano: {title}")
    except Exception as e:
        print(f"Błąd wysyłki na Discorda: {e}")

def check_news():
    sent_links = load_sent_news()
    new_sent_count = 0

    for url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                xml_data = response.read()
            
            root = ET.fromstring(xml_data)
            source = "BBC Sport" if "bbci" in url else "Sky Sports"
            
            # Sprawdzamy pierwsze 5 najnowszych wiadomości z każdego źródła
            items = root.findall('.//item')[:5]
            for item in reversed(items):  # Wysyłamy od najstarszego do najnowszego z tej piątki
                title_elem = item.find('title')
                link_elem = item.find('link')
                
                if title_elem is not None and link_elem is not None:
                    title = title_elem.text.strip()
                    link = link_elem.text.strip()
                    
                    if link not in sent_links:
                        send_to_discord(title, link, source)
                        sent_links.add(link)
                        new_sent_count += 1
                        
        except Exception as e:
            print(f"Błąd podczas przetwarzania {url}: {e}")

    if new_sent_count > 0:
        save_sent_news(sent_links)
        print(f"Zapisano {new_sent_count} nowych wiadomości do historii.")
    else:
        print("Brak nowych newsów do wysłania.")

if __name__ == "__main__":
    check_news()
