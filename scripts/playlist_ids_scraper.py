import yt_dlp

PLAYLIST_URL = "https://youtube.com/playlist?list=PLZuKCLcFXk1NAem6Php_lnIIM1QybL5ZS"

ydl_opts = {"quiet": True, "extract_flat": True, "skip_download": True}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(PLAYLIST_URL, download=False)

ids = [e["id"] for e in info.get("entries", []) if e.get("id")]

with open("video_ids.py", "w", encoding="utf-8") as f:
    f.write(f"video_ids = {ids!r}\n")

print(f"Guardados {len(ids)} video IDs en video_ids.py")