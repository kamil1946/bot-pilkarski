import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import json
import os
import base64
import re
import html
from datetime import datetime

PROTO = "https" + "://"
WEBHOOK_URL = PROTO + "discord.com/api/webhooks/1567194433563398264/v9SIVA2FryrdOCx5RlxxbLsCpqbW3MJWI9TdRpePDd4yvg0f0t525Dp03GULH5YnFgzY"
HISTORY_FILE = "sent_news.txt"

GITHUB_REPO = "kamil1946/strona-bot-pilkarski"
GITHUB_FILE_PATH = "news.json"
GH_TOKEN = os.environ.get("GH_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

RSS_FEEDS = [
    PROTO + "feeds.bbci.co.uk/sport/football/rss.xml",
    PROTO + "www.skysports.com/rss/11095"
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
    t = (title + " " + full_text[:500]).lower()
    if any(k in t for k in ["premier league", "arsenal", "liverpool", "man utd", "manchester united", "man city", "manchester city", "chelsea", "tottenham", "newcastle", "aston villa", "everton", "west ham", "crystal palace", "brighton", "fulham", "bournemouth", "wolves"]):
        return "PL", "Premier League", "bg-purple-600"
    if any(k in t for k in ["la liga", "real madrid", "real madryt", "barcelona", "atletico", "mbappe", "vinicius", "yamal", "sevilla", "espanyol", "athletic"]):
        return "LL", "La Liga", "bg-red-600"
    if any(k in t for k in ["champions league", "liga mistrzów", "uefa", "europa league", "liga europy"]):
        return "CL", "Liga Mistrzów", "bg-blue-600"
    if any(k in t for k in ["world cup", "mistrzostwa świata", "euro", "england", "anglia", "poland", "polska", "france", "francja", "spain", "hiszpania", "germany", "niemcy", "brazil", "argentina", "reprezentacj", "scotland", "szkocj"]):
        return "REP", "Reprezentacje", "bg-emerald-600"
    return "WORLD", "Piłka Nożna", "bg-purple-600"

def clean_html(raw_html):
    if not raw_html:
        return ""
    text = re.sub(r'<[^<]+?>', '', raw_html)
    return html.unescape(text).strip()

def fetch_source_facts(url, fallback_summary):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=12) as res:
            page_html = res.read().decode('utf-8', errors='ignore')

        page_html = re.sub(r'<(script|style|nav|header|footer)[^>]*>.*?</\1>', '', page_html, flags=re.DOTALL | re.IGNORECASE)
        raw_paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', page_html, flags=re.DOTALL | re.IGNORECASE)

        paragraphs = []
        for p in raw_paragraphs:
            text = clean_html(p)
            if len(text) >= 100 and "football f1" not in text.lower() and "cookie" not in text.lower():
                if text not in paragraphs:
                    paragraphs.append(text)
            if len(paragraphs) >= 10:
                break

        if paragraphs:
            return "\n".join(paragraphs)
    except Exception as e:
        print(f"Nie udało się odczytać źródła {url}: {e}")
    return fallback_summary

def summarize_in_polish_with_gemini(orig_title, source_text, source_name):
    if not GEMINI_API_KEY:
        print("BŁĄD: Brak klucza GEMINI_API_KEY!")
        return orig_title, source_text[:180], f"<p>{source_text[:300]}</p>"

    prompt = (
        f"Jesteś redaktorem polskiego portalu piłkarskiego PITCH ZONE.\n"
        f"Na podstawie poniższego artykułu ze źródła ({source_name}) napisz konkretne, autorskie podsumowanie faktów po polsku własnymi słowami (nie kopiuj dosłownie zdań z oryginału).\n\n"
        f"Wymagania:\n"
        f"1. Wyciągnij najważniejsze detale z tekstu: nazwiska piłkarzy i trenerów, nazwy klubów, dokładny powód (np. jaka kontuzja, na ile wypada, jaki wynik, co dokładnie powiedział trener).\n"
        f"2. Zwróć odpowiedź WYŁĄCZNIE jako czysty obiekt JSON (bez znaczników markdown) z trzema polami:\n"
        f'- "title": dynamiczny nagłówek po polsku (max 85 znaków)\n'
        f'- "summary": zajawka 1-2 zdania po polsku z głównym faktem (max 190 znaków)\n'
        f'- "paragraphs": lista 3 konkretnych akapitów po polsku opisujących szczegóły wydarzenia\n\n'
        f"Oryginalny tytuł: {orig_title}\n"
        f"Treść artykułu źródłowego:\n{source_text[:4000]}"
    )

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4}
    }).encode('utf-8')

    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]

    for model_name in models_to_try:
        api_url = PROTO + f"generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        try:
            req = urllib.request.Request(api_url, data=payload, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=25) as res:
                data = json.loads(res.read().decode('utf-8'))
                raw_reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                raw_reply = re.sub(r'^```json\s*|\s*```$', '', raw_reply, flags=re.IGNORECASE).strip()
                parsed = json.loads(raw_reply)

                pl_title = parsed.get("title", orig_title)
                pl_summary = parsed.get("summary", "")
                paragraphs = parsed.get("paragraphs", [])
                html_body = "".join(f"<p>{p}</p>" for p in paragraphs) if paragraphs else f"<p>{pl_summary}</p>"
                print(f"SUKCES Gemini ({model_name}): {pl_title}")
                return pl_title, pl_summary, html_body
        except urllib.error.HTTPError as he:
            err_body = he.read().decode('utf-8', errors='ignore')
            print(f"Błąd HTTP Gemini ({model_name}): {he.code} - {err_body[:150]}")
            if he.code == 404:
                continue
            break
        except Exception as e:
            print(f"Błąd Gemini AI ({model_name}): {e}")
            break

    return orig_title, source_text[:180], f"<p>{source_text[:350]}</p>"

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
        print("Pominięto aktualizację strony.")
        return

    api_url = PROTO + f"api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
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
                print(f"SUKCES! Zaktualizowano news.json (+{len(new_articles)} newsów)!")
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

                    img_url = PROTO + "images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1000&q=80"
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
