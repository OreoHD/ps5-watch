import argparse, html, json, os, re, sys, time, urllib.parse, urllib.request
from html.parser import HTMLParser

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "ps5-watch-AENDERE-MICH-123xyz")
MIN_PREIS = 250
MAX_PREIS = 3000
INTERVALL_SEK = 300
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ps5_seen.json")

QUELLEN = {
    "Ricardo": [
        "https://www.ricardo.ch/de/s/ps5",
        "https://www.ricardo.ch/de/s/playstation%205%20pro",
    ],
    "Tutti": [
        "https://www.tutti.ch/de/q/suche/Ak8CjwTQUzUwNdW1NNSy0DUwNTI0sQAAAOPtB0M?sorting=newest&page=1&query=ps5",
    ],
    "Galaxus": ["https://www.galaxus.ch/de/search?q=playstation%205%20konsole"],
    "Digitec": ["https://www.digitec.ch/de/search?q=playstation%205%20konsole"],
    "Interdiscount": ["https://www.interdiscount.ch/de/search?search=playstation%205%20konsole"],
    "MediaMarkt": ["https://www.mediamarkt.ch/de/search.html?query=playstation%205%20konsole"],
    "Brack": ["https://www.brack.ch/search?query=playstation%205%20konsole"],
    "Microspot": ["https://www.microspot.ch/de/search?search=playstation%205%20konsole"],
}

MUSS = re.compile(r"\bps\s?5\b|playstation\s?5", re.I)
AUSSCHLUSS = re.compile(
    r"controller|dualsense|dual sense|headset|pulse|ladestation|charging|hülle|huelle|skin|"
    r"fernbedienung|kamera|camera|\bspiel\b|\bgame\b|\bgames\b|fifa|fc ?2\d|call of duty|"
    r"gutschein|guthaben|\bcard\b|ssd|festplatte|ständer|staender|halterung|laufwerk|"
    r"defekt|bastler|ersatzteil|nur laufwerk|ohne konsole|portal|vr ?2|zubehör|zubehoer|"
    r"lenkrad|stick|cover|tasche|kabel|netzteil|lüfter|luefter|spiele",
    re.I,
)
PREIS = re.compile(r"(?:CHF|Fr\.?)\s*([\d'’.,]+)|([\d'’]{3,6})(?:\.\d\d)?\.[–-]|([\d'’]{3,6})\.\d\d\b")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept-Language": "de-CH,de;q=0.9",
}


class LinkSammler(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self._href, self._txt = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._txt = []

    def handle_data(self, data):
        if self._href is not None:
            self._txt.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(" ".join(self._txt).split())))
            self._href = None


def preis_aus(text):
    for m in PREIS.finditer(text):
        roh = next(g for g in m.groups() if g)
        roh = roh.replace("'", "").replace("’", "")
        roh = re.sub(r"[.,]-+$|[.,]$", "", roh)
        roh = roh.replace(",", ".")
        try:
            return float(roh)
        except ValueError:
            continue
    return None


def holen(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def treffer_aus_html(quelle, url, seite):
    gefunden = []
    p = LinkSammler()
    p.feed(seite)
    for href, text in p.links:
        if not href or not MUSS.search(text) or AUSSCHLUSS.search(text):
            continue
        preis = preis_aus(text)
        if preis is None:
            continue
        gefunden.append((quelle, text[:110], preis, urllib.parse.urljoin(url, html.unescape(href))))
    for blob in re.findall(r'<script[^>]*type="application/(?:ld\+)?json"[^>]*>(.*?)</script>', seite, re.S):
        try:
            data = json.loads(blob)
        except Exception:
            continue
        stack = [data]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                name = str(o.get("name") or o.get("title") or "")
                offers = o.get("offers")
                preis = None
                if isinstance(offers, dict):
                    preis = offers.get("price")
                elif isinstance(offers, list) and offers and isinstance(offers[0], dict):
                    preis = offers[0].get("price")
                if preis is None:
                    preis = o.get("price")
                link = o.get("url") or o.get("@id")
                if name and link and preis and MUSS.search(name) and not AUSSCHLUSS.search(name):
                    try:
                        gefunden.append((quelle, name[:110], float(preis), urllib.parse.urljoin(url, str(link))))
                    except (ValueError, TypeError):
                        pass
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
    return gefunden


def push(titel, text, link):
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=text.encode("utf-8"),
        headers={"Title": titel.encode("ascii", "ignore").decode(), "Click": link, "Priority": "high", "Tags": "video_game"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=15).read()


def lauf(debug=False):
    try:
        gesehen = set(json.load(open(STATE_FILE)))
    except Exception:
        gesehen = set()
    neu = 0
    for quelle, urls in QUELLEN.items():
        for url in urls:
            try:
                seite = holen(url)
            except Exception as e:
                print(f"[{quelle}] Fehler: {e}", file=sys.stderr)
                continue
            treffer = treffer_aus_html(quelle, url, seite)
            if debug:
                print(f"[{quelle}] {len(treffer)} Treffer ({len(seite)} Bytes)")
            for q, name, preis, link in treffer:
                if debug:
                    print(f"   {preis:>7.0f}  {name}  {link}")
                if not (MIN_PREIS <= preis <= MAX_PREIS):
                    continue
                if link in gesehen:
                    continue
                gesehen.add(link)
                neu += 1
                print(f"NEU: {q} CHF {preis:.0f} {name} {link}")
                try:
                    push(f"PS5 gefunden: CHF {preis:.0f} ({q})", f"{name}\nCHF {preis:.0f}", link)
                except Exception as e:
                    print(f"Push fehlgeschlagen: {e}", file=sys.stderr)
    json.dump(sorted(gesehen), open(STATE_FILE, "w"))
    print(f"Fertig, {neu} neue Treffer.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:
        push("PS5-Watcher Test", "Wenn du das siehst, klappt die Benachrichtigung.", "https://www.ricardo.ch/de/s/ps5")
        print("Testnachricht gesendet an:", NTFY_TOPIC)
    elif a.loop:
        while True:
            lauf(a.debug)
            time.sleep(INTERVALL_SEK)
    else:
        lauf(a.debug)

