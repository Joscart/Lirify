import requests
from langdetect import detect

# Entrada: datos de la canción a buscar
track_name = "Dream On"
artist_name = "Aerosmith"
album_name = ""
duration = 268

# Backends de letras en el orden de fallback de Limusic
BACKENDS = [
    ("lrclib", "https://lrclib.net/api/get"),
    ("lyrics_ovh", None),
]


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


FETCHERS = {
    "lrclib": fetch_lrclib,
    "lyrics_ovh": fetch_lyrics_ovh,
}


def obtener_letra(track, artist, album="", dur=None):
    # Intentar cada backend en orden (fallback)
    for nombre, _ in BACKENDS:
        try:
            letra = FETCHERS[nombre](track, artist, album, dur)
            if letra:
                print(f"Letra obtenida desde: {nombre}")
                return letra
        except Exception as e:
            print(f"Backend {nombre} falló: {e}")
            continue
    return ""


def identificar_idioma(texto):
    if not texto:
        return "desconocido"
    try:
        return detect(texto)
    except Exception:
        return "desconocido"


# Ejecución
letra = obtener_letra(track_name, artist_name, album_name, duration)

# Guardar la letra en una cadena (string) de Python
letra_python = str(letra)

idioma = identificar_idioma(letra_python)

print("Canción:", track_name)
print("Artista:", artist_name)
print("Idioma detectado:", idioma)
print("\n--- Letra (string Python) ---")
print(repr(letra_python))

# Opcional: guardar en archivo .py con la letra como string
with open("letra_cancion.py", "w", encoding="utf-8") as f:
    f.write(f'letra = """{letra_python}"""\n')
    f.write(f'idioma = "{idioma}"\n')

print("\nLetra guardada en letra_cancion.py")