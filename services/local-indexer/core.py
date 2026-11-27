"""Lirify core engine.

`Indexer` owns the whole index lifecycle in one place:

* text pipeline (normalise -> tokenise -> stopwords -> stemming),
* inverted index, vocabulary and TF-IDF/cosine matrices (local only),
* LLM embeddings (Qwen3-Embedding-0.6B through sentence-transformers),
* search and recommendation over the LLM embeddings,
* publication of songs + embeddings to MongoDB Atlas and Qdrant Cloud.

The cloud serving API never builds matrices: Atlas keeps the songs and Qdrant
keeps the pre-computed LLM embeddings, and that is all the web UI reads.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Iterable, Sequence
from typing import Any

import nltk
import numpy as np
from lingua import LanguageDetectorBuilder
from nltk.corpus import stopwords
from sentence_transformers import SentenceTransformer

JSON_LISTAS = ("ids", "titulos", "artistas", "idiomas", "backends", "letras")

_PALABRAS_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_ETIQUETA_LRC_RE = re.compile(r"^\[[A-Za-z]+:.*?\]$", re.MULTILINE)
_MARCA_TIEMPO_RE = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{1,3})?\]")
_ETIQUETA_RE = re.compile(r"<[^>]+>")

CONFIANZA_MINIMA = float(os.environ.get("LANGUAGE_MIN_CONFIDENCE", "0.65"))
EMBEDDING_DEVICE = (os.environ.get("EMBEDDING_DEVICE") or "auto").strip().lower()
EMBEDDING_DTYPE = (os.environ.get("EMBEDDING_DTYPE") or "float16").strip().lower()
EMBEDDING_BATCH = int(os.environ.get("EMBEDDING_BATCH_SIZE", "8"))
EMBEDDING_MAX_CHARS = int(os.environ.get("EMBEDDING_MAX_CHARS", "6000"))

_NAMESPACE_PUNTOS = uuid.UUID("6f0a1f4e-7c2b-5c6d-9f10-1b2c3d4e5f60")


def limpiar_letra(texto: str) -> str:
    texto = _MARCA_TIEMPO_RE.sub(" ", texto or "")
    texto = _ETIQUETA_LRC_RE.sub(" ", texto)
    return _ETIQUETA_RE.sub(" ", texto).strip()


def id_punto(video_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE_PUNTOS, video_id))


class Indexer:
    def __init__(
        self,
        modelo_embeddings: Any = None,
        modelo_id: str | None = None,
        dimension_embeddings: int | None = None,
    ):
        self.STATES = {
            0: "En espera de documentos",
            1: "Inicializando",
            2: "Procesando documentos",
            3: "Indexando documentos",
        }
        self.state = 0
        self.languages = [
            "english",
            "spanish",
            "french",
            "german",
            "italian",
            "portuguese",
            "dutch",
            "swedish",
            "norwegian",
            "danish",
            "finnish",
        ]
        self.stop_words: dict[str, set] = {}
        self.stemmer: dict[str, Any] = {}
        self.inicializar_stopwords()
        self.inicializar_stemmer()

        self.inverted_index: dict[str, dict[int, list[int]]] = {}
        self.vocabulary: set = set()
        self.docs_id: set = set()

        self.ids: list[str] = []
        self.titulos: list[str] = []
        self.artistas: list[str] = []
        self.idiomas: list[str] = []
        self.idiomas_detectados: list[list[str]] = []
        self.backends: list[str] = []
        self.letras: list[str] = []

        self.matriz_incidencia = None
        self.matriz_bolsa_palabras = None
        self.matriz_tf = None
        self.vector_idf = None
        self.matriz_tfidf = None

        self.modelo_id = (
            modelo_id
            or os.environ.get("EMBEDDING_MODEL")
            or "Qwen/Qwen3-Embedding-0.6B"
        ).strip()
        self.modelo_embeddings = modelo_embeddings
        self.embedding_device = "unknown"
        self.matriz_embeddings_llm: np.ndarray | None = None
        self.dimension_embeddings = int(
            dimension_embeddings or os.environ.get("EMBEDDING_DIM", "1024") or 1024
        )

        self.language_detector = LanguageDetectorBuilder.from_all_languages().build()

    # ------------------------------------------------------------------
    # Inicialización
    # ------------------------------------------------------------------
    def dispositivo_embeddings(self) -> str:
        pedido = EMBEDDING_DEVICE
        if pedido in {"cpu", "cuda"}:
            if pedido == "cuda":
                try:
                    import torch

                    if not torch.cuda.is_available():
                        print(
                            "[lirify] EMBEDDING_DEVICE=cuda but CUDA is unavailable; "
                            "falling back to CPU",
                            flush=True,
                        )
                        return "cpu"
                except ImportError:
                    print(
                        "[lirify] torch is missing; falling back to CPU embeddings",
                        flush=True,
                    )
                    return "cpu"
            return pedido
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def inicializar_modelo_embeddings(self) -> Any:
        if self.modelo_embeddings is None:
            dispositivo = self.dispositivo_embeddings()
            opciones: dict[str, Any] = {"device": dispositivo}
            if dispositivo == "cuda" and EMBEDDING_DTYPE in {"float16", "half"}:
                try:
                    import torch

                    opciones["model_kwargs"] = {"torch_dtype": torch.float16}
                except ImportError:
                    pass
            self.modelo_embeddings = SentenceTransformer(self.modelo_id, **opciones)
            self.embedding_device = dispositivo
            if dispositivo == "cpu":
                try:
                    import torch

                    torch.set_num_threads(max(1, os.cpu_count() or 1))
                except ImportError:
                    pass
            print(
                f"[lirify] embeddings on {dispositivo} "
                f"(batch={EMBEDDING_BATCH}, dtype={EMBEDDING_DTYPE if dispositivo == 'cuda' else 'float32'})",
                flush=True,
            )
        return self.modelo_embeddings

    def inicializar_stopwords(self) -> None:
        descargado = False
        for language in self.languages:
            try:
                self.stop_words[language] = set(stopwords.words(language))
            except (LookupError, OSError, ValueError):
                if not descargado:
                    try:
                        nltk.download("stopwords", quiet=True)
                    except (OSError, RuntimeError):
                        pass
                    descargado = True
                try:
                    self.stop_words[language] = set(stopwords.words(language))
                except (LookupError, OSError, ValueError):
                    self.stop_words[language] = set()

    def inicializar_stemmer(self) -> None:
        from nltk.stem.snowball import SnowballStemmer

        for language in self.languages:
            try:
                self.stemmer[language] = SnowballStemmer(language)
            except (LookupError, OSError, ValueError):
                self.stemmer[language] = None

    def invalidar_matrices(self) -> None:
        self.matriz_incidencia = None
        self.matriz_bolsa_palabras = None
        self.matriz_tf = None
        self.vector_idf = None
        self.matriz_tfidf = None

    def _asegurar_metadatos(self, id_documento: int) -> None:
        while len(self.ids) <= id_documento:
            self.ids.append("")
            self.titulos.append("")
            self.artistas.append("")
            self.idiomas.append("")
            self.idiomas_detectados.append([])
            self.backends.append("")
            self.letras.append("")

    # ------------------------------------------------------------------
    # Persistencia local (JSON) para inspección y arranques en frío
    # ------------------------------------------------------------------
    def importar_inverted_index(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            data = {}

        self.inverted_index = {
            palabra: {
                int(id_documento): list(posiciones)
                for id_documento, posiciones in documentos.items()
            }
            for palabra, documentos in data.items()
        }
        self.vocabulary = set(self.inverted_index.keys())
        self.docs_id = {
            id_documento
            for documentos in self.inverted_index.values()
            for id_documento in documentos
        }
        self.invalidar_matrices()

    def exportar_inverted_index(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(self.inverted_index, file, ensure_ascii=False, indent=4)

    def a_diccionario(self, incluir_embeddings: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "modelo_id": self.modelo_id,
            "dimension": self.dimension_embeddings,
            "documentos": [
                {
                    "video_id": self.ids[i] if i < len(self.ids) else "",
                    "titulo": self.titulos[i] if i < len(self.titulos) else "",
                    "artista": self.artistas[i] if i < len(self.artistas) else "",
                    "idioma": self.idiomas[i] if i < len(self.idiomas) else "",
                    "idiomas_detectados": list(
                        self.idiomas_detectados[i]
                        if i < len(self.idiomas_detectados)
                        else []
                    ),
                    "backend": self.backends[i] if i < len(self.backends) else "",
                    "letra": self.letras[i] if i < len(self.letras) else "",
                }
                for i in sorted(self.docs_id)
            ],
            "estadisticas": self.estadisticas(),
        }
        if incluir_embeddings and self.matriz_embeddings_llm is not None:
            payload["embeddings"] = self.matriz_embeddings_llm.tolist()
        return payload

    def desde_diccionario(self, payload: dict[str, Any]) -> None:
        self.modelo_id = str(payload.get("modelo_id") or self.modelo_id)
        dimension = int(payload.get("dimension") or self.dimension_embeddings)
        self.dimension_embeddings = dimension

        documentos = payload.get("documentos") or []
        self.inverted_index = {}
        self.vocabulary = set()
        self.docs_id = set()
        self.ids = []
        self.titulos = []
        self.artistas = []
        self.idiomas = []
        self.idiomas_detectados = []
        self.backends = []
        self.letras = []

        for documento in documentos:
            self.agregar_documento(
                documento.get("letra") or documento.get("lyrics") or "",
                video_id=documento.get("video_id", ""),
                titulo=documento.get("titulo") or documento.get("title") or "",
                artista=documento.get("artista") or documento.get("artist") or "",
                idioma=documento.get("idioma") or documento.get("language") or "",
                languages=documento.get("idiomas_detectados")
                or documento.get("languages"),
                backend=documento.get("backend") or "",
            )

        embeddings = payload.get("embeddings")
        if embeddings:
            matriz = np.asarray(embeddings, dtype=np.float32)
            if matriz.shape[0] == len(self.docs_id) and matriz.shape[1] == dimension:
                self.matriz_embeddings_llm = matriz

    def guardar(self, path: str, incluir_embeddings: bool = True) -> None:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(
                self.a_diccionario(incluir_embeddings=incluir_embeddings),
                file,
                ensure_ascii=False,
            )

    def cargar(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as file:
            self.desde_diccionario(json.load(file))

    # ------------------------------------------------------------------
    # Lenguaje y texto
    # ------------------------------------------------------------------
    def detectar_idioma(self, texto: str) -> str | None:
        if not (texto or "").strip():
            return None
        idioma_detectado = self.language_detector.detect_language_of(texto)
        return idioma_detectado.name.lower() if idioma_detectado else None

    def detectar_idiomas(self, texto: str, minimo: int = 8) -> list[str]:
        """Every language detected line by line, in first-appearance order.

        Short or metadata-only lines are skipped (timestamps, ``[ar:...]`` tags),
        and the primary language of the song is usually the first entry.
        """
        detectados: list[str] = []
        for linea in (texto or "").splitlines():
            limpia = _MARCA_TIEMPO_RE.sub(" ", linea)
            limpia = _ETIQUETA_LRC_RE.sub(" ", limpia).strip()
            if len(limpia) < minimo or len(_PALABRAS_RE.findall(limpia)) < 3:
                continue

            try:
                valores = self.language_detector.compute_language_confidence_values(
                    limpia
                )
            except AttributeError:
                valores = []
            if valores:
                mejor = valores[0]
                if float(getattr(mejor, "value", 0.0)) < CONFIANZA_MINIMA:
                    continue
                deteccion = getattr(mejor, "language", None)
            else:
                deteccion = self.language_detector.detect_language_of(limpia)
            if deteccion is None:
                continue

            try:
                codigo = deteccion.iso_code_639_1.name.lower()
            except (AttributeError, ValueError):
                codigo = deteccion.name.lower()
            if codigo and codigo not in detectados:
                detectados.append(codigo)
        return detectados

    def normalizar_texto(self, texto: str, idioma: str | None) -> str | None:
        if not texto:
            return None
        if idioma == "english":
            return re.sub(r"[^a-zA-Z0-9]", " ", texto).lower()
        if idioma == "spanish":
            return re.sub(r"[^a-zA-Z0-9áéíóúüñÁÉÍÓÚÜÑ]", " ", texto).lower()
        if idioma == "french":
            return re.sub(r"[^a-zA-Z0-9àâçéèêëîïôûùüÿñæœ]", " ", texto).lower()
        if idioma == "german":
            return re.sub(r"[^a-zA-Z0-9äöüßÄÖÜ]", " ", texto).lower()
        if idioma == "italian":
            return re.sub(r"[^a-zA-Z0-9àèéìíîòóùú]", " ", texto).lower()
        if idioma == "portuguese":
            return re.sub(r"[^a-zA-Z0-9áàâãçéêíóôõúü]", " ", texto).lower()
        if idioma == "dutch":
            return re.sub(r"[^a-zA-Z0-9áéíóúüñÁÉÍÓÚÜÑ]", " ", texto).lower()
        if idioma == "swedish":
            return re.sub(r"[^a-zA-Z0-9åäöÅÄÖ]", " ", texto).lower()
        if idioma in {"norwegian", "danish"}:
            return re.sub(r"[^a-zA-Z0-9æøåÆØÅ]", " ", texto).lower()
        if idioma == "finnish":
            return re.sub(r"[^a-zA-Z0-9äöÄÖ]", " ", texto).lower()
        return re.sub(r"[^\w\s]", " ", texto).lower()

    def eliminar_stopwords(
        self, tokens: Sequence[str], idioma: str | None
    ) -> list[str] | None:
        if not tokens:
            return None
        stop = self.stop_words.get(idioma or "") or set()
        filtradas = [palabra for palabra in tokens if palabra not in stop]
        return filtradas or None

    def aplicar_stemming(
        self, tokens: Sequence[str], idioma: str | None
    ) -> list[str] | None:
        if not tokens:
            return None
        stemmer = self.stemmer.get(idioma or "")
        if stemmer is None:
            return list(tokens)
        return [stemmer.stem(palabra) for palabra in tokens]

    def tokenizar_texto(
        self, texto: str, idioma: str | None = None
    ) -> list[str] | None:
        if not texto:
            return None
        return _PALABRAS_RE.findall(texto)

    def procesar_texto(self, texto: str) -> list[str] | None:
        """Return one flat list of terms for the whole (multi-line) text."""
        if not texto:
            return None
        procesed_text: list[str] = []
        for line in texto.splitlines():
            idioma = self.detectar_idioma(line)
            if not idioma:
                continue
            line = self.normalizar_texto(line, idioma)
            if not line:
                continue
            line = self.tokenizar_texto(line, idioma)
            if not line:
                continue
            line = self.eliminar_stopwords(line, idioma)
            if not line:
                continue
            line = self.aplicar_stemming(line, idioma)
            if not line:
                continue
            procesed_text.extend(line)
        return procesed_text or None

    # ------------------------------------------------------------------
    # Indexación
    # ------------------------------------------------------------------
    def agregar_documento(
        self,
        texto: str,
        video_id: str = "",
        titulo: str = "",
        artista: str = "",
        idioma: str = "",
        backend: str = "",
        languages: Iterable[str] | None = None,
    ) -> int | None:
        if not texto:
            return None

        palabras_procesadas = self.procesar_texto(texto)
        if not palabras_procesadas:
            return None

        id_documento = max(self.docs_id, default=-1) + 1
        self.docs_id.add(id_documento)
        self._asegurar_metadatos(id_documento)
        self.ids[id_documento] = video_id
        self.titulos[id_documento] = titulo
        self.artistas[id_documento] = artista
        self.idiomas[id_documento] = idioma
        detectados = list(languages) if languages else self.detectar_idiomas(texto)
        if idioma and idioma != "unknown" and idioma not in detectados:
            detectados.insert(0, idioma)
        self.idiomas_detectados[id_documento] = detectados
        self.backends[id_documento] = backend
        self.letras[id_documento] = texto

        for posicion, palabra in enumerate(palabras_procesadas):
            if palabra not in self.vocabulary:
                self.vocabulary.add(palabra)
                self.inverted_index[palabra] = {}
            self.inverted_index[palabra].setdefault(id_documento, []).append(posicion)

        self.invalidar_matrices()
        return id_documento

    def agregar_cancion(self, cancion: dict[str, Any]) -> int | None:
        video_id = str(cancion.get("video_id") or cancion.get("videoId") or "")
        letra = str(cancion.get("lyrics") or cancion.get("letra") or "")
        id_documento = self.agregar_documento(
            letra,
            video_id=video_id,
            titulo=str(
                cancion.get("track")
                or cancion.get("title")
                or cancion.get("titulo")
                or ""
            ),
            artista=str(cancion.get("artist") or cancion.get("artista") or ""),
            idioma=str(cancion.get("language") or cancion.get("idioma") or ""),
            backend=str(cancion.get("backend") or ""),
            languages=cancion.get("languages") or cancion.get("idiomas_detectados"),
        )
        if id_documento is not None:
            cancion["languages"] = list(self.idiomas_detectados[id_documento])
        return id_documento

    def indexar_canciones(
        self, canciones: Iterable[dict[str, Any]], calcular_embeddings: bool = True
    ) -> list[int]:
        existentes = {video_id for video_id in self.ids if video_id}
        agregados = []
        for cancion in canciones:
            video_id = str(cancion.get("video_id") or cancion.get("videoId") or "")
            if video_id and video_id in existentes:
                continue
            id_documento = self.agregar_cancion(cancion)
            if id_documento is None:
                continue
            if video_id:
                existentes.add(video_id)
            agregados.append(id_documento)
        if agregados and calcular_embeddings and self.matriz_embeddings_llm is not None:
            for id_documento in agregados:
                self.agregar_documento_con_embeddings(id_documento)
        return agregados

    def id_de(self, video_id: str) -> int | None:
        for id_documento, actual in enumerate(self.ids):
            if actual == video_id:
                return id_documento
        return None

    def _quitar_terminos(self, id_documento: int) -> None:
        for palabra in list(self.inverted_index):
            documentos = self.inverted_index[palabra]
            if id_documento not in documentos:
                continue
            del documentos[id_documento]
            if not documentos:
                del self.inverted_index[palabra]
                self.vocabulary.discard(palabra)

    def _aplicar_terminos(self, id_documento: int, terminos: Sequence[str]) -> None:
        for posicion, palabra in enumerate(terminos):
            self.vocabulary.add(palabra)
            self.inverted_index.setdefault(palabra, {}).setdefault(
                id_documento, []
            ).append(posicion)

    def actualizar_cancion(self, cancion: dict[str, Any]) -> bool:
        """Update one indexed song in place; returns False when it is unknown."""
        video_id = str(cancion.get("video_id") or cancion.get("videoId") or "")
        id_documento = self.id_de(video_id)
        if id_documento is None:
            return False

        letra = str(cancion.get("lyrics") or cancion.get("letra") or "")
        terminos = self.procesar_texto(letra) or []
        self._quitar_terminos(id_documento)
        if terminos:
            self._aplicar_terminos(id_documento, terminos)

        self.ids[id_documento] = video_id
        self.titulos[id_documento] = str(
            cancion.get("track") or cancion.get("title") or ""
        )
        self.artistas[id_documento] = str(cancion.get("artist") or "")
        idioma = str(cancion.get("language") or "")
        self.idiomas[id_documento] = idioma
        detectados = list(
            cancion.get("languages") or cancion.get("idiomas_detectados") or []
        ) or self.detectar_idiomas(letra)
        if idioma and idioma != "unknown" and idioma not in detectados:
            detectados.insert(0, idioma)
        self.idiomas_detectados[id_documento] = detectados
        self.backends[id_documento] = str(cancion.get("backend") or "")
        self.letras[id_documento] = letra

        self.invalidar_matrices()
        if self.matriz_embeddings_llm is not None:
            if terminos:
                self.agregar_documento_con_embeddings(id_documento)
            else:
                self.matriz_embeddings_llm[id_documento] = 0.0
        return True

    def eliminar_cancion(self, video_id: str) -> bool:
        """Remove one song, compacting the last document into its slot."""
        id_documento = self.id_de(video_id)
        if id_documento is None:
            return False

        self._quitar_terminos(id_documento)
        ultimo = max(self.docs_id)
        if id_documento != ultimo:
            for documentos in self.inverted_index.values():
                if ultimo in documentos:
                    documentos[id_documento] = documentos.pop(ultimo)
            for campo in (
                self.ids,
                self.titulos,
                self.artistas,
                self.idiomas,
                self.idiomas_detectados,
                self.backends,
                self.letras,
            ):
                if ultimo < len(campo):
                    campo[id_documento] = campo[ultimo]

        self.docs_id.discard(ultimo)
        for campo in (
            self.ids,
            self.titulos,
            self.artistas,
            self.idiomas,
            self.idiomas_detectados,
            self.backends,
            self.letras,
        ):
            while len(campo) > ultimo:
                campo.pop()

        if self.matriz_embeddings_llm is not None:
            if id_documento != ultimo:
                self.matriz_embeddings_llm[id_documento] = self.matriz_embeddings_llm[
                    ultimo
                ]
            self.matriz_embeddings_llm = self.matriz_embeddings_llm[:ultimo]

        self.invalidar_matrices()
        return True

    def limpiar(self) -> None:
        self.inverted_index = {}
        self.vocabulary = set()
        self.docs_id = set()
        self.ids = []
        self.titulos = []
        self.artistas = []
        self.idiomas = []
        self.idiomas_detectados = []
        self.backends = []
        self.letras = []
        self.matriz_embeddings_llm = None
        self.invalidar_matrices()

    def construir_matriz_incidencia_binaria(self) -> np.ndarray:
        matriz = np.zeros((len(self.vocabulary), len(self.docs_id)), dtype=int)
        for i, palabra in enumerate(self.vocabulary):
            for j, id_documento in enumerate(sorted(self.docs_id)):
                if id_documento in self.inverted_index[palabra]:
                    matriz[i][j] = 1
        return matriz

    def construir_bolsa_de_palabras(self) -> np.ndarray:
        matriz = np.zeros((len(self.vocabulary), len(self.docs_id)), dtype=int)
        for i, palabra in enumerate(self.vocabulary):
            for j, id_documento in enumerate(sorted(self.docs_id)):
                if id_documento in self.inverted_index[palabra]:
                    matriz[i][j] = len(self.inverted_index[palabra][id_documento])
        return matriz

    def construir_matriz_tf(self) -> np.ndarray:
        if self.matriz_bolsa_palabras is None:
            self.matriz_bolsa_palabras = self.construir_bolsa_de_palabras()
        matriz_tf = np.zeros_like(self.matriz_bolsa_palabras, dtype=float)
        data = self.matriz_bolsa_palabras
        condicion = data > 0
        matriz_tf = np.log10(data, where=condicion, out=matriz_tf)
        matriz_tf[condicion] += 1
        return matriz_tf

    def construir_vector_idf(self) -> np.ndarray:
        if self.matriz_incidencia is None:
            self.matriz_incidencia = self.construir_matriz_incidencia_binaria()
        df = np.sum(self.matriz_incidencia, axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            idf = np.log10(max(len(self.docs_id), 1) / np.where(df == 0, 1, df))
        return np.nan_to_num(idf, nan=0.0, posinf=0.0, neginf=0.0)

    def construir_matriz_tfidf(self) -> np.ndarray:
        if self.matriz_tf is None:
            self.matriz_tf = self.construir_matriz_tf()
        if self.vector_idf is None:
            self.vector_idf = self.construir_vector_idf()
        matriz = self.matriz_tf * self.vector_idf[:, np.newaxis]
        normas = np.linalg.norm(matriz, axis=0)
        normas[normas == 0] = 1.0
        return matriz / normas

    def construir_matriz_similaridad_coseno(self) -> np.ndarray:
        if self.matriz_tfidf is None:
            self.matriz_tfidf = self.construir_matriz_tfidf()
        similitud = self.matriz_tfidf.T @ self.matriz_tfidf
        return np.clip(similitud, 0.0, 1.0)

    def construir_matriz_distancia_coseno(self) -> np.ndarray:
        return 1 - self.construir_matriz_similaridad_coseno()

    def reconstruir_documento(self, id_documento: int) -> list[str]:
        if id_documento not in self.docs_id:
            return []
        return [
            palabra
            for palabra in self.vocabulary
            if id_documento in self.inverted_index[palabra]
        ]

    # ------------------------------------------------------------------
    # Embeddings LLM
    # ------------------------------------------------------------------
    def _texto_embedding(self, id_documento: int) -> str:
        letra = self.letras[id_documento] if id_documento < len(self.letras) else ""
        return limpiar_letra(letra) or " ".join(
            self.reconstruir_documento(id_documento)
        )

    def _recortar(self, texto: str) -> str:
        return (texto or "")[:EMBEDDING_MAX_CHARS]

    def _codificar(self, textos: Sequence[str]) -> np.ndarray:
        modelo = self.inicializar_modelo_embeddings()
        vectores = modelo.encode(
            [self._recortar(texto) for texto in textos],
            batch_size=max(1, EMBEDDING_BATCH),
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        matriz = np.asarray(vectores, dtype=np.float32)
        return matriz.reshape(len(textos), -1)

    def embedding_de_texto(self, texto: str) -> list[float]:
        vector = self._codificar([self._recortar(limpiar_letra(texto) or texto)])[0]
        self.dimension_embeddings = int(vector.shape[0])
        return vector.astype(float).tolist()

    def construir_matriz_embeddings_llm(self) -> np.ndarray:
        ids = sorted(self.docs_id)
        if not ids:
            self.matriz_embeddings_llm = np.zeros(
                (0, self.dimension_embeddings), dtype=np.float32
            )
            return self.matriz_embeddings_llm
        matriz = self._codificar([self._texto_embedding(i) for i in ids])
        self.dimension_embeddings = int(matriz.shape[1])
        self.matriz_embeddings_llm = matriz
        return matriz

    def agregar_documento_con_embeddings(self, id_documento: int) -> None:
        vector = self._codificar([self._texto_embedding(id_documento)])[0]
        if self.matriz_embeddings_llm is None:
            self.matriz_embeddings_llm = vector.reshape(1, -1)
            return
        if id_documento < len(self.matriz_embeddings_llm):
            self.matriz_embeddings_llm[id_documento] = vector
        else:
            self.matriz_embeddings_llm = np.vstack(
                [self.matriz_embeddings_llm, vector.reshape(1, -1)]
            )

    def _matriz_embeddings_normalizada(self) -> np.ndarray | None:
        if self.matriz_embeddings_llm is None:
            if not self.docs_id:
                return None
            self.construir_matriz_embeddings_llm()
        matriz = self.matriz_embeddings_llm
        if matriz is None or not len(matriz):
            return None
        normas = np.linalg.norm(matriz, axis=1, keepdims=True)
        normas[normas == 0] = 1.0
        return matriz / normas

    # ------------------------------------------------------------------
    # Consultas (búsqueda y recomendación sobre embeddings)
    # ------------------------------------------------------------------
    def _tokens_meta(self, texto: str) -> set:
        return set(_PALABRAS_RE.findall((texto or "").lower()))

    def _bonificacion_meta(self, consulta: str, id_documento: int) -> float:
        tokens = self._tokens_meta(consulta)
        if not tokens:
            return 0.0
        titulo = self._tokens_meta(
            self.titulos[id_documento] if id_documento < len(self.titulos) else ""
        )
        artista = self._tokens_meta(
            self.artistas[id_documento] if id_documento < len(self.artistas) else ""
        )
        nombre = len(tokens & titulo) / max(len(tokens), 1)
        autor = len(tokens & artista) / max(len(tokens), 1)
        return 0.5 * nombre + 0.3 * autor

    def _resumen(self, id_documento: int, puntaje: float) -> dict[str, Any]:
        return {
            "video_id": self.ids[id_documento] if id_documento < len(self.ids) else "",
            "title": self.titulos[id_documento]
            if id_documento < len(self.titulos)
            else "",
            "artist": self.artistas[id_documento]
            if id_documento < len(self.artistas)
            else "",
            "language": self.idiomas[id_documento]
            if id_documento < len(self.idiomas)
            else "",
            "score": round(float(puntaje), 6),
        }

    def buscar(self, consulta: str, limite: int = 20) -> dict[str, Any]:
        """Rank indexed songs against a free-text query using LLM embeddings."""
        limite = max(1, min(int(limite or 20), 100))
        if not (consulta or "").strip() or not self.docs_id:
            return {"query": consulta, "results": [], "engine": "embeddings"}

        matriz = self._matriz_embeddings_normalizada()
        if matriz is None:
            return {"query": consulta, "results": [], "engine": "none"}

        vector = self._codificar([consulta])[0]
        norma = float(np.linalg.norm(vector))
        if norma == 0:
            return {"query": consulta, "results": [], "engine": "embeddings"}
        similitudes = matriz @ (vector / norma)

        orden = np.argsort(-similitudes)
        resultados = []
        for posicion in orden:
            id_documento = int(posicion)
            puntaje = float(similitudes[id_documento])
            puntaje += self._bonificacion_meta(consulta, id_documento)
            if puntaje <= 0:
                continue
            resultados.append(self._resumen(id_documento, puntaje))
            if len(resultados) >= limite:
                break
        resultados.sort(key=lambda fila: -fila["score"])
        return {"query": consulta, "results": resultados, "engine": "embeddings"}

    def recomendar(self, video_ids: Sequence[str], limite: int = 10) -> dict[str, Any]:
        """Recommend songs similar to the given seeds (browser-owned history)."""
        limite = max(1, min(int(limite or 10), 50))
        seeds = [
            video_id
            for video_id in dict.fromkeys(video_ids or [])
            if video_id in self.ids
        ]
        if not seeds:
            return {
                "seed_video_id": "",
                "recommendations": [],
                "engine": "none",
            }

        matriz = self._matriz_embeddings_normalizada()
        if matriz is None:
            return {
                "seed_video_id": seeds[0],
                "recommendations": [],
                "engine": "none",
            }

        indice_por_id = {video_id: i for i, video_id in enumerate(self.ids)}
        totales: dict[int, float] = {}
        for posicion, video_id in enumerate(seeds[:5]):
            peso = 1.0 / (1 + posicion)
            fila = indice_por_id[video_id]
            similitudes = matriz @ matriz[fila]
            for id_documento in np.argsort(-similitudes)[: limite * 3 + len(seeds)]:
                id_documento = int(id_documento)
                if self.ids[id_documento] in seeds:
                    continue
                totales[id_documento] = totales.get(id_documento, 0.0) + peso * float(
                    similitudes[id_documento]
                )

        semilla = indice_por_id[seeds[0]]
        ranked = sorted(totales.items(), key=lambda fila: -fila[1])[:limite]
        recomendaciones = []
        for id_documento, similitud in ranked:
            puntaje = (
                0.85 * similitud
                + 0.10 * self._jaccard_meta(semilla, id_documento, self.titulos)
                + 0.05 * self._jaccard_meta(semilla, id_documento, self.artistas)
            )
            recomendaciones.append(self._resumen(id_documento, puntaje))

        return {
            "seed_video_id": seeds[0],
            "seed_video_ids": seeds,
            "recommendations": recomendaciones,
            "engine": "embeddings",
            "weights": {"name": 0.10, "artist": 0.05, "lyrics": 0.85},
        }

    def _jaccard_meta(self, izquierda: int, derecha: int, campo: list[str]) -> float:
        if izquierda >= len(campo) or derecha >= len(campo):
            return 0.0
        a = self._tokens_meta(campo[izquierda])
        b = self._tokens_meta(campo[derecha])
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def estadisticas(self) -> dict[str, Any]:
        idiomas: dict[str, int] = {}
        detectados: dict[str, int] = {}
        backends: dict[str, int] = {}
        for i in sorted(self.docs_id):
            if i < len(self.idiomas) and self.idiomas[i]:
                idiomas[self.idiomas[i]] = idiomas.get(self.idiomas[i], 0) + 1
            if i < len(self.idiomas_detectados):
                for idioma in self.idiomas_detectados[i]:
                    detectados[idioma] = detectados.get(idioma, 0) + 1
            if i < len(self.backends) and self.backends[i]:
                backends[self.backends[i]] = backends.get(self.backends[i], 0) + 1
        tokens = sum(
            len(posiciones)
            for documentos in self.inverted_index.values()
            for posiciones in documentos.values()
        )
        return {
            "songs_indexed": len(self.docs_id),
            "video_ids": sum(1 for video_id in self.ids if video_id),
            "vocabulary_size": len(self.vocabulary),
            "inverted_terms": len(self.inverted_index),
            "lyrics_tokens": tokens,
            "languages": idiomas,
            "detected_languages": detectados,
            "backends": backends,
            "embedding_model": self.modelo_id,
            "embedding_dim": self.dimension_embeddings,
            "embedding_provider": "sentence-transformers",
            "embedding_device": self.embedding_device,
            "embedding_batch_size": EMBEDDING_BATCH,
            "state": self.STATES.get(self.state, ""),
        }

    async def get_state(self) -> int:
        return self.state

    # ------------------------------------------------------------------
    # Publicación a la nube (solo canciones + embeddings LLM)
    # ------------------------------------------------------------------
    def _documento_de_cancion(
        self, cancion: dict[str, Any], ahora: float | None = None
    ) -> dict[str, Any] | None:
        video_id = str(cancion.get("video_id") or cancion.get("videoId") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
            return None
        letra = str(cancion.get("lyrics") or "")
        if not letra.strip():
            return None
        return {
            "videoId": video_id,
            "title": str(cancion.get("track") or cancion.get("title") or ""),
            "youtubeTitle": str(cancion.get("title") or cancion.get("track") or ""),
            "artist": str(cancion.get("artist") or ""),
            "language": str(cancion.get("language") or ""),
            "languages": list(
                cancion.get("languages")
                or cancion.get("idiomas_detectados")
                or ([cancion.get("language")] if cancion.get("language") else [])
            ),
            "lyrics": letra,
            "backend": str(cancion.get("backend") or ""),
            "schemaVersion": 1,
            "updatedAt": ahora or time.time(),
        }

    def _documentos_mongo(self) -> list[dict[str, Any]]:
        documentos = []
        vistos: set[str] = set()
        for i in sorted(self.docs_id):
            documento = self._documento_de_cancion(
                {
                    "video_id": self.ids[i] if i < len(self.ids) else "",
                    "track": self.titulos[i] if i < len(self.titulos) else "",
                    "artist": self.artistas[i] if i < len(self.artistas) else "",
                    "language": self.idiomas[i] if i < len(self.idiomas) else "",
                    "languages": list(
                        self.idiomas_detectados[i]
                        if i < len(self.idiomas_detectados)
                        else []
                    ),
                    "lyrics": self.letras[i] if i < len(self.letras) else "",
                    "backend": self.backends[i] if i < len(self.backends) else "",
                }
            )
            if documento is None or documento["videoId"] in vistos:
                continue
            vistos.add(documento["videoId"])
            documentos.append(documento)
        return documentos

    def _puntos_de_canciones(
        self, canciones: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        validas = []
        for cancion in canciones:
            documento = self._documento_de_cancion(cancion)
            if documento is not None:
                validas.append((documento, cancion))
        if not validas:
            return []
        vectores = self._codificar(
            [
                limpiar_letra(documento["lyrics"]) or documento["lyrics"]
                for documento, _ in validas
            ]
        )
        self.dimension_embeddings = int(vectores.shape[1])
        return [
            {
                "id": id_punto(documento["videoId"]),
                "vector": vector.astype(float).tolist(),
                "payload": {
                    "video_id": documento["videoId"],
                    "title": documento["title"],
                    "artist": documento["artist"],
                    "language": documento["language"],
                },
            }
            for (documento, _), vector in zip(validas, vectores)
        ]

    def _puntos_qdrant(self) -> list[dict[str, Any]]:
        if self.matriz_embeddings_llm is None:
            return []
        puntos = []
        for i in sorted(self.docs_id):
            video_id = self.ids[i] if i < len(self.ids) else ""
            if not video_id:
                continue
            puntos.append(
                {
                    "id": id_punto(video_id),
                    "vector": self.matriz_embeddings_llm[i].astype(float).tolist(),
                    "payload": {
                        "video_id": video_id,
                        "title": self.titulos[i] or "",
                        "artist": self.artistas[i] or "",
                        "language": self.idiomas[i] or "",
                    },
                }
            )
        return puntos

    def publicar(
        self,
        mongo_uri: str | None = None,
        db_name: str | None = None,
        qdrant_url: str | None = None,
        qdrant_api_key: str | None = None,
        coleccion: str | None = None,
        lote: int = 64,
        solo: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Write songs to Atlas and LLM embeddings to Qdrant. Nothing else.

        ``solo`` limits the write to a freshly indexed batch: only those songs are
        embedded and upserted, instead of re-encoding the whole library.
        """
        from pymongo import MongoClient, UpdateOne

        uri = (
            mongo_uri
            or os.environ.get("MONGODB_URI")
            or os.environ.get("MONGO_URI")
            or ""
        ).strip()
        db_name = db_name or os.environ.get("MONGODB_DB") or "lirify"
        qdrant_url = (qdrant_url or os.environ.get("QDRANT_URL") or "").strip()
        qdrant_api_key = (
            qdrant_api_key or os.environ.get("QDRANT_API_KEY") or ""
        ).strip()
        coleccion = (
            coleccion or os.environ.get("QDRANT_COLLECTION") or "lirify_lyrics_qwen3"
        ).strip()

        if not uri:
            raise RuntimeError("MONGODB_URI is required to publish")

        puntos = None
        if solo is None:
            canciones = self._documentos_mongo()
        else:
            lote_canciones = list(solo)
            documentos = [
                documento
                for documento in (
                    self._documento_de_cancion(cancion) for cancion in lote_canciones
                )
                if documento is not None
            ]
            canciones = documentos
            puntos = self._puntos_de_canciones(lote_canciones)
        if not canciones:
            raise RuntimeError(
                "Nothing indexed yet: index a playlist before publishing"
            )
        if solo is None and self.matriz_embeddings_llm is None:
            self.construir_matriz_embeddings_llm()

        cliente = MongoClient(uri, serverSelectionTimeoutMS=15000)
        base = cliente[db_name]
        try:
            base["songs"].create_index("videoId", unique=True)
            base["songs"].create_index("language")
        except Exception as exc:  # noqa: BLE001 - an existing cluster keeps serving
            print(f"[lirify] song indexes not created: {exc}", flush=True)
        operaciones = [
            UpdateOne(
                {"videoId": cancion["videoId"]},
                {
                    "$set": cancion,
                    "$setOnInsert": {"createdAt": cancion["updatedAt"]},
                },
                upsert=True,
            )
            for cancion in canciones
        ]
        resultado = base["songs"].bulk_write(operaciones, ordered=False)
        escritos = int(resultado.upserted_count + resultado.modified_count)

        vectores = 0
        if qdrant_url:
            vectores = self._publicar_qdrant(
                qdrant_url, qdrant_api_key, coleccion, lote, puntos
            )

        estadisticas = self.estadisticas()
        revision = 0
        try:
            base["index_stats"].update_one(
                {"_id": "global"},
                {
                    "$set": {
                        "build": estadisticas,
                        "updatedAt": time.time(),
                        "schemaVersion": 1,
                    },
                    "$inc": {"revision": 1},
                },
                upsert=True,
            )
            documento = base["index_stats"].find_one({"_id": "global"}) or {}
            revision = int(documento.get("revision") or 0)
        finally:
            cliente.close()

        return {
            "published": True,
            "songs": len(canciones),
            "written": escritos,
            "vectors": vectores,
            "revision": revision,
            "database": db_name,
            "collection": coleccion if qdrant_url else "",
            "embedding_model": self.modelo_id,
            "embedding_dim": self.dimension_embeddings,
        }

    def _publicar_qdrant(
        self,
        url: str,
        api_key: str,
        coleccion: str,
        lote: int,
        puntos: list[dict[str, Any]] | None = None,
    ) -> int:
        import requests

        if puntos is None:
            puntos = self._puntos_qdrant()
        if not puntos:
            return 0
        base = url.rstrip("/")
        cabeceras = {"Content-Type": "application/json"}
        if api_key:
            cabeceras["api-key"] = api_key
        recurso = f"{base}/collections/{coleccion}"

        respuesta = requests.get(recurso, headers=cabeceras, timeout=15)
        if respuesta.status_code == 404:
            creada = requests.put(
                recurso,
                headers=cabeceras,
                json={
                    "vectors": {
                        "size": self.dimension_embeddings,
                        "distance": "Cosine",
                    }
                },
                timeout=30,
            )
            if creada.status_code >= 400:
                raise RuntimeError(
                    f"qdrant create {coleccion} -> {creada.status_code}: "
                    f"{creada.text[:300]}"
                )

        escritos = 0
        for inicio in range(0, len(puntos), max(1, lote)):
            chunk = puntos[inicio : inicio + max(1, lote)]
            subida = requests.put(
                f"{recurso}/points?wait=true",
                headers=cabeceras,
                json={"points": chunk},
                timeout=60,
            )
            if subida.status_code >= 400:
                raise RuntimeError(
                    f"qdrant upsert -> {subida.status_code}: {subida.text[:300]}"
                )
            escritos += len(chunk)
        return escritos


if __name__ == "__main__":
    print("=== 1. INICIALIZANDO INDEXER ===")
    indexer = Indexer()
    print(f"Estado actual: {indexer.STATES[indexer.state]}")
    print(f"Idiomas cargados ({len(indexer.languages)}): {indexer.languages}\n")

    print("=== 2. PIPELINE INDIVIDUAL ===")
    prueba_es = "Los programadores estaban desarrollando algoritmos rápidos en Python."
    idioma = indexer.detectar_idioma(prueba_es)
    norm = indexer.normalizar_texto(prueba_es, idioma)
    tokens = indexer.tokenizar_texto(norm, idioma)
    sin_sw = indexer.eliminar_stopwords(tokens, idioma)
    stems = indexer.aplicar_stemming(sin_sw, idioma)
    print(f"Idioma:      {idioma}")
    print(f"Normalizado: {norm}")
    print(f"Tokens:      {tokens}")
    print(f"Sin SW:      {sin_sw}")
    print(f"Stemming:    {stems}\n")

    print("=== 3. AGREGADO DE DOCUMENTOS ===")
    doc_0 = """
    La inteligencia artificial transforma la recuperación de información.
    Information retrieval systems index multilingual documents efficiently.
    """
    doc_1 = """
    L'apprentissage automatique permet d'analyser des textes complexes.
    Los algoritmos de búsqueda utilizan matrices dispersas y embeddings.
    """
    doc_2 = "Die schnelle braune Fuchs springt über den faulen Hund."

    id0 = indexer.agregar_documento(doc_0, video_id="aaaaaaaaaaa", titulo="Uno")
    id1 = indexer.agregar_documento(doc_1, video_id="bbbbbbbbbbb", titulo="Dos")
    id2 = indexer.agregar_documento(doc_2, video_id="ccccccccccc", titulo="Drei")
    print(f"IDs: {id0}, {id1}, {id2}")
    print(f"Vocabulario: {len(indexer.vocabulary)} palabras")
    print(f"Estadísticas: {indexer.estadisticas()}\n")

    print("=== 4. EXPORTACIÓN E IMPORTACIÓN JSON ===")
    ruta_json = "test_inverted_index.json"
    indexer.exportar_inverted_index(ruta_json)
    print(f"Índice exportado a '{ruta_json}'.")
