import requests
import re
from langdetect import detect

VIDEO_ID = "8I1DWXcikqg"


def get_youtube_metadata(video_id):
    # noembed devuelve título y autor sin API key
    url = f"https://noembed.com/embed?url=https://www.youtube.com/watch?v={video_id}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    return data.get("title", ""), data.get("author_name", "")


def parse_artist_track(title, author):
    # Intentar "Artista - Canción"
    if " - " in title:
        artist, track = title.split(" - ", 1)
        return artist.strip(), track.strip()
    # Limpiar sufijos comunes del título
    track = re.sub(r"\(.*?\)|\[.*?\]", "", title).strip()
    author = author.replace(" - Topic", "").strip()
    return author.strip(), track


def fetch_lrclib(track, artist, album="", dur=None):
    params = {"track_name": track, "artist_name": artist}
    if album:
        params["album_name"] = album
    if dur is not None:
        params["duration"] = dur
    r = requests.get("https://lrclib.net/api/get", params=params, timeout=15)
    r.raise_for_status()
    d = r.json()
    return (d.get("syncedLyrics") or d.get("plainLyrics") or "").strip()


def fetch_lyrics_ovh(track, artist, album="", dur=None):
    r = requests.get(f"https://api.lyrics.ovh/v1/{artist}/{track}", timeout=15)
    r.raise_for_status()
    d = r.json()
    return (d.get("lyrics") or "").strip()


BACKENDS = [("lrclib", fetch_lrclib), ("lyrics_ovh", fetch_lyrics_ovh)]


def obtener_letra(track, artist, album="", dur=None):
    for nombre, fetcher in BACKENDS:
        try:
            letra = fetcher(track, artist, album, dur)
            if letra:
                print(f"Letra obtenida desde: {nombre}")
                return letra
        except Exception as e:
            print(f"Backend {nombre} falló: {e}")
    return ""


title, author = get_youtube_metadata(VIDEO_ID)
print("Título YouTube:", title)
print("Autor:", author)

artist, track = parse_artist_track(title, author)
print("Artista:", artist)
print("Canción:", track)

letra = obtener_letra(track, artist)
letra_python = str(letra)
idioma = detect(letra_python) if letra_python else "desconocido"

print("Idioma detectado:", idioma)
print("\n--- Letra (string Python) ---")
print(repr(letra_python))

with open("letra_youtube.py", "w", encoding="utf-8") as f:
    f.write(f'video_id = "{VIDEO_ID}"\n')
    f.write(f'titulo = """{title}"""\n')
    f.write(f'letra = """{letra_python}"""\n')
    f.write(f'idioma = "{idioma}"\n')
print("\nGuardado en letra_youtube.py")