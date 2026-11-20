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
import io
import textwrap
import unicodedata
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

PROTO = "https" + "://"
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK", "").strip()
HISTORY_FILE = "sent_news.txt"

GITHUB_REPO = "kamil1946/strona-bot-pilkarski"
GITHUB_FILE_PATH = "news.json"
SITE_URL = "https://strona-bot-pilkarski.vercel.app"
LOGO_PATH = "logo-bramkarz.png"
GH_TOKEN = os.environ.get("GH_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# Dedykowane, legalne źródła RSS z przypisaniem do lig (name, url, default_cat, limit_per_run)
RSS_SOURCES = [
    ("Weszło", PROTO + "weszlo.com/feed/", "EKS", 2),
    ("Goal.pl Ekstraklasa", PROTO + "www.goal.pl/kategoria/ekstraklasa/feed/", "EKS", 2),
    ("Meczyki.pl", PROTO + "www.meczyki.pl/rss.xml", None, 2),
    ("Football Italia", PROTO + "football-italia.net/feed/", "SA", 3),
    ("Bulinews", PROTO + "bulinews.com/rss.xml", "BL", 3),
    ("Football España", PROTO + "www.football-espana.net/feed", "LL", 3),
    ("BBC Sport", PROTO + "feeds.bbci.co.uk/sport/football/rss.xml", "PL", 2),
    ("Sky Sports", PROTO + "www.skysports.com/rss/11095", "PL", 2),
]

FALLBACK_IMAGES = [
    PROTO + "images.unsplash.com/photo-1522778119026-d647f0596c20?auto=format&fit=crop&w=1200&q=80",
    PROTO + "images.unsplash.com/photo-1574629810360-7efbbe195018?auto=format&fit=crop&w=1200&q=80",
    PROTO + "images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    PROTO + "images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80",
]

CATEGORY_META = {
    "EKS": ("Ekstraklasa", "bg-rose-600", (225, 29, 72)),
    "BL": ("Bundesliga", "bg-amber-600", (217, 119, 6)),
    "LL": ("La Liga", "bg-red-600", (220, 38, 38)),
    "SA": ("Serie A", "bg-sky-600", (2, 132, 199)),
    "PL": ("Premier League", "bg-purple-600", (147, 51, 234)),
    "CL": ("Liga Mistrzów", "bg-indigo-600", (79, 70, 229)),
    "EL": ("Liga Europy", "bg-blue-600", (37, 99, 235)),
    "ECL": ("Liga Konferencji", "bg-teal-600", (13, 148, 136)),
    "OTHER": ("Inne Ligi", "bg-emerald-600", (5, 150, 105)),
}

def create_article_slug(title):
    s = (title or "").lower().replace("ł", "l")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60]

