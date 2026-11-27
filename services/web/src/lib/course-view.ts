import { escapeHtml, highlight } from "./format";
import { iconMarkup } from "./icons";
import { text } from "./locale";
import type { CourseSearchPayload, Track } from "./types";

const integer = new Intl.NumberFormat(text("es-EC", "en-US"));
const similarity = new Intl.NumberFormat(text("es-EC", "en-US"), {
  style: "percent", maximumFractionDigits: 1,
});

export function courseLanding(search: (query: string) => void): HTMLElement {
  const landing = document.createElement("section");
  landing.className = "course-landing";
  landing.innerHTML = `
    <div class="page-head"><div>
      <h1>${text("Encuentra una canción por su letra", "Find a song by its lyrics")}</h1>
      <p>${text("Escribe una frase que recuerdes o reproduce una canción del catálogo.", "Enter a line you remember or play a song from the catalogue.")}</p>
    </div></div>
    <form class="course-form" role="search">
      <label class="sr-only" for="course-query">${text("Palabra o frase de la canción", "Word or phrase from the song")}</label>
      <input id="course-query" type="search" name="q" maxlength="200" required autocomplete="off" spellcheck="false" enterkeyhint="search" placeholder="${text("Vivo por amarte", "Somewhere in the night")}" />
      <button type="submit" class="btn btn-primary">${iconMarkup("search", "", 18)} ${text("Buscar", "Search")}</button>
    </form>
    <div class="course-examples"><span>${text("Prueba con", "Try")}</span>
      <button type="button" class="chip" value="corazón">corazón</button>
      <button type="button" class="chip" value="midnight">midnight</button>
      <button type="button" class="chip" value="fuego">fuego</button>
    </div>
    <section id="course-catalogue" class="course-catalogue">
      <div class="shelf-head"><div><h2>${text("Tu catálogo", "Your catalogue")}</h2></div>
      <a class="shelf-link" href="#/library">${text("Ver todas", "View all")}</a></div>
      <div id="course-catalogue-content" role="status" class="muted">${text("Cargando canciones…", "Loading songs…")}</div>
    </section>
    <a class="btn btn-outline" href="#/import">${iconMarkup("plus", "", 18)} ${text("Agregar una playlist al catálogo", "Add a playlist to the catalogue")}</a>`;
  const form = landing.querySelector<HTMLFormElement>("form")!;
  const input = form.querySelector<HTMLInputElement>("input")!;
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (input.value.trim()) search(input.value.trim());
  });
  for (const button of landing.querySelectorAll<HTMLButtonElement>(".course-examples button")) {
    button.addEventListener("click", () => search(button.value));
  }
  return landing;
}

type RenderRow = (track: Track, index: number, queue: Track[], key: string) => HTMLElement;

export function courseResults(payload: CourseSearchPayload, renderRow: RenderRow): HTMLElement {
  const section = document.createElement("section");
  section.className = "course-results";
  const count = payload.results.length;
  section.innerHTML = `<header class="page-head"><div>
    <h1 id="course-results-title">“${escapeHtml(payload.query)}”</h1>
    <p>${count} ${count === 1 ? text("resultado", "result") : text("resultados", "results")} · ${integer.format(payload.scanned)} ${text("canciones en el índice", "songs in the index")}</p>
  </div></header>`;
  if (!count) {
    const empty = document.createElement("p");
    empty.className = "course-status";
    empty.textContent = payload.scanned
      ? text("No encontramos coincidencias en las letras. Prueba con otra frase.", "No lyric matches. Try another phrase.")
      : text("El catálogo está vacío. Agrega una playlist para empezar.", "Your catalogue is empty. Add a playlist to get started.");
    section.append(empty);
    if (!payload.scanned) {
      const link = document.createElement("a");
      link.className = "btn btn-primary";
      link.href = "#/import";
      link.textContent = text("Agregar playlist", "Add playlist");
      section.append(link);
    }
    return section;
  }
  const list = document.createElement("ol");
  list.className = "course-result-list";
  payload.results.forEach((track, index) => {
    const row = document.createElement("li");
    row.className = "course-result";
    const article = document.createElement("article");
    article.append(renderRow(track, index, payload.results, "course:results"));
    const meta = document.createElement("div");
    meta.className = "course-match-meta";
    meta.innerHTML = `<span class="course-score">${similarity.format(track.score)} ${text("de similitud coseno", "cosine similarity")}</span>
      ${track.snippet ? `<blockquote class="course-lyric" lang="${track.language === "es" ? "es" : "en"}">“${highlight(track.snippet, payload.query)}”</blockquote>` : ""}`;
    article.append(meta);
    if (track.recommendations.length) {
      const details = document.createElement("details");
      details.className = "course-recommendations";
      details.open = index === 0;
      const summary = document.createElement("summary");
      summary.textContent = `${track.recommendations.length} ${text("canciones similares", "similar songs")}`;
      const recommendations = document.createElement("ul");
      track.recommendations.forEach((recommendation, i) => {
        const item = document.createElement("li");
        item.append(renderRow(recommendation, i, track.recommendations, `course:similar:${track.id}`));
        recommendations.append(item);
      });
      details.append(summary, recommendations);
      article.append(details);
    }
    row.append(article);
    list.append(row);
  });
  section.append(list);
  return section;
}
