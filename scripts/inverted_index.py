import re

# Definir la colección de documentos (corpus) d1, d2, d3, d4
d1 = "To do is to be. To be is to do."
d2 = "To be or not to be. I am what I am."
d3 = "I think therefore I am. Do be do be do."
d4 = "Do do do, da da da. Let it be, let it be."

documentos = [d1, d2, d3, d4]

# Fase 1 y 2: Extraer tokens y normalización de términos
# Elimina símbolos de puntuación, convierte a minúsculas y obtiene la secuencia de tokens por documento
def normalizar_documentos(documentos):
    documentos_normalizados = []
    print("Normalización y Tokenización:")

    for i in range(len(documentos)):
        docID = i + 1 # Identificador numérico del documento (docID)
        texto = re.sub(r'[^a-zA-Z0-9]', ' ', documentos[i]).lower()
        tokens = texto.split()
        documentos_normalizados.append(tokens)

        print("Documento d" + str(docID) + ":")
        print("Tokens:", tokens)
        print("Total de tokens:", len(tokens))

    return documentos_normalizados

# Creación del Diccionario (Vocabulario de términos únicos)
# Un término es una palabra normalizada que será una entrada en el diccionario del sistema de RI
def obtener_vocabulario(documentos_normalizados):
    vocabulario = []

    for doc in documentos_normalizados:
        for termino in doc:
            if termino not in vocabulario:
                vocabulario.append(termino)

    return vocabulario

# Fase 3: Indexar - Construcción del Full Inverted Index (Índice posicional)
# Estructura por término: <term, ni; [docID, tf, [position1, position2, ...]]>
def construir_indice_invertido(documentos_normalizados):
    indice = {}

    for i in range(len(documentos_normalizados)):
        docID = i + 1 # Identificador numérico docID (inicia en 1)
        tokens = documentos_normalizados[i]

        for j in range(len(tokens)):
            termino = tokens[j]
            posicion = j + 1 # Conteo de posición por palabras (inicia en 1, sin signos de puntuación)

            # Si el término no existe en el diccionario, se crea su entrada
            if termino not in indice:
                indice[termino] = {}

            # Si el docID no está en la posting list del término, se inicializa su lista de posiciones
            if docID not in indice[termino]:
                indice[termino][docID] = []

            indice[termino][docID].append(posicion)

    return indice

# Mostrar tabla de Vocabulario y frecuencia documental (ni = número de documentos que contienen el término)
def mostrar_tabla_ni(vocabulario, documentos_normalizados):
    print("\n-----------------------------------")
    print("Tabla ni (Frecuencia de documento doc. freq.):")
    print("Vocabulario  | ni")
    print("-----------------------------------")

    for termino in vocabulario:
        ni = 0
        for doc in documentos_normalizados:
            if termino in doc:
                ni = ni + 1
        print(f"{termino:<12} | {ni:<3}")

# Mostrar el Full Inverted Index completo: Vocabulario | ni | Ocurrencias [docID, tf, [posiciones]]
def mostrar_indice_completo(vocabulario, indice):
    print("\n------------------------------------------------------------")
    print("Solución Full Inverted Index (Ocurrencias como posting lists):")
    print("Vocabulario  | ni  | Ocurrencias [docID, tf, [posiciones]]")
    print("------------------------------------------------------------")

    for termino in vocabulario:
        ocurrencias = []

        for docID in indice[termino]:
            posiciones = indice[termino][docID]
            tf = len(posiciones) # Frecuencia del término (tf) dentro del documento docID
            ocurrencias.append([docID, tf, posiciones])

        ni = len(ocurrencias) # Número de documentos que contienen el término (ni)
        print(f"{termino:<12} | {ni:<3} | {ocurrencias}")

# Ejecución de las fases de construcción del Índice Invertido
print("Colección de documentos a indexar:", documentos)
print("Total de documentos en el corpus:", len(documentos), "\n")

documentos_normalizados = normalizar_documentos(documentos)

vocabulario = obtener_vocabulario(documentos_normalizados)
print("\nVocabulario de términos (Diccionario):", vocabulario)

mostrar_tabla_ni(vocabulario, documentos_normalizados)

indice = construir_indice_invertido(documentos_normalizados)

mostrar_indice_completo(vocabulario, indice)