def load_sent_news():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_sent_news(sent_links):
    links_list = list(sent_links)[-1500:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for link in links_list:
            f.write(f"{link}\n")

def is_football_article(title, full_text=""):
    t = (title + " " + full_text[:400]).lower()

    # 1. Twarda blokada spamu, linków do Telegrama, kasyn i reklam
    spam_keywords = [
        "t.me/", "telegram", "join our channel", "lootmudra", "free earning",
        "promo code", "airdrop", "crypto", "casino", "kasyno", "giveaway",
        "whatsapp", "subscribe to", "click here"
    ]
    if any(spam in t for spam in spam_keywords):
        return False

    # 2. Blokada innych dyscyplin sportowych
    non_football_keywords = [
        "tenis", "tennis", "iga świątek", "hubert hurkacz", "wta", "atp", "roland garros", "wimbledon",
        "formuła 1", "formula 1", "f1", "verstappen", "hamilton", "leclerc", "grand prix",
        "żużel", "speedway", "zmarzlik", "pge ekstraliga",
        "siatkówka", "volleyball", "plusliga", "fornal", "leon", "grbić",
        "koszykówka", "nba", "lebron", "sochan",
        "mma", "ufc", "ksw", "fame mma", "boks", "boxing", "usyk", "fury",
        "skoki narciarskie", "stoch", "kubacki", "żyła", "małysz",
        "hokej", "nhl", "golf", "kolarstwo", "tour de france"
    ]
    return not any(bad in t for bad in non_football_keywords)

def detect_category(title, full_text="", default_cat=None):
    t_title = (title or "").lower()
    t = (title + " " + full_text[:700]).lower()
    
    # Dokładne dopasowanie europejskich pucharów (tylko pełne nazwy lub samodzielne skróty \buel\b)
    if re.search(r'\b(liga mistrzów|champions league|ucl)\b', t_title) or re.search(r'\b(liga mistrzów|champions league|ucl)\b', t):
        return "CL", CATEGORY_META["CL"][0], CATEGORY_META["CL"][1]
    if re.search(r'\b(liga europy|europa league|uel)\b', t_title) or re.search(r'\b(liga europy|europa league|uel)\b', t):
        return "EL", CATEGORY_META["EL"][0], CATEGORY_META["EL"][1]
    if re.search(r'\b(liga konferencji|conference league|uecl)\b', t_title) or re.search(r'\b(liga konferencji|conference league|uecl)\b', t):
        return "ECL", CATEGORY_META["ECL"][0], CATEGORY_META["ECL"][1]

    eks_keywords = [
        "ekstraklasa", "pko bp ekstraklasa", "puchar polski",
        "legia warszawa", "lech poznań", "raków częstochowa", "jagiellonia białystok",
        "pogoń szczecin", "górnik zabrze", "śląsk wrocław", "cracovia", "widzew łódź",
        "motor lublin", "piast gliwice", "korona kielce", "radomiak radom", "stal mielec",
        "puszcza niepołomice", "zagłębie lubin", "gks katowice", "lechia gdańsk", "wisła kraków"
    ]
    pl_keywords = [
        "premier league", "arsenal", "arteta", "liverpool", "man utd", "manchester united",
        "man city", "manchester city", "chelsea", "tottenham", "newcastle", "aston villa",
        "everton", "west ham", "crystal palace", "brighton", "fulham", "bournemouth",
        "wolves", "wolverhampton", "brentford", "nottingham", "ipswich", "leicester",
        "southampton", "kiwior", "cash", "bednarek"
    ]
    ll_keywords = [
        "la liga", "laliga", "real madrid", "real madryt", "barcelona", "barca",
        "atletico", "atlético", "mbappe", "mbappé", "vinicius", "yamal", "lewandowski",
        "szczęsny", "sevilla", "espanyol", "bilbao", "athletic club", "sociedad",
        "villarreal", "valencia", "betis", "celta", "girona", "osasuna", "mallorca",
        "getafe", "rayo vallecano"
    ]
    sa_keywords = [
        "serie a", "juventus", "inter mediolan", "ac milan", "napoli", "as roma",
        "lazio", "atalanta", "fiorentina", "bologna", "torino", "monza", "udinese",
        "genoa", "cagliari", "verona", "parma", "como", "empoli", "lecce", "venezia",
        "zieliński", "zalewski"
    ]
    bl_keywords = [
        "bundesliga", "bayern", "monachium", "munich", "borussia", "dortmund",
        "leverkusen", "bayer", "leipzig", "lipsk", "eintracht", "stuttgart",
        "wolfsburg", "werder", "brema", "union berlin", "freiburg", "hoffenheim",
        "mainz", "augsburg", "st. pauli", "bochum", "heidenheim"
    ]

    for scope in (t_title, t):
        if any(k in scope for k in eks_keywords):
            return "EKS", CATEGORY_META["EKS"][0], CATEGORY_META["EKS"][1]
        if any(k in scope for k in pl_keywords):
            return "PL", CATEGORY_META["PL"][0], CATEGORY_META["PL"][1]
        if any(k in scope for k in ll_keywords):
            return "LL", CATEGORY_META["LL"][0], CATEGORY_META["LL"][1]
        if any(k in scope for k in sa_keywords):
            return "SA", CATEGORY_META["SA"][0], CATEGORY_META["SA"][1]
        if any(k in scope for k in bl_keywords):
            return "BL", CATEGORY_META["BL"][0], CATEGORY_META["BL"][1]

    if default_cat and default_cat in CATEGORY_META:
        if default_cat == "EKS" and "ekstraklas" not in t and "liga" not in t:
            return "OTHER", CATEGORY_META["OTHER"][0], CATEGORY_META["OTHER"][1]
        return default_cat, CATEGORY_META[default_cat][0], CATEGORY_META[default_cat][1]
        
    return "OTHER", CATEGORY_META["OTHER"][0], CATEGORY_META["OTHER"][1]

def clean_html(raw_html):
    if not raw_html:
        return ""
    text = re.sub(r'<[^<]+?>', '', raw_html)
    return html.unescape(text).strip()

def is_valid_photo_url(url):
    if not url:
        return False
    lower = url.lower()
    return any(ext in lower for ext in [".jpg", ".jpeg", ".png"])

def fetch_wikipedia_main_image(query_term):
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
    headers = {"User-Agent": "PitchZoneBot/1.0 (https://strona-bot-pilkarski.vercel.app; contact@pitchzone.pl)"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.loads(res.read().decode("utf-8"))
            pages = data.get("query", {}).get("pages", {})
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
    headers = {"User-Agent": "PitchZoneBot/1.0 (https://strona-bot-pilkarski.vercel.app; contact@pitchzone.pl)"}
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
    if player_name:
        img, credit = fetch_wikipedia_main_image(player_name)
        if img:
            return img, credit
        img, credit = fetch_wikimedia_commons_image(player_name)
        if img:
            return img, credit
    if club_or_topic:
        img, credit = fetch_wikipedia_main_image(club_or_topic)
        if img:
            return img, credit
        img, credit = fetch_wikimedia_commons_image(club_or_topic)
        if img:
            return img, credit
    fallback_url = FALLBACK_IMAGES[index % len(FALLBACK_IMAGES)]
    return fallback_url, "Unsplash (CC0)"

# ================= GENERATOR KART GRAFICZNYCH SOCIAL MEDIA (1080x1350) =================
def load_font_safe(size, bold=True):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def load_white_logo(target_height=48):
    """Wczytuje prawdziwe logo (logo-bramkarz.png), skaluje do mniejszego rozmiaru i zmienia na białe."""
    logo_img = None
    try:
        if os.path.exists(LOGO_PATH):
            logo_img = Image.open(LOGO_PATH).convert("RGBA")
        else:
            req = urllib.request.Request(f"{SITE_URL}/{LOGO_PATH}", headers={"User-Agent": "PitchZoneBot/1.0"})
            with urllib.request.urlopen(req, timeout=8) as res:
                logo_img = Image.open(io.BytesIO(res.read())).convert("RGBA")
    except Exception:
        return None

    if logo_img:
        aspect = logo_img.width / max(1, logo_img.height)
        new_w = max(1, int(target_height * aspect))
        logo_img = logo_img.resize((new_w, target_height), Image.Resampling.LANCZOS)
        r, g, b, a = logo_img.split()
        white_layer = Image.new("RGBA", logo_img.size, (255, 255, 255, 255))
        white_layer.putalpha(a)
        return white_layer
    return None

def download_image_rgba(url):
    headers = {
        "User-Agent": "PitchZoneBot/1.0 (https://strona-bot-pilkarski.vercel.app; contact@pitchzone.pl) Python-urllib"
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=12) as res:
        return Image.open(io.BytesIO(res.read())).convert("RGBA")

def generate_social_card(img_url, img_credit, source_name, badge_text, cat_code, title, summary, output_path="social_card.png"):
    """Tworzy w 100% legalną kartę graficzną 1080x1350 z gwarantowanym zdjęciem, logo, pełnymi zdaniami i podpisem CC."""
    W, H = 1080, 1350
    canvas = Image.new("RGBA", (W, H), (8, 8, 12, 255))

    # 1. Pobranie tła (z automatycznym fallbackiem na Unsplash, żeby nigdy nie było czarnego tła)
    bg = None
    actual_credit = img_credit or "Unsplash (CC0)"
    for candidate_url, candidate_credit in [(img_url, actual_credit), (FALLBACK_IMAGES[0], "Unsplash (CC0)")]:
        try:
            bg = download_image_rgba(candidate_url)
            actual_credit = candidate_credit
            break
        except Exception as e:
            print(f"Próba pobrania tła ({candidate_url}) nieudana: {e}")

    if bg:
        target_ratio = W / (H * 0.72)
        bg_ratio = bg.width / max(1, bg.height)
        if bg_ratio > target_ratio:
            new_h = int(H * 0.72)
            new_w = int(new_h * bg_ratio)
        else:
            new_w = W
            new_h = int(new_w / bg_ratio)

        bg = bg.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = max(0, (new_w - W) // 2)
        bg = bg.crop((left, 0, left + W, min(new_h, int(H * 0.72))))
        canvas.paste(bg, (0, 0))

    # 2. Ciemny gradient od góry i od dołu
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    for y in range(210):
        alpha = int(210 * (1 - y / 210))
        draw_ov.line([(0, y), (W, y)], fill=(5, 5, 8, alpha))

    grad_start = 420
    grad_end = 950
    for y in range(grad_start, H):
        if y < grad_end:
            ratio = (y - grad_start) / (grad_end - grad_start)
            alpha = int(255 * (ratio ** 1.4))
        else:
            alpha = 255
        draw_ov.line([(0, y), (W, y)], fill=(8, 8, 12, alpha))

    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)

    # 3. Górny branding: prawdziwe pomniejszone logo (48px) + PITCH ZONE (bez napisu LIVE)
    text_start_x = 64
    logo_img = load_white_logo(target_height=48)
    if logo_img:
        canvas.paste(logo_img, (64, 54), logo_img)
        text_start_x = 64 + logo_img.width + 18

    font_brand = load_font_safe(40, bold=True)
    font_sub = load_font_safe(15, bold=True)
    draw.text((text_start_x, 50), "PITCH", font=font_brand, fill=(255, 255, 255, 255))
    pitch_w = draw.textbbox((0, 0), "PITCH", font=font_brand)[2]
    draw.text((text_start_x + pitch_w + 12, 50), "ZONE", font=font_brand, fill=(168, 85, 247, 255))
    draw.text((text_start_x, 96), "SERWIS PIŁKARSKI", font=font_sub, fill=(185, 185, 200, 255))

    # 4. Kolorowy badge ligi
    badge_rgb = CATEGORY_META.get(cat_code, CATEGORY_META["PL"])[2]
    badge_label = badge_text.upper()
    font_badge = load_font_safe(23, bold=True)
    b_box = draw.textbbox((0, 0), badge_label, font=font_badge)
    b_w = (b_box[2] - b_box[0]) + 42
    badge_y = 750
    draw.rounded_rectangle([(64, badge_y), (64 + b_w, badge_y + 46)], radius=23, fill=(*badge_rgb, 255))
    draw.text((85, badge_y + 9), badge_label, font=font_badge, fill=(255, 255, 255, 255))

    # 5. Główny nagłówek (łamany na max 4 linie)
    font_title = load_font_safe(50, bold=True)
    wrapped_title = textwrap.wrap(title, width=29)[:4]
    curr_y = badge_y + 66
    for line in wrapped_title:
        draw.text((64, curr_y), line, font=font_title, fill=(255, 255, 255, 255))
        curr_y += 62

    # 6. Zajawka (summary) — przycinana wyłącznie na pełnym zdaniu
    curr_y += 14
    font_summary = load_font_safe(26, bold=False)
    max_summary_y = H - 140
    available_lines = max(1, (max_summary_y - curr_y) // 36)

    clean_sum = (summary or "").strip()
    wrapped_sum = textwrap.wrap(clean_sum, width=54)
    if len(wrapped_sum) > available_lines:
        sentences = re.split(r'(?<=[.!?])\s+', clean_sum)
        chosen = ""
        for s in sentences:
            candidate = (chosen + " " + s).strip() if chosen else s
            if len(textwrap.wrap(candidate, width=54)) <= available_lines:
                chosen = candidate
            else:
                break
        if chosen:
            wrapped_sum = textwrap.wrap(chosen, width=54)
        else:
            wrapped_sum = textwrap.wrap(clean_sum, width=54)[:available_lines]
            wrapped_sum[-1] = wrapped_sum[-1].rstrip(" ,;:-") + "..."

    for line in wrapped_sum[:available_lines]:
        draw.text((64, curr_y), line, font=font_summary, fill=(195, 195, 210, 255))
        curr_y += 36

    # 7. Dolny pasek prawny
    draw.line([(64, H - 112), (W - 64, H - 112)], fill=(45, 45, 60, 255), width=2)
    draw.rectangle([(64, H - 88), (71, H - 44)], fill=(168, 85, 247, 255))
    draw.text((86, H - 88), f"WIĘCEJ NA PITCH ZONE  •  ŹRÓDŁO: {source_name.upper()}", font=load_font_safe(19, bold=True), fill=(225, 225, 240, 255))
    credit_label = actual_credit[:65]
    draw.text((86, H - 60), f"Zdjęcie: {credit_label} | Opracowanie informacyjne (art. 25 pr. aut.)", font=load_font_safe(15, bold=False), fill=(140, 140, 155, 255))

    canvas.convert("RGB").save(output_path, "PNG", optimize=True)
    return output_path

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
            if len(text) >= 90 and "football f1" not in text.lower() and "cookie" not in text.lower():
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
        f'- "topic": angielska nazwa głównego klubu, stadionu lub wydarzenia do wyszukania zdjęcia w Wikipedii (np. "Allianz Arena", "Arsenal F.C.", "Legia Warsaw")\n\n'
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
                    print(f"SUKCES Gemini ({model_name}): {pl_title}")
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

def send_to_discord_with_card(title, summary, portal_link, source, card_path):
    if not WEBHOOK_URL or "TUTAJ_WKLEJ" in WEBHOOK_URL:
        return

    content_text = f"🚨 **NOWY NEWS PIŁKARSKI ({source})**\n\n**{title}**\n{summary}\n\n🔗 Czytaj na portalu: {portal_link}"

    if card_path and os.path.exists(card_path):
        boundary = "----PitchZoneBoundary7MA4YWxkTrZu0gW"
        with open(card_path, "rb") as f:
            img_bytes = f.read()

        payload_json = json.dumps({"content": content_text})
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="payload_json"\r\n'
            f"Content-Type: application/json\r\n\r\n"
            f"{payload_json}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="pitchzone_card.png"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode("utf-8") + img_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(
            WEBHOOK_URL,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "PitchZoneBot/1.0"
            }
        )
        try:
            urllib.request.urlopen(req, timeout=15)
            return
        except Exception as e:
            print(f"Błąd wysyłki grafiki na Discord: {e}")

    # Fallback tekstowy
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps({"content": content_text}).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    )
    try:
        urllib.request.urlopen(req)
    except Exception:
        pass

