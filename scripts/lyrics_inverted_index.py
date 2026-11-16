import importlib.util, re, json
import nltk
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer, SnowballStemmer

nltk.download("stopwords", quiet=True)

spec = importlib.util.spec_from_file_location("letras", "letras_from_ids.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
letras = m.letras

STEMMERS = {
    "en": PorterStemmer().stem,
    "es": SnowballStemmer("spanish").stem,
    "fr": SnowballStemmer("french").stem,
    "pt": SnowballStemmer("portuguese").stem,
    "de": SnowballStemmer("german").stem,
    "it": SnowballStemmer("italian").stem,
}

STOP = {}
for lang in ["english", "spanish", "french", "portuguese", "german", "italian"]:
    try:
        STOP[lang[:2]] = set(stopwords.words(lang))
    except Exception:
        STOP[lang[:2]] = set()

WEIGHTS = {"cancion": 10.0, "artista": 5.0, "idioma": 5.0, "letra": 8.0}


def stem_token(tok, lang):
    fn = STEMMERS.get(lang, PorterStemmer().stem)
    try:
        return fn(tok)
    except Exception:
        return tok


def tokenize(text):
    text = re.sub(r"\[\d{2}:\d{2}\.\d{2}\]", " ", text or "")
    text = re.sub(r"[^a-zA-ZáéíóúÁÉÍÓÚñÑüÜàâçéèêëïîôùûüÿæœ]", " ", text)
    return [t for t in text.lower().split() if len(t) > 1]


indice = {}  # term -> {doc_index: peso_acumulado}
docs = []

for di, r in enumerate(letras):
    lang = r.get("idioma", "en") or "en"
    stop = STOP.get(lang, set())
    fields = {
        "cancion": r.get("cancion", ""),
        "artista": r.get("artista", ""),
        "idioma": lang,
        "letra": r.get("letra", ""),
    }
    for field, value in fields.items():
        w = WEIGHTS[field]
        for tok in tokenize(str(value)):
            if tok in stop:
                continue
            stem = stem_token(tok, lang)
            if stem not in indice:
                indice[stem] = {}
            indice[stem][di] = indice[stem].get(di, 0.0) + w
    docs.append(f"{r['artista']} - {r['cancion']}")

# Guardar solo indice + documentos
salida = {
    "documentos": docs,
    "indice": {k: {str(dk): dv for dk, dv in v.items()} for k, v in indice.items()},
}

with open("lyrics_inverted_index.json", "w", encoding="utf-8") as f:
    json.dump(salida, f, ensure_ascii=False, indent=2)

print("Términos (stems):", len(indice))
print("Documentos:", len(docs))
print("Guardado en lyrics_inverted_index.json")