import urllib.request
import xml.etree.ElementTree as ET
import json
import os
import base64
import re
import html
from datetime import datetime

WEBHOOK_URL = "https://discord.com/api/webhooks/1567194433563398264/v9SIVA2FryrdOCx5RlxxbLsCpqbW3MJWI9TdRpePDd4yvg0f0t525Dp03GULH5YnFgzY"
HISTORY_FILE = "sent_news.txt"

# KONFIGURACJA REPOZYTORIUM STRONY (ZMIEŃ 'TWOJ_NICK' NA SWOJĄ NAZWĘ UŻYTKOWNIKA GITHUB!)
GITHUB_REPO = "kamil1946/strona-bot-pilkarski"
GITHUB_FILE_PATH = "news.json"
GH_TOKEN = os.environ.get("GH_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

RSS_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.skysports.com/rss/12040"
]

def load_sent_news():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_sent_news(sent_links):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for link in sent_links:
            f.write(f"{link}\n")

def detect_category(title, full_text=""):
    t = (title + " " + full_text[:400]).lower()
    if any(k in t for k in ["premier league", "arsenal", "liverpool", "man utd", "manchester united", "man city", "manchester city", "chelsea", "tottenham", "newcastle", "aston villa", "everton", "west ham"]):
        return "PL", "Premier League", "bg-purple-600"
    if any(k in t for k in ["la liga", "real madrid", "real madryt", "barcelona", "atletico", "mbappe", "vinicius", "yamal", "sevilla"]):
        return "LL", "La Liga", "bg-red-600"
    if any(k in t for k in ["champions league", "liga mistrzów", "uefa", "europa league", "liga europy"]):
        return "CL", "Liga Mistrzów", "bg-blue-600"
    if any(k in t for k in ["world cup", "mistrzostwa świata", "euro", "england", "anglia", "poland", "polska", "france", "francja", "spain", "hiszpania", "germany", "niemcy", "brazil", "argentina", "reprezentacj"]):
        return "REP", "Reprezentacje", "bg-emerald-600"
    return "WORLD", "Piłka Nożna", "bg-purple-600"

def clean_html(raw_html):
    if not raw_html:
        return ""
    text = re.sub(r'<[^<]+?>', '', raw_html)
    return html.unescape(text).strip()

def fetch_source_facts(url, fallback_summary):
    """Pobiera tekst ze źródła wyłącznie jako kontekst do streszczenia faktów przez AI."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=10) as res:
            page_html = res.read().decode('utf-8', errors='ignore')

        page_html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', page_html, flags=re.DOTALL | re.IGNORECASE)
        raw_paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', page_html, flags=re.DOTALL | re.IGNORECASE)

        paragraphs = []
        for p in raw_paragraphs:
            text = clean_html(p)
            if len(text) >= 60:
                paragraphs.append(text)
            if len(paragraphs) >= 8:
                break

        if paragraphs:
            return "\n".join(paragraphs)
    except Exception as e:
        print(f"Nie udało się odczytać źródła {url}: {e}")
    return fallback_summary

def summarize_in_polish_with_gemini(orig_title, source_text, source_name):
    """Tworzy krótkie, autorskie podsumowanie faktów po polsku (bez kopiowania artykułu)."""
    if not GEMINI_API_KEY:
        return orig_title, source_text[:180], f"<p>{source_text[:250]}...</p>"

    prompt = f"""Jesteś redaktorem polskiego portalu piłkarskiego PITCH ZONE.
Na podstawie poniższych informacji ze źródła ({source_name}) przygotuj krótkie, autorskie podsumowanie faktów po polsku własnymi słowami (nie kopiuj dosłownie zdań z oryginału).

