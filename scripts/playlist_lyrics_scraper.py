import yt_dlp
import requests
import re
from langdetect import detect

PLAYLIST_URL = "https://youtube.com/playlist?list=PLZuKCLcFXk1NAem6Php_lnIIM1QybL5ZS"


def get_playlist_entries(url):
    ydl_opts = {"quiet": True, "extract_flat": True, "skip_download": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info.get("entries", [])


def parse_artist_track(title, author):
    if " - " in title:
        artist, track = title.split(" - ", 1)
        return artist.strip(), track.strip()
    track = re.sub(r"\(.*?\)|\[.*?\]", "", title).strip()
    return (author or "").replace(" - Topic", "").strip(), track


def fetch_lrclib(track, artist):
    params = {"track_name": track, "artist_name": artist}
    r = requests.get("https://lrclib.net/api/get", params=params, timeout=15)
    r.raise_for_status()
    d = r.json()
    return (d.get("syncedLyrics") or d.get("plainLyrics") or "").strip()


def fetch_lyrics_ovh(track, artist):
    r = requests.get(f"https://api.lyrics.ovh/v1/{artist}/{track}", timeout=15)
    r.raise_for_status()
    d = r.json()
    return (d.get("lyrics") or "").strip()


def obtener_letra(track, artist):
    for nombre, fetcher in [("lrclib", fetch_lrclib), ("lyrics_ovh", fetch_lyrics_ovh)]:
        try:
            letra = fetcher(track, artist)
            if letra:
                return nombre, letra
        except Exception:
            continue
    return None, ""


entries = get_playlist_entries(PLAYLIST_URL)
resultados = []

for e in entries:
    vid = e.get("id")
    title = e.get("title", "")
    author = e.get("uploader") or e.get("channel") or ""
    artist, track = parse_artist_track(title, author)
    backend, letra = obtener_letra(track, artist)
    idioma = detect(letra) if letra else "desconocido"
    resultados.append({
        "video_id": vid,
        "titulo": title,
        "artista": artist,
        "cancion": track,
        "backend": backend,
        "idioma": idioma,
        "letra": letra,
    })
    print(f"{artist} - {track}: {backend} ({idioma})")

# Guardar lista de letras (strings) en archivo Python
with open("letras_playlist.py", "w", encoding="utf-8") as f:
    f.write("letras = [\n")
    for r in resultados:
        f.write(f"    {{'video_id': {r['video_id']!r}, 'artista': {r['artista']!r}, 'cancion': {r['cancion']!r}, 'idioma': {r['idioma']!r}, 'letra': {r['letra']!r}}},\n")
    f.write("]\n")
print(f"\nGuardadas {len(resultados)} letras en letras_playlist.py")