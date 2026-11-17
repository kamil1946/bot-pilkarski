import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
import json
import os
import base64
import re
import html
import time
from datetime import datetime

PROTO = "https" + "://"
# Pamiętaj o wklejeniu tutaj swojego nowego linku do webhooka Discord (lub ustawieniu w GitHub Secrets jako DISCORD_WEBHOOK)
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK", "").strip() or (PROTO + "discord.com/api/webhooks/TUTAJ_WKLEJ_NOWY_LINK")
HISTORY_FILE = "sent_news.txt"

GITHUB_REPO = "kamil1946/strona-bot-pilkarski"
GITHUB_FILE_PATH = "news.json"
GH_TOKEN = os.environ.get("GH_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# Rozszerzona lista źródeł RSS (wielokrotnie więcej newsów ze świata futbolu)
RSS_FEEDS = [
    PROTO + "feeds.bbci.co.uk/sport/football/rss.xml",
    PROTO + "www.skysports.com/rss/11095",
    PROTO + "www.skysports.com/rss/12040",  # Serie A
    PROTO + "www.skysports.com/rss/11881",  # Bundesliga
    PROTO + "www.skysports.com/rss/11711",  # La Liga
    PROTO + "www.skysports.com/rss/12028",  # European Football
    PROTO + "www.skysports.com/rss/11952",  # Transfer Centre
    PROTO + "https://site.api.espn.com/apis/site/v2/sports/soccer/news", # Uwaga: RSS obsługujemy przez standardowe tagi item, w razie potrzeby system pominie niespójne
]

FALLBACK_IMAGES = [
    PROTO + "images.unsplash.com/photo-1522778119026-d647f0596c20?auto=format&fit=crop&w=1200&q=80",
    PROTO + "images.unsplash.com/photo-1574629810360-7efbbe195018?auto=format&fit=crop&w=1200&q=80",
    PROTO + "images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    PROTO + "images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80",
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
    # Bundesliga sprawdzana przed Premier League, żeby np. Harry Kane w Bayernie trafiał do BL
    if any(k in t for k in ["bundesliga", "bayern", "monachium", "munich", "borussia", "dortmund", "bayer leverkusen", "rb leipzig", "eintracht", "stuttgart", "wolfsburg"]):
        return "BL", "Bundesliga", "bg-amber-600"
    if any(k in t for k in ["ekstraklasa", "legia", "lech poznań", "raków", "jagiellonia", "pogoń szczecin", "górnik zabrze", "śląsk wrocław", "cracovia", "widzew", "motor lublin", "piast gliwice"]):
        return "EKS", "Ekstraklasa", "bg-rose-600"
    if any(k in t for k in ["la liga", "real madrid", "real madryt", "barcelona", "atletico", "mbappe", "vinicius", "yamal", "sevilla", "espanyol", "athletic bilbao", "real sociedad", "villarreal"]):
        return "LL", "La Liga", "bg-red-600"
    if any(k in t for k in ["serie a", "juventus", "inter mediolan", "inter milan", "ac milan", "napoli", "as roma", "lazio", "atalanta", "fiorentina", "bologna"]):
        return "SA", "Serie A", "bg-sky-600"
    if any(k in t for k in ["premier league", "arsenal", "liverpool", "man utd", "manchester united", "man city", "manchester city", "chelsea", "tottenham", "newcastle", "aston villa", "everton", "west ham", "crystal palace", "brighton", "fulham", "bournemouth", "wolves"]):
        return "PL", "Premier League", "bg-purple-600"
    return "OTHER", "Inne Ligi", "bg-emerald-600"

def clean_html(raw_html):
    if not raw_html:
        return ""
    text = re.sub(r'<[^<]+?>', '', raw_html)
    return html.unescape(text).strip()

def is_valid_photo_url(url):
    if not url:
        return False
    lower = url.lower()
    # Akceptujemy wyłącznie formaty JPG i PNG (odrzucamy SVG, TIF, PDF, które psują obrazki)
    return any(ext in lower for ext in [".jpg", ".jpeg", ".png"])

def fetch_wikipedia_main_image(query_term):
    """Pobiera główne zdjęcie z artykułu w Wikipedii (najlepsze źródło portretów piłkarzy)."""
    if not query_term or len(query_term.strip()) < 3:
        return None, None

    params = urllib.parse.urlencode({
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query_term.strip(),
        "gsrlimit": "2",
        "prop": "pageimages|imageinfo",
        "pithumbsize": "1000",
        "pilicense": "free"
    })
    url = f"{PROTO}en.wikipedia.org/w/api.php?{params}"
    headers = {"User-Agent": "PitchZoneBot/1.0 (https://strona-bot-pilkarski.vercel.app)"}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.loads(res.read().decode("utf-8"))
            pages = data.get("query", {}).get("pages", {})
            # Sortujemy po indeksie trafności wyszukiwania
            sorted_pages = sorted(pages.values(), key=lambda x: x.get("index", 99))
            for page in sorted_pages:
                thumb = page.get("thumbnail", {}).get("source")
                page_image_name = page.get("pageimage", "")
                if thumb and is_valid_photo_url(thumb) and "flag" not in page_image_name.lower() and "logo" not in page_image_name.lower():
                    return thumb, "Wikimedia Commons (CC)"
    except Exception:
        pass
    return None, None

def fetch_wikimedia_commons_image(query_term):
    """Przeszukuje bezpośrednio bazę multimediów Wikimedia Commons."""
    if not query_term or len(query_term.strip()) < 3:
        return None, None

    params = urllib.parse.urlencode({
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query_term.strip(),
        "gsrnamespace": "6",
        "gsrlimit": "6",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "1000"
    })
    url = f"{PROTO}commons.wikimedia.org/w/api.php?{params}"
    headers = {"User-Agent": "PitchZoneBot/1.0 (https://strona-bot-pilkarski.vercel.app)"}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.loads(res.read().decode("utf-8"))
            pages = data.get("query", {}).get("pages", {})
            sorted_pages = sorted(pages.values(), key=lambda x: x.get("index", 99))

            for page in sorted_pages:
                info = page.get("imageinfo", [{}])[0]
                thumb_url = info.get("thumburl") or info.get("url")
                if not is_valid_photo_url(thumb_url):
                    continue

                meta = info.get("extmetadata", {})
                license_name = meta.get("LicenseShortName", {}).get("value", "CC BY-SA")
                artist_raw = meta.get("Artist", {}).get("value", "Wikimedia Commons")
                artist_clean = clean_html(artist_raw)[:40].strip() or "Wikimedia Commons"

                return thumb_url, f"Fot. {artist_clean} ({license_name})"
    except Exception:
        pass
    return None, None

def get_legal_article_image(player_name, club_or_topic, index=0):
    """3-stopniowe dobieranie tematycznego legalnego zdjęcia: Piłkarz (Wiki) -> Piłkarz (Commons) -> Klub/Stadion -> Fallback CC0."""
    # 1. Szukaj konkretnego piłkarza/trenera w Wikipedii
    if player_name:
        img, credit = fetch_wikipedia_main_image(player_name)
        if img:
            print(f"Znaleziono zdjęcie piłkarza (Wikipedia): {player_name}")
            return img, credit

        img, credit = fetch_wikimedia_commons_image(player_name)
        if img:
            print(f"Znaleziono zdjęcie piłkarza (Commons): {player_name}")
            return img, credit

    # 2. Jeśli brak piłkarza, szukaj powiązanego klubu / stadionu / obiektu
    if club_or_topic:
        img, credit = fetch_wikipedia_main_image(club_or_topic)
        if img:
            print(f"Znaleziono zdjęcie tematyczne (Wikipedia): {club_or_topic}")
            return img, credit

        img, credit = fetch_wikimedia_commons_image(club_or_topic)
        if img:
            print(f"Znaleziono zdjęcie tematyczne (Commons): {club_or_topic}")
            return img, credit

    # 3. Ostateczny bezpieczny fallback (Unsplash CC0)
    fallback_url = FALLBACK_IMAGES[index % len(FALLBACK_IMAGES)]
    return fallback_url, "Unsplash (CC0)"

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

def get_available_flash_models():
    fallback_models = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash-lite"]
    if not GEMINI_API_KEY:
        return fallback_models
    try:
        list_url = PROTO + f"generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
        req = urllib.request.Request(list_url)
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode('utf-8'))
            found = []
            for m in data.get("models", []):
                name = m.get("name", "").replace("models/", "")
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in methods and "flash" in name and "2.0" not in name and "2.5-flash" != name:
                    found.append(name)
            if found:
                found.sort(key=lambda x: (0 if "lite" in x or "latest" in x else 1, x))
                return found[:4]
    except Exception:
        pass
    return fallback_models

def summarize_in_polish_with_gemini(orig_title, source_text, source_name, models_list):
    if not GEMINI_API_KEY:
        return orig_title, source_text[:180], f"<p>{source_text[:300]}</p>", "", ""

    prompt = (
        f"Jesteś redaktorem polskiego portalu piłkarskiego PITCH ZONE.\n"
        f"Na podstawie poniższego artykułu ze źródła ({source_name}) napisz konkretne, autorskie podsumowanie faktów po polsku własnymi słowami (nie kopiuj dosłownie zdań z oryginału).\n\n"
        f"Wymagania:\n"
        f"1. Wyciągnij najważniejsze detale z tekstu: nazwiska piłkarzy i trenerów, nazwy klubów, dokładny powód (np. jaka kontuzja, na ile wypada, jaki wynik, co dokładnie powiedział trener).\n"
        f"2. Zwróć odpowiedź WYŁĄCZNIE jako czysty obiekt JSON (bez znaczników markdown) z pięcioma polami:\n"
        f'- "title": dynamiczny nagłówek po polsku (max 85 znaków)\n'
        f'- "summary": zajawka 1-2 zdania po polsku z głównym faktem (max 190 znaków)\n'
        f'- "paragraphs": lista 3 konkretnych akapitów po polsku opisujących szczegóły wydarzenia\n'
        f'- "player": pełne imię i nazwisko głównego piłkarza lub trenera w artykule po angielsku (np. "Harry Kane", "Mikel Arteta" lub "" jeśli brak osoby)\n'
        f'- "topic": angielska nazwa głównego klubu, stadionu lub wydarzenia do wyszukania zdjęcia w Wikipedii (np. "Allianz Arena", "Arsenal F.C.", "Wembley Stadium")\n\n'
        f"Oryginalny tytuł: {orig_title}\n"
        f"Treść artykułu źródłowego:\n{source_text[:3500]}"
    )

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4}
    }).encode('utf-8')

    for model_name in models_list:
        api_url = PROTO + f"generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        for attempt in range(2):
            try:
                req = urllib.request.Request(api_url, data=payload, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=30) as res:
                    data = json.loads(res.read().decode('utf-8'))
                    raw_reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    raw_reply = re.sub(r'^```json\s*|\s*```$', '', raw_reply, flags=re.IGNORECASE).strip()
                    parsed = json.loads(raw_reply)

                    pl_title = parsed.get("title", orig_title)
                    pl_summary = parsed.get("summary", "")
                    paragraphs = parsed.get("paragraphs", [])
                    player_name = parsed.get("player", "")
                    topic_name = parsed.get("topic", "")
                    html_body = "".join(f"<p>{p}</p>" for p in paragraphs) if paragraphs else f"<p>{pl_summary}</p>"
                    print(f"SUKCES Gemini ({model_name}): {pl_title} | Postać: {player_name} | Temat: {topic_name}")
                    return pl_title, pl_summary, html_body, player_name, topic_name
            except urllib.error.HTTPError as he:
                if he.code in (429, 503) and attempt == 0:
                    time.sleep(8)
                    continue
                if he.code == 404:
                    break
                break
            except Exception:
                break

    return orig_title, source_text[:180], f"<p>{source_text[:350]}</p>", "", ""

def send_to_discord(title, summary, link, source):
    if not WEBHOOK_URL or "TUTAJ_WKLEJ" in WEBHOOK_URL:
        return
    message = {
        "content": f"🚨 **NOWY NEWS PIŁKARSKI ({source})**\n\n**{title}**\n{summary}\n\n🔗 Pełny artykuł źródłowy: {link}"
    }
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps(message).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    )
    try:
        urllib.request.urlopen(req)
    except Exception:
        pass

def push_news_to_website(new_articles):
    if not GH_TOKEN or not new_articles:
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
            "message": f"Auto-news PL: dodano {len(new_articles)} streszczeń ze zdjęciami tematycznymi",
            "content": encoded_content,
            "sha": sha
        }).encode('utf-8')

        put_req = urllib.request.Request(api_url, data=payload, headers=headers, method="PUT")
        urllib.request.urlopen(put_req)
    except Exception:
        pass

def check_news():
    sent_links = load_sent_news()
    new_sent_count = 0
    website_batch = []
    models_list = get_available_flash_models()

    for url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                xml_data = response.read()

            root = ET.fromstring(xml_data)
            
            if "bbci" in url:
                source = "BBC Sport"
            elif "espn" in url:
                source = "ESPN"
            else:
                source = "Sky Sports"

            items = root.findall('.//item')[:3]
            for item in reversed(items):
                title_elem = item.find('title')
                link_elem = item.find('link')
                desc_elem = item.find('description')

                if title_elem is not None and link_elem is not None:
                    orig_title = clean_html(title_elem.text)
                    link = link_elem.text.strip()
                    rss_summary = clean_html(desc_elem.text) if desc_elem is not None else ""

                    if link not in sent_links:
                        if new_sent_count > 0:
                            time.sleep(5)

                        source_context = fetch_source_facts(link, rss_summary)
                        pl_title, pl_summary, pl_html_body, player_name, topic_name = summarize_in_polish_with_gemini(
                            orig_title, source_context, source, models_list
                        )

                        legal_img_url, legal_img_credit = get_legal_article_image(player_name, topic_name, new_sent_count)

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
                            "img": legal_img_url,
                            "imgCredit": legal_img_credit,
                            "title": pl_title,
                            "summary": pl_summary,
                            "content": f"{pl_html_body}<p class='pt-3 border-t border-gray-100 dark:border-border text-xs text-gray-400'>Podsumowanie faktów opracowane na podstawie publikacji {source}. <a href='{link}' target='_blank' rel='noopener' class='text-purple-500 font-bold underline ml-1'>Przeczytaj oryginalny artykuł →</a></p>"
                        })

        except Exception as e:
            print(f"Błąd przetwarzania kanału {url}: {e}")

    if new_sent_count > 0:
        save_sent_news(sent_links)
        push_news_to_website(website_batch)

if __name__ == "__main__":
    check_news()
