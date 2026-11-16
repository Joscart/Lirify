import requests, re, importlib.util
from langdetect import detect

# Cargar IDs guardados
spec = importlib.util.spec_from_file_location("video_ids", "video_ids.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
VIDEO_IDS = m.video_ids

def get_metadata(vid):
    r = requests.get(f"https://noembed.com/embed?url=https://www.youtube.com/watch?v={vid}", timeout=15)
    r.raise_for_status()
    d = r.json()
    return d.get("title",""), d.get("author_name","")

def parse(title, author):
    if " - " in title:
        a,t = title.split(" - ",1)
        return a.strip(), t.strip()
    t = re.sub(r"\(.*?\)|\[.*?\]","",title).strip()
    return author.replace(" - Topic","").strip(), t

def fetch_lrclib(track, artist):
    r = requests.get("https://lrclib.net/api/get", params={"track_name":track,"artist_name":artist}, timeout=15)
    r.raise_for_status()
    d = r.json()
    return (d.get("syncedLyrics") or d.get("plainLyrics") or "").strip()

def fetch_ovh(track, artist):
    r = requests.get(f"https://api.lyrics.ovh/v1/{artist}/{track}", timeout=15)
    r.raise_for_status()
    return (r.json().get("lyrics") or "").strip()

results=[]
for vid in VIDEO_IDS:
    try:
        title, author = get_metadata(vid)
        artist, track = parse(title, author)
        letra=""
        backend=None
        for name,fn in [("lrclib",fetch_lrclib),("lyrics_ovh",fetch_ovh)]:
            try:
                l=fn(track,artist)
                if l:
                    letra=l; backend=name; break
            except Exception:
                pass
        idioma = detect(letra) if letra else "desconocido"
        results.append({"video_id":vid,"artista":artist,"cancion":track,"backend":backend,"idioma":idioma,"letra":letra})
        print(f"{artist} - {track}: {backend} ({idioma})")
    except Exception as e:
        print(f"{vid}: error {e}")

with open("letras_from_ids.py","w",encoding="utf-8") as f:
    f.write("letras = [\n")
    for r in results:
        f.write(f"    {r!r},\n")
    f.write("]\n")
print(f"Guardadas {len(results)} letras en letras_from_ids.py")