def balance_news_by_category(articles, max_per_category=8, max_total=45):
    counts = {}
    balanced = []
    for art in articles:
        cat = art.get("category", "OTHER")
        if counts.get(cat, 0) < max_per_category:
            balanced.append(art)
            counts[cat] = counts.get(cat, 0) + 1
        if len(balanced) >= max_total:
            break
    return balanced

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

        combined = new_articles + existing_news
        updated_news = balance_news_by_category(combined, max_per_category=8, max_total=45)

        encoded_content = base64.b64encode(
            json.dumps(updated_news, ensure_ascii=False, indent=2).encode('utf-8')
        ).decode('utf-8')

        payload = json.dumps({
            "message": f"Auto-news PL: dodano {len(new_articles)} zbalansowanych artykułów",
            "content": encoded_content,
            "sha": sha
        }).encode('utf-8')

        put_req = urllib.request.Request(api_url, data=payload, headers=headers, method="PUT")
        urllib.request.urlopen(put_req)
    except Exception as e:
        print(f"Błąd zapisu news.json na GitHub: {e}")

def check_news():
    sent_links = load_sent_news()
    new_sent_count = 0
    website_batch = []
    models_list = get_available_flash_models()

    for source, url, default_cat, limit_per_run in RSS_SOURCES:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=12) as response:
                xml_data = response.read()

            root = ET.fromstring(xml_data)
            items = root.findall('.//item')[:limit_per_run]

            for item in reversed(items):
                title_elem = item.find('title')
                link_elem = item.find('link')
                desc_elem = item.find('description')

                if title_elem is not None and link_elem is not None:
                    orig_title = clean_html(title_elem.text)
                    link = link_elem.text.strip()
                    rss_summary = clean_html(desc_elem.text) if desc_elem is not None else ""

                    if link not in sent_links:
                        if not is_football_article(orig_title, rss_summary):
                            sent_links.add(link)
                            continue

                        if new_sent_count > 0:
                            time.sleep(4)

                        source_context = fetch_source_facts(link, rss_summary)
                        pl_title, pl_summary, pl_html_body, player_name, topic_name = summarize_in_polish_with_gemini(
                            orig_title, source_context, source, models_list
                        )

                        legal_img_url, legal_img_credit = get_legal_article_image(player_name, topic_name, new_sent_count)
                        cat_code, badge_text, badge_color = detect_category(
                            orig_title + " " + pl_title, pl_html_body, default_cat=default_cat
                        )

                        # Generowanie karty graficznej 1080x1350 do social mediów
                        card_path = None
                        try:
                            card_path = generate_social_card(
                                legal_img_url, legal_img_credit, source, badge_text, cat_code, pl_title, pl_summary
                            )
                        except Exception as ge:
                            print(f"Błąd generowania karty graficznej: {ge}")

                        portal_direct_link = f"{SITE_URL}/?news={create_article_slug(pl_title)}"
                        send_to_discord_with_card(pl_title, pl_summary, portal_direct_link, source, card_path)

                        sent_links.add(link)
                        new_sent_count += 1
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
            print(f"Błąd przetwarzania kanału {source} ({url}): {e}")

    if new_sent_count > 0:
        save_sent_news(sent_links)
        push_news_to_website(website_batch)
    elif len(sent_links) > 0:
        save_sent_news(sent_links)

if __name__ == "__main__":
    check_news()
