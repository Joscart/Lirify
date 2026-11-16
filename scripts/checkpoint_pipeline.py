import importlib.util, json, re, numpy as np
from nltk.stem import PorterStemmer

# Importar o exportar índice invertido
INDEX_FILE = "inverted_index.json"

def build_index(lyrics_tokens):
    index = {}
    for i, toks in enumerate(lyrics_tokens):
        for j, t in enumerate(toks):
            index.setdefault(t, {}).setdefault(str(i), []).append(j+1)
    return index

def save_index(index):
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)

def load_index():
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# Cargar canciones
spec = importlib.util.spec_from_file_location("letras", "letras_from_ids.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
songs = m.letras

names = [re.sub(r'[^a-z0-9 ]','',s["cancion"].lower()).strip() for s in songs]
artists = [re.sub(r'[^a-z0-9 ]','',s["artista"].lower()).strip() for s in songs]
langs = [s["idioma"].strip().lower() for s in songs]

stemmer = PorterStemmer()
def toks(t):
    # Eliminar timestamps tipo [00:00.00] antes de quitar caracteres especiales
    t = re.sub(r'\[\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{1,3})?\]', ' ', t)
    return [stemmer.stem(w) for w in re.sub(r'[^a-zA-Z ]', ' ', t).lower().split()]

lyrics_tokens = [toks(s["letra"]) for s in songs]
index = build_index(lyrics_tokens)
save_index(index)
print("Índice invertido exportado a", INDEX_FILE)

# Reconstruir matriz de conteo desde índice
vocab = sorted(index.keys())
M = np.zeros((len(vocab), len(songs)), dtype=int)
for ti,t in enumerate(vocab):
    for doc,positions in index[t].items():
        M[ti,int(doc)] = len(positions)

# TF-IDF
cond = M>0
tf = np.zeros_like(M,float); tf[cond]=np.log10(M[cond])+1
df = np.sum(cond,axis=1)
idf = np.log10(len(songs)/np.where(df==0,1,df))
tfidf = tf*idf[:,None]
norms=np.linalg.norm(tfidf,axis=0); norms[norms==0]=1
tfidf_u = tfidf/norms

def jac(a,b):
    sa=set(a.split()); sb=set(b.split())
    if not sa and not sb: return 1.0
    return len(sa&sb)/len(sa|sb)

n=len(songs)
Jn=np.zeros((n,n)); Ja=np.zeros((n,n)); Jl=np.zeros((n,n))
for i in range(n):
    for j in range(n):
        Jn[i,j]=jac(names[i],names[j])
        Ja[i,j]=jac(artists[i],artists[j])
        Jl[i,j]=1.0 if langs[i]==langs[j] and langs[i] else 0.0
lyrics_sim = tfidf_u.T @ tfidf_u
unified = (0.10*Jn + 0.05*Ja + 0.05*Jl + 0.8*lyrics_sim)
mx=unified.max() if unified.max()>0 else 1
unified=unified/mx
np.save("unified_similarity.npy", unified)
print("Matriz de similitud exportada. Shape:", unified.shape)