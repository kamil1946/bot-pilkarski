import urllib.request
import xml.etree.ElementTree as ET
import json
import time

WEBHOOK_URL = "https://discord.com/api/webhooks/1567194433563398264/v9SIVA2FryrdOCx5RlxxbLsCpqbW3MJWI9TdRpePDd4yvg0f0t525Dp03GULH5YnFgzY"

# Kanały RSS z newsami piłkarskimi (BBC Sport & Sky Sports)
RSS_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.skysports.com/rss/12040"
]

def send_to_discord(title, link, source):
    message = {
        "content": f"🚨 **NOWY NEWS PIŁKARSKI ({source})**\n\n**{title}**\n🔗 Czytaj więcej: {link}"
    }
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps(message).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    )
    try:
        urllib.request.urlopen(req)
        print(f"Wysłano: {title}")
    except Exception as e:
        print(f"Błąd wysyłki: {e}")

def check_news():
    for url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            xml_data = urllib.request.urlopen(req).read()
            root = ET.fromstring(xml_data)
            
            # Pobierz najnowszy artykuł z kanału
            item = root.find('.//item')
            if item is not None:
                title = item.find('title').text
                link = item.find('link').text
                source = "BBC Sport" if "bbci" in url else "Sky Sports"
                send_to_discord(title, link, source)
                break
        except Exception as e:
            print(f"Błąd pobierania {url}: {e}")

if __name__ == "__main__":
    check_news()
