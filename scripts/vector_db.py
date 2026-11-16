import importlib.util, json, re, numpy as np
from nltk.stem import PorterStemmer

spec = importlib.util.spec_from_file_location("letras", "letras_from_ids.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
songs = m.letras

# Normalización
def norm_name(s): return re.sub(r'[^a-z0-9 ]', '', s.lower()).strip()
def norm_artist(s): return re.sub(r'[^a-z0-9 ]', '', s.lower()).strip()
def norm_lang(s): return s.strip().lower()

stemmer = PorterStemmer()
stop = set()
try:
    from nltk.corpus import stopwords
    stop = set(stopwords.words("english"))
except Exception:
    pass

def norm_lyrics(text, lang):
    text = re.sub(r'[^a-zA-ZáéíóúÁÉÍÓÚñÑ ]', ' ', text).lower()
    toks = [w for w in text.split() if w not in stop]
    toks = [stemmer.stem(w) for w in toks]
    return toks

# Construir corpus
names = [norm_name(s["cancion"]) for s in songs]
artists = [norm_artist(s["artista"]) for s in songs]
langs = [norm_lang(s["idioma"]) for s in songs]
lyrics_tokens = [norm_lyrics(s["letra"], s["idioma"]) for s in songs]

# Inverted index para lyrics
index = {}
for i, toks in enumerate(lyrics_tokens):
    for j, t in enumerate(toks):
        index.setdefault(t, {}).setdefault(i, []).append(j+1)

# Count matrix (terms x docs)
vocab = sorted(index.keys())
term_to_i = {t:i for i,t in enumerate(vocab)}
M = np.zeros((len(vocab), len(songs)), dtype=int)
for ti,t in enumerate(vocab):
    for doc,positions in index[t].items():
        M[ti,doc] = len(positions)

# TF-IDF lyrics
cond = M > 0
tf = np.zeros_like(M, dtype=float)
tf[cond] = np.log10(M[cond]) + 1
df = np.sum(cond, axis=1)
idf = np.log10(len(songs)/np.where(df==0,1,df))
tfidf = tf * idf[:,None]
# normalizar columnas
norms = np.linalg.norm(tfidf, axis=0)
norms[norms==0]=1
tfidf_unit = tfidf / norms

# Jaccard helpers
def jaccard_sets(a,b):
    sa=set(a.split()); sb=set(b.split())
    if not sa and not sb: return 1.0
    return len(sa & sb)/len(sa | sb)

n=len(songs)
J_name=np.zeros((n,n)); J_artist=np.zeros((n,n)); J_lang=np.zeros((n,n))
for i in range(n):
    for j in range(n):
        J_name[i,j]=jaccard_sets(names[i],names[j])
        J_artist[i,j]=jaccard_sets(artists[i],artists[j])
        J_lang[i,j]=1.0 if langs[i]==langs[j] and langs[i]!="" else 0.0

lyrics_sim = tfidf_unit.T @ tfidf_unit

# Pesos
W = {"name":0.10,"artist":0.05,"lang":0.05,"lyrics":0.8}
unified = (W["name"]*J_name + W["artist"]*J_artist + W["lang"]*J_lang + W["lyrics"]*lyrics_sim)
# normalizar 0-1 por max
mx = unified.max() if unified.max()>0 else 1
unified = unified/mx

# Vector database JSON
db = []
for i,s in enumerate(songs):
    db.append({
        "name": s["cancion"],
        "artist": s["artista"],
        "language": s["idioma"],
        "lyrics": s["letra"],
    })

with open("vector_db.json","w",encoding="utf-8") as f:
    json.dump(db, f, ensure_ascii=False, indent=2)

np.save("unified_similarity.npy", unified)
print("Vector DB guardado (", len(db), "canciones )")
print("Matriz unificada shape:", unified.shape)