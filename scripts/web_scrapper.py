import re
import csv
import nltk
from bs4 import BeautifulSoup
from urllib.request import urlopen, Request
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer

# Descargar recursos de NLTK e inicializar Stopwords (inglés y español) y Algoritmo de Porter
nltk.download("stopwords", quiet=True)
stop_words = stopwords.words("english") + stopwords.words("spanish")
stemmer = PorterStemmer()

# Definir parámetros de entrada para el Web Scraping
#url = "https://ideiageoca.org"
#url = "https://blog.google/innovation-and-ai/products/teachable-machine/"
#url = "https://davidcruz.vercel.app/"
#url = "https://dievalhu.github.io/diegovallejo/"
#url = "https://aiquest.ideiageoca.org/"
#url = "https://ups.edu.ec"
#url = "https://nexorf.com"
#url = "https://github.com/trending"
#url = "https://neutronpcgamer.com"
url = "https://github.com/features/copilot?locale=es-419"
cantidad_titulos = 100

# 1. Web Scraping: Extraer los títulos (encabezados) de cualquier página web
def extraer_titulos_web(url, cantidad):
    # User-Agent evita el bloqueo (Error 403) en la mayoría de sitios web
    peticion = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    archivo_web = urlopen(peticion)
    html = archivo_web.read()
    archivo_web.close()

    soup = BeautifulSoup(html, "html.parser")
    encabezados = soup.find_all(["h1", "h2", "h3"])

    # Filtrar encabezados vacíos o repetidos y limpiar saltos de línea internos
    titulos = []
    for i in range(len(encabezados)):
        texto = " ".join(encabezados[i].get_text().split())
        if len(texto) > 0 and texto not in titulos:
            titulos.append(texto)

    # Retornar los primeros N títulos válidos encontrados
    return titulos[0:cantidad]

# 2. Volcar cada título extraído en un archivo .csv e importarlos a Python
def guardar_y_cargar_csv(titulos):
    archivos_csv = []

    # Guardar cada título en un archivo .csv
    for i in range(len(titulos)):
        nombre_archivo = "titulo" + str(i + 1) + ".csv"
        archivo = open(nombre_archivo, "w", newline="", encoding="utf-8")
        escritor = csv.writer(archivo)
        escritor.writerow([titulos[i]])
        archivo.close()
        archivos_csv.append(nombre_archivo)

    # Importar los archivos .csv para conformar el corpus de documentos d1, d2, ..., dN
    documentos = []
    for i in range(len(archivos_csv)):
        archivo = open(archivos_csv[i], "r", encoding="utf-8")
        contenido = archivo.read().strip()
        archivo.close()
        documentos.append(contenido)

    return archivos_csv, documentos

# 3. Preprocesamiento NLP: Normalización, Tokenización, Eliminación de Stopwords y Stemming
def preprocesar_documentos(documentos):
    documentos_procesados = []
    print("\nPreprocesamiento NLP de Documentos (Normalización, Stopwords y Stemming):")

    for i in range(len(documentos)):
        docID = i + 1 # Identificador numérico del documento (docID)

        # Eliminar caracteres especiales (conservando letras con tilde/ñ), pasar a minúsculas y tokenizar
        texto_limpio = re.sub(r'[^a-zA-ZáéíóúÁÉÍÓÚñÑ]', ' ', documentos[i]).lower()
        tokens = texto_limpio.split()

        # Eliminar palabras de parada (stopwords) y aplicar Stemming (Algoritmo de Porter)
        tokens_stem = []
        for j in range(len(tokens)):
            palabra = tokens[j]
            if palabra not in stop_words:
                raiz = stemmer.stem(palabra) # Reducir el término a su raíz (stem)
                tokens_stem.append(raiz)

        documentos_procesados.append(tokens_stem)

        print("Documento d" + str(docID) + ":", tokens_stem)
        print("Total de términos procesados:", len(tokens_stem))

    return documentos_procesados

# 4. Creación del Diccionario: Obtener el vocabulario de términos (stems) únicos
def obtener_vocabulario(documentos_procesados):
    vocabulario = []

    for doc in documentos_procesados:
        for termino in doc:
            if termino not in vocabulario:
                vocabulario.append(termino)

    return vocabulario

# 5. Construcción del Full Inverted Index (Índice posicional)
# Estructura por término: <term, ni; [docID, tf, [position1, position2, ...]]>
def construir_indice_invertido(documentos_procesados):
    indice = {}

    for i in range(len(documentos_procesados)):
        docID = i + 1 # Identificador numérico docID (inicia en 1)
        tokens = documentos_procesados[i]

        for j in range(len(tokens)):
            termino = tokens[j]
            posicion = j + 1 # Posición de la palabra en el documento (inicia en 1)

            # Si el término no existe en el diccionario, se crea su entrada
            if termino not in indice:
                indice[termino] = {}

            # Si el docID no está en la posting list del término, se inicializa su lista de posiciones
            if docID not in indice[termino]:
                indice[termino][docID] = []

            indice[termino][docID].append(posicion)

    return indice

# Mostrar tabla de Vocabulario y frecuencia documental (ni = doc. freq.)
def mostrar_tabla_ni(vocabulario, documentos_procesados):
    print("\n-----------------------------------")
    print("Tabla ni (Frecuencia de documento doc. freq.):")
    print("Vocabulario (Stem) | ni")
    print("-----------------------------------")

    for termino in vocabulario:
        ni = 0
        for doc in documentos_procesados:
            if termino in doc:
                ni = ni + 1
        print(f"{termino:<18} | {ni:<3}")

# Mostrar el Full Inverted Index completo: Vocabulario | ni | Ocurrencias [docID, tf, [posiciones]]
def mostrar_indice_completo(vocabulario, indice):
    print("\n--------------------------------------------------------------------")
    print("Solución Full Inverted Index con Stemming (Ocurrencias / Postings):")
    print("Vocabulario (Stem) | ni  | Ocurrencias [docID, tf, [posiciones]]")
    print("--------------------------------------------------------------------")

    for termino in vocabulario:
        ocurrencias = []

        for docID in indice[termino]:
            posiciones = indice[termino][docID]
            tf = len(posiciones) # Frecuencia del término (tf) dentro del documento docID
            ocurrencias.append([docID, tf, posiciones])

        ni = len(ocurrencias) # Número de documentos que contienen el término (ni)
        print(f"{termino:<18} | {ni:<3} | {ocurrencias}")

# Ejecución del proceso completo
print("URL analizada:", url)
titulos_extraidos = extraer_titulos_web(url, cantidad_titulos)

archivos_csv, documentos = guardar_y_cargar_csv(titulos_extraidos)
print("Archivos CSV generados e importados:", archivos_csv)

print("\nColección de documentos importados (Corpus):")
for i in range(len(documentos)):
    print("d" + str(i + 1) + ":", documentos[i])

documentos_procesados = preprocesar_documentos(documentos)

vocabulario = obtener_vocabulario(documentos_procesados)
print("\nVocabulario de términos únicos con Stemming (Diccionario):", vocabulario)
print("Tamaño del vocabulario:", len(vocabulario))

mostrar_tabla_ni(vocabulario, documentos_procesados)

indice = construir_indice_invertido(documentos_procesados)

mostrar_indice_completo(vocabulario, indice)