Wymagania:
1. Podaj konkretne fakty: kto, co się stało, kiedy, jaki klub/liga, szczegóły kontuzji/transferu/wyniku.
2. Zwróć odpowiedź WYŁĄCZNIE jako czysty obiekt JSON (bez znaczników markdown ```json) z trzema polami:
- "title": krótki, dynamiczny nagłówek po polsku (max 85 znaków)
- "summary": zajawka 1-2 zdania po polsku (max 180 znaków)
- "paragraphs": lista 2 lub 3 krótkich akapitów po polsku opisujących kluczowe fakty

Oryginalny tytuł: {orig_title}
Materiał źródłowy:
{source_text[:3000]}
"""

    api_url = f"[https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=](https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=){GEMINI_API_KEY}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4}
    }).encode('utf-8')

    try:
        req = urllib.request.Request(api_url, data=payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=20) as res:
            data = json.loads(res.read().decode('utf-8'))
            raw_reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            # Usuwamy ewentualne bloki ```json ... ```
            raw_reply = re.sub(r'^```json\s*|\s*```$', '', raw_reply, flags=re.IGNORECASE).strip()
            parsed = json.loads(raw_reply)

            pl_title = parsed.get("title", orig_title)
            pl_summary = parsed.get("summary", "")
            paragraphs = parsed.get("paragraphs", [])
            html_body = "".join(f"<p>{p}</p>" for p in paragraphs) if paragraphs else f"<p>{pl_summary}</p>"
            return pl_title, pl_summary, html_body
    except Exception as e:
        print(f"Błąd Gemini AI (używam fallbacku): {e}")
        return orig_title, source_text[:180], f"<p>{source_text[:220]}...</p>"

def send_to_discord(title, summary, link, source):
    message = {
        "content": f"🚨 **NOWY NEWS PIŁKARSKI ({source})**\n\n**{title}**\n{summary}\n\n🔗 Pełny artykuł źródłowy: {link}"
    }
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps(message).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    )
    try:
        with urllib.request.urlopen(req) as response:
            if response.status in (200, 204):
                print(f"Wysłano na Discorda: {title}")
    except Exception as e:
        print(f"Błąd wysyłki na Discorda: {e}")

def push_news_to_website(new_articles):
    if not GH_TOKEN or not new_articles:
        print("Pominięto aktualizację strony (brak GH_TOKEN lub brak nowych artykułów).")
        return

    api_url = f"[https://api.github.com/repos/](https://api.github.com/repos/){GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PitchZone-Bot"
    }

    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as res:
            file_data = json.loads(res.read().decode('utf-8'))
            sha = file_data["sha"]
            existing_news = json.loads(base64.b64decode(file_data["content"]).decode('utf-8'))

        updated_news = new_articles + existing_news
        updated_news = updated_news[:25]

        encoded_content = base64.b64encode(
            json.dumps(updated_news, ensure_ascii=False, indent=2).encode('utf-8')
        ).decode('utf-8')

        payload = json.dumps({
            "message": f"Auto-news PL: dodano {len(new_articles)} streszczeń",
            "content": encoded_content,
            "sha": sha
        }).encode('utf-8')

        put_req = urllib.request.Request(api_url, data=payload, headers=headers, method="PUT")
        with urllib.request.urlopen(put_req) as put_res:
            if put_res.status in (200, 201):
                print(f"Zaktualizowano news.json na stronie (+{len(new_articles)} newsów)!")
    except Exception as e:
        print(f"Błąd aktualizacji news.json na GitHubie: {e}")

def check_news():
    sent_links = load_sent_news()
    new_sent_count = 0
    website_batch = []

    for url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                xml_data = response.read()
            
            root = ET.fromstring(xml_data)
            source = "BBC Sport" if "bbci" in url else "Sky Sports"
            
            items = root.findall('.//item')[:4]
            for item in reversed(items):
                title_elem = item.find('title')
                link_elem = item.find('link')
                desc_elem = item.find('description')
                
                if title_elem is not None and link_elem is not None:
                    orig_title = clean_html(title_elem.text)
                    link = link_elem.text.strip()
                    rss_summary = clean_html(desc_elem.text) if desc_elem is not None else ""
                    
                    img_url = "[https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1000&q=80](https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1000&q=80)"
                    for child in item:
                        if 'thumbnail' in child.tag or 'content' in child.tag or 'enclosure' in child.tag:
                            if child.attrib.get('url'):
                                img_url = child.attrib.get('url')
                                break

                    if link not in sent_links:
                        source_context = fetch_source_facts(link, rss_summary)
                        pl_title, pl_summary, pl_html_body = summarize_in_polish_with_gemini(orig_title, source_context, source)

                        send_to_discord(pl_title, pl_summary, link, source)
                        sent_links.add(link)
                        new_sent_count += 1

                        cat_code, badge_text, badge_color = detect_category(orig_title + " " + pl_title, pl_html_body)
                        now_str = datetime.now().strftime("%d.%m • %H:%M")

                        website_batch.insert(0, {
                            "category": cat_code,
                            "badge": badge_text,
                            "badgeColor": badge_color,
                            "time": now_str,
                            "source": f"Na podstawie: {source}",
                            "img": img_url,
                            "title": pl_title,
                            "summary": pl_summary,
                            "content": f"{pl_html_body}<p class='pt-3 border-t border-gray-100 dark:border-border text-xs text-gray-400'>Podsumowanie faktów opracowane na podstawie publikacji {source}. <a href='{link}' target='_blank' rel='noopener' class='text-purple-500 font-bold underline ml-1'>Przeczytaj oryginalny artykuł →</a></p>"
                        })
                        
        except Exception as e:
            print(f"Błąd podczas przetwarzania {url}: {e}")

    if new_sent_count > 0:
        save_sent_news(sent_links)
        push_news_to_website(website_batch)
        print(f"Zapisano {new_sent_count} nowych podsumowań.")
    else:
        print("Brak nowych newsów do wysłania.")

if __name__ == "__main__":
    check_news()
