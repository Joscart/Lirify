import { api } from "./api";
import { courseLanding, courseResults } from "./course-view";
import { emit } from "./bus";
import {
  escapeHtml,
  fmtCount,
  fmtDuration,
  fmtTime,
  greeting,
} from "./format";
import { iconMarkup } from "./icons";
import { recordSearch, seeds } from "./history";
import { text } from "./locale";
import { player } from "./player";
import type {
  Artist,
  Bootstrap,
  Playlist,
  Shelf,
  Track,
  ViewName,
} from "./types";

export interface Route {
  name: ViewName;
  param?: string;
  query?: string;
}

interface RenderOptions {
  video?: boolean;
  tag?: string;
}

const sources = new Map<string, Track[]>();
const tracksById = new Map<string, Track>();
const playlistsById = new Map<string, Playlist>();
const artistsById = new Map<string, Artist>();

let bootstrap: Bootstrap | null = null;
let bootstrapPromise: Promise<Bootstrap> | null = null;
let renderToken = 0;

export function getBootstrap(force = false): Promise<Bootstrap> {
  if (bootstrap && !force) return Promise.resolve(bootstrap);
  if (bootstrapPromise && !force) return bootstrapPromise;
  bootstrapPromise = api
    .bootstrap()
    .then((data) => {
      bootstrap = data;
      data.artists.forEach((artist) => artistsById.set(artist.id, artist));
      data.playlists.forEach((playlist) => playlistsById.set(playlist.id, playlist));
      emit("bootstrap", data);
      return data;
    })
    .finally(() => {
      bootstrapPromise = null;
    });
  return bootstrapPromise;
}

export function getCachedBootstrap(): Bootstrap | null {
  return bootstrap;
}

export function navigate(path: string): void {
  if (location.hash === `#${path}`) return;
  location.hash = path;
}

function registerSource(key: string, tracks: Track[]): string {
  sources.set(key, tracks);
  tracks.forEach((track) => tracksById.set(track.id, track));
  return key;
}

function cloneTemplate(id: string): HTMLElement {
  const template = document.getElementById(id) as HTMLTemplateElement | null;
  if (!template) throw new Error(`Missing template ${id}`);
  return template.content.firstElementChild!.cloneNode(true) as HTMLElement;
}

function setArt(
  img: HTMLImageElement | null,
  fallback: HTMLElement | null,
  url: string,
  alt = "",
  retryUrl = "",
) {
  if (!img) return;
  if (!url) {
    img.hidden = true;
    return;
  }
  img.hidden = false;
  img.alt = alt;
  img.loading = "lazy";
  img.decoding = "async";
  img.onerror = () => {
    if (retryUrl && img.src !== retryUrl) {
      img.src = retryUrl;
      return;
    }
    img.hidden = true;
  };
  img.src = url;
  if (fallback) fallback.dataset.ready = "true";
}

function durationLabel(track: Track): string {
  if (!track.duration) return "—";
  return `${track.duration_estimated ? "~" : ""}${fmtTime(track.duration)}`;
}

function artistHref(artistId: string): string {
  return `#/artist/${encodeURIComponent(artistId)}`;
}

function playlistHref(id: string): string {
  return `#/playlist/${encodeURIComponent(id)}`;
}

// ---------------------------------------------------------------------------
// Cards
// ---------------------------------------------------------------------------

export function trackCard(track: Track, sourceKey: string, options: RenderOptions = {}): HTMLElement {
  const card = cloneTemplate(options.video ? "tpl-video-card" : "tpl-track-card");
  card.dataset.trackId = track.id;
  card.dataset.source = sourceKey;
  card.dataset.action = options.video ? "playvideo" : "play";
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  const art = card.querySelector<HTMLImageElement>('[data-el="art"]');
  const fallback = card.querySelector<HTMLElement>('[data-el="fallback"]');
  setArt(art, fallback, options.video ? track.poster || track.thumb : track.thumb, track.title);

  const title = card.querySelector<HTMLElement>('[data-el="title"]');
  if (title) title.textContent = track.title;
  const artist = card.querySelector<HTMLElement>('[data-el="artist"]');
  if (artist) {
    artist.textContent = track.artist;
    artist.dataset.action = "artist";
    artist.dataset.artistId = track.artist_id;
  }
  const lang = card.querySelector<HTMLElement>('[data-el="lang"]');
  if (lang) lang.textContent = track.language || "—";
  const duration = card.querySelector<HTMLElement>('[data-el="duration"]');
  if (duration && track.duration) {
    duration.hidden = false;
    duration.textContent = durationLabel(track);
  }
  const tag = card.querySelector<HTMLElement>('[data-el="tag"]');
  if (tag && options.tag) {
    tag.hidden = false;
    tag.textContent = options.tag;
  } else if (tag && track.synced_lyrics && !options.video) {
    tag.hidden = false;
    tag.textContent = text("sincronizada", "synced");
  }
  if (player.current?.id === track.id) card.classList.add("is-playing");
  return card;
}

export function artistCard(artist: Artist): HTMLElement {
  const card = cloneTemplate("tpl-artist-card");
  card.dataset.artistId = artist.id;
  card.dataset.action = "open-artist";
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  const play = card.querySelector<HTMLElement>('[data-action="artist"]');
  if (play) play.dataset.action = "playartist";
  const art = card.querySelector<HTMLImageElement>('[data-el="art"]');
  setArt(art, card.querySelector('[data-el="fallback"]'), artist.cover, artist.name);
  const title = card.querySelector<HTMLElement>('[data-el="title"]');
  if (title) title.textContent = artist.name;
  const meta = card.querySelector<HTMLElement>('[data-el="meta"]');
  if (meta) meta.textContent = `Artist · ${artist.count} ${artist.count === 1 ? "track" : "tracks"}`;
  return card;
}

export function playlistCard(playlist: Playlist): HTMLElement {
  playlistsById.set(playlist.id, playlist);
  const card = cloneTemplate("tpl-playlist-card");
  card.dataset.playlistId = playlist.id;
  card.dataset.action = "open-playlist";
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  const mosaic = card.querySelector<HTMLElement>('[data-el="mosaic"]');
  const fallback = card.querySelector<HTMLElement>('[data-el="fallback"]');
  if (mosaic) {
    const covers = (playlist.covers || []).filter(Boolean).slice(0, 4);
    mosaic.dataset.count = String(covers.length);
    if (!covers.length) mosaic.hidden = true;
    else {
      if (fallback) fallback.style.display = "none";
      covers.forEach((url) => {
        const img = document.createElement("img");
        img.alt = "";
        img.loading = "lazy";
        img.decoding = "async";
        img.src = url;
        img.onerror = () => img.remove();
        mosaic.appendChild(img);
      });
    }
  }
  const title = card.querySelector<HTMLElement>('[data-el="title"]');
  if (title) title.textContent = playlist.title;
  const meta = card.querySelector<HTMLElement>('[data-el="meta"]');
  if (meta) meta.textContent = playlist.subtitle || `${playlist.count} tracks`;
  const tag = card.querySelector<HTMLElement>('[data-el="tag"]');
  if (tag && playlist.tag) {
    tag.hidden = false;
    tag.textContent = playlist.tag;
  }
  return card;
}

export function trackRow(
  track: Track,
  index: number,
  sourceKey: string,
  options: { showThumb?: boolean } = {},
): HTMLElement {
  const row = cloneTemplate("tpl-track-row");
  row.dataset.trackId = track.id;
  row.dataset.source = sourceKey;
  row.dataset.index = String(index);
  row.querySelector(".track-index")?.setAttribute("aria-label", `${text("Reproducir", "Play")} ${track.title}`);
  if (player.state.current?.id === track.id) row.classList.add("is-playing");
  if (!player.state.playing) row.classList.add("is-paused");

  const num = row.querySelector<HTMLElement>('[data-el="index"]');
  if (num) num.textContent = String(index + 1).padStart(2, "0");
  const art = row.querySelector<HTMLImageElement>('[data-el="art"]');
  if (art && options.showThumb !== false) {
    art.hidden = false;
    art.src = track.thumb;
    art.onerror = () => (art.hidden = true);
  } else if (art) {
    art.closest(".track-thumb")?.remove();
  }
  const title = row.querySelector<HTMLElement>('[data-el="title"]');
  if (title) title.textContent = track.title;
  const artist = row.querySelector<HTMLElement>('[data-el="artist"]');
  if (artist) {
    artist.textContent = track.artist;
    artist.dataset.artistId = track.artist_id;
    (artist as HTMLAnchorElement).href = artistHref(track.artist_id);
  }
  const src = row.querySelector<HTMLElement>('[data-el="src"]');
  if (src) {
    src.textContent = track.synced_lyrics ? text("Letra sincronizada", "Synced lyrics") : text("Letra", "Lyrics");
  }
  const lang = row.querySelector<HTMLElement>('[data-el="lang"]');
  if (lang) lang.textContent = track.language || "—";
  const duration = row.querySelector<HTMLElement>('[data-el="duration"]');
  if (duration) duration.textContent = durationLabel(track);
  const like = row.querySelector<HTMLButtonElement>('[data-action="like"]');
  if (like && player.isLiked(track.id)) {
    like.classList.add("is-liked");
    like.setAttribute("aria-pressed", "true");
  }
  return row;
}

// ---------------------------------------------------------------------------
// Shared blocks
// ---------------------------------------------------------------------------

function trackTable(tracks: Track[], sourceKey: string, queueTracks: Track[] = tracks): HTMLElement {
  registerSource(sourceKey, queueTracks);
  const wrap = document.createElement("div");
  wrap.className = "track-table";
  wrap.innerHTML = `
    <div class="track-head">
      <span>#</span>
      <span>${text("Título", "Title")}</span>
      <span class="col-lang">${text("Idioma", "Language")}</span>
      <span class="col-duration" style="text-align:right">${text("Duración", "Time")}</span>
      <span class="col-actions"></span>
    </div>`;
  const fragment = document.createDocumentFragment();
  tracks.forEach((track, index) => fragment.appendChild(trackRow(track, index, sourceKey)));
  wrap.appendChild(fragment);
  return wrap;
}

function sectionHead(title: string, subtitle: string, seeAll?: { label: string; href: string }) {
  const head = document.createElement("div");
  head.className = "shelf-head";
  head.innerHTML = `
    <div>
      <div class="shelf-title"><h2>${escapeHtml(title)}</h2></div>
      <div class="shelf-sub">${escapeHtml(subtitle)}</div>
    </div>
    <div class="shelf-tools">
      ${seeAll ? `<a class="shelf-link" href="${seeAll.href}">${escapeHtml(seeAll.label)}</a>` : ""}
      <button class="shelf-arrow" data-scroll="prev" aria-label="${text("Desplazar a la izquierda", "Scroll left")}">${iconMarkup("chevron-left", "", 15)}</button>
      <button class="shelf-arrow" data-scroll="next" aria-label="${text("Desplazar a la derecha", "Scroll right")}">${iconMarkup("chevron-right", "", 15)}</button>
    </div>`;
  return head;
}

function shelfRow(items: HTMLElement[], grid = false): HTMLElement {
  const row = document.createElement("div");
  row.className = `shelf-row${grid ? " is-grid" : ""}`;
  items.forEach((item) => row.appendChild(item));
  return row;
}

function wireShelfArrows(section: HTMLElement): void {
  const row = section.querySelector<HTMLElement>(".shelf-row");
  if (!row) return;
  const prev = section.querySelector<HTMLButtonElement>('[data-scroll="prev"]');
  const next = section.querySelector<HTMLButtonElement>('[data-scroll="next"]');
  const update = () => {
    if (!prev || !next) return;
    prev.disabled = row.scrollLeft <= 4;
    next.disabled = row.scrollLeft + row.clientWidth >= row.scrollWidth - 4;
  };
  prev?.addEventListener("click", () => row.scrollBy({ left: -row.clientWidth * 0.82, behavior: "smooth" }));
  next?.addEventListener("click", () => row.scrollBy({ left: row.clientWidth * 0.82, behavior: "smooth" }));
  row.addEventListener("scroll", update, { passive: true });
  window.setTimeout(update, 60);
}

function renderShelf(shelf: Shelf): HTMLElement {
  const section = document.createElement("section");
  section.className = "shelf";
  const seeAll =
    shelf.kind === "tracks"
      ? { label: "See all", href: "#/library" }
      : shelf.kind === "artists"
        ? { label: "See all", href: "#/library/artists" }
        : shelf.kind === "playlists"
          ? { label: "See all", href: "#/library/playlists" }
          : { label: "See all", href: "#/videos" };
  section.appendChild(sectionHead(shelf.title, shelf.subtitle, seeAll));

  let items: HTMLElement[] = [];
  if (shelf.kind === "tracks" || shelf.kind === "videos") {
    const tracks = shelf.items as Track[];
    const sourceKey = `shelf:${shelf.id}`;
    registerSource(sourceKey, tracks);
    items = tracks.map((track) =>
      trackCard(track, sourceKey, { video: shelf.kind === "videos", tag: shelf.kind === "videos" ? "MV" : undefined }),
    );
  } else if (shelf.kind === "artists") {
    items = (shelf.items as Artist[]).map((artist) => artistCard(artist));
  } else {
    items = (shelf.items as Playlist[]).map((playlist) => playlistCard(playlist));
  }
  section.appendChild(shelfRow(items));
  wireShelfArrows(section);
  return section;
}

function emptyState(title: string, message: string, icon = "music"): HTMLElement {
  const el = document.createElement("div");
  el.className = "empty-state";
  el.innerHTML = `
    <span class="glyph">${iconMarkup(icon, "", 24)}</span>
    <h3>${escapeHtml(title)}</h3>
    <p>${escapeHtml(message)}</p>`;
  return el;
}

function errorState(message: string): HTMLElement {
  const el = document.createElement("div");
  el.className = "error-state";
  el.innerHTML = `
    <span class="glyph">${iconMarkup("wave", "", 24)}</span>
    <h3>The API did not answer</h3>
    <p>${escapeHtml(message)}</p>
    <button class="btn btn-ghost btn-sm" data-retry>${text("Reintentar", "Try again")}</button>`;
  el.querySelector("[data-retry]")?.addEventListener("click", () => renderRoute(currentRoute()));
  return el;
}

function skeletonView(target: HTMLElement) {
  target.innerHTML = `
    <div class="page-head"><div>
      <div class="skeleton" style="width:220px;height:38px;border-radius:10px"></div>
      <div class="skeleton" style="width:320px;height:12px;margin-top:12px"></div>
    </div></div>
    <div class="shelf"><div class="shelf-head"><div class="skeleton" style="width:200px;height:22px"></div></div>
    <div class="shelf-row">${Array.from({ length: 8 })
      .map(() => `<div class="skeleton-card"><div class="art skeleton"></div><div class="line skeleton"></div><div class="line short skeleton"></div></div>`)
      .join("")}</div></div>`;
}

// ---------------------------------------------------------------------------
// Home
// ---------------------------------------------------------------------------

function showCourseLanding(root: HTMLElement): void {
  root.replaceChildren(courseLanding((query) => navigate(`/search/${encodeURIComponent(query)}`)));
}

/** A "because you listened" shelf built purely from browser-owned seeds. */
async function historyShelf(token: number): Promise<HTMLElement | null> {
  const recent = seeds(3);
  if (!recent.length) return null;
  try {
    const payload = await api.radio(recent[0], 18, recent);
    if (token !== renderToken || !payload.recommendations.length) return null;
    return renderShelf({
      id: "history-radio",
      title: "Because you listened",
      subtitle: "Seeded by your browser history",
      kind: "tracks",
      items: payload.recommendations,
    });
  } catch {
    return null;
  }
}

async function renderHome(root: HTMLElement, token: number): Promise<void> {
  skeletonView(root);
  let data: Bootstrap;
  try {
    data = await getBootstrap();
  } catch (error) {
    if (token === renderToken) root.replaceChildren(errorState(String((error as Error).message || error)));
    return;
  }
  if (token !== renderToken) return;

  const fragment = document.createDocumentFragment();
  const pageHead = document.createElement("div");
  pageHead.className = "page-head";
  pageHead.innerHTML = `
    <div>
      <h1>${greeting()}.</h1>
      <p>${fmtCount(data.library.songs)} songs, ${fmtCount(data.library.artists)} artists and ${fmtCount(
        data.library.tokens,
      )} lyric tokens, ready to play.</p>
    </div>
    <div class="page-actions">
      <button class="icon-btn round" data-refresh aria-label="${text("Actualizar catálogo", "Refresh the index")}" data-tip="${text("Actualizar catálogo", "Refresh index")}">${iconMarkup(
        "refresh",
        "",
        16,
      )}</button>
      <button class="btn btn-ghost btn-sm" data-home-shuffle>${iconMarkup("shuffle", "", 15)} ${text("Mezclar biblioteca", "Shuffle library")}</button>
    </div>`;
  pageHead.querySelector("[data-refresh]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget as HTMLButtonElement;
    button.disabled = true;
    button.classList.add("is-loading");
    resetBootstrap();
    try {
      await getBootstrap(true);
      emit("toast", "Library refreshed");
      await renderRoute(currentRoute());
    } catch (error) {
      emit("error", String((error as Error).message || error));
      button.disabled = false;
      button.classList.remove("is-loading");
    }
  });
  fragment.appendChild(pageHead);

  const personal = await historyShelf(token);
  if (token !== renderToken) return;

  if (data.hero) {
    const hero = document.createElement("section");
    hero.className = "hero";
    hero.dataset.trackId = data.hero.id;
    hero.innerHTML = `
      <div class="hero-art">
        <img data-el="art" alt="${escapeHtml(data.hero.title)}" />
        <div class="art-fallback">${iconMarkup("music", "", 60)}</div>
      </div>
      <div class="hero-body">

        <h1 class="hero-title">${escapeHtml(data.hero.title)}</h1>
        <a class="hero-artist" href="${artistHref(data.hero.artist_id)}">${escapeHtml(data.hero.artist)}</a>
        <div class="hero-blurb">
          <span>${escapeHtml(data.hero.language_name || "Unknown")}</span>
          <span class="sep"></span>
          <span>${data.hero.synced_lyrics ? "Synced lyrics" : "Lyrics indexed"}</span>
          <span class="sep"></span>
          <span>${escapeHtml(data.hero.blurb || "")}</span>
        </div>
        <div class="hero-actions">
          <button class="btn btn-primary" data-hero-play>${iconMarkup("play", "", 17)} ${text("Reproducir", "Play")}</button>
          <button class="btn btn-outline" data-hero-radio>${iconMarkup("radio", "", 16)} ${text("Iniciar radio", "Start radio")}</button>
        </div>
        <div class="hero-stats">
          <div class="hero-stat"><b>${fmtCount(data.library.songs)}</b><span>${text("Canciones", "Songs")}</span></div>
          <div class="hero-stat"><b>${fmtCount(data.library.artists)}</b><span>${text("Artistas", "Artists")}</span></div>
          <div class="hero-stat"><b>${fmtCount(data.library.terms)}</b><span>Terms</span></div>
          <div class="hero-stat"><b>${fmtCount(data.library.synced)}</b><span>Synced</span></div>
        </div>
      </div>`;
    const heroArt = hero.querySelector<HTMLImageElement>('[data-el="art"]');
    setArt(
      heroArt,
      hero.querySelector(".art-fallback"),
      data.hero.thumb,
      data.hero.title,
      data.hero.art,
    );

    const heroQueue = registerSource(
      "home:hero",
      [data.hero, ...(data.top_tracks || []).filter((track) => track.id !== data.hero!.id)].slice(0, 40),
    );
    hero.querySelector("[data-hero-play]")?.addEventListener("click", () => {
      player.playTrack(data.hero!, sources.get(heroQueue));
    });
    hero.querySelector("[data-hero-radio]")?.addEventListener("click", async () => {
      await player.playTrack(data.hero!, [data.hero!]);
      await player.appendAutomix();
      emit("queue-open", true);
    });
    hero.querySelector<HTMLAnchorElement>(".hero-artist")?.addEventListener("click", (event) => {
      event.preventDefault();
      navigate(`/artist/${data.hero!.artist_id}`);
    });
    fragment.appendChild(hero);
  }

  if (data.languages.length) {
    const chips = document.createElement("div");
    chips.className = "chips";
    const all = document.createElement("a");
    all.className = "chip is-active";
    all.href = "#/library";
    all.textContent = text("Todo", "All");
    chips.appendChild(all);
    data.languages
      .filter((language) => language.code !== "unknown")
      .forEach((language) => {
        const chip = document.createElement("a");
        chip.className = "chip";
        chip.href = playlistHref(`lang-${language.code}`);
        chip.innerHTML = `${escapeHtml(language.name)} <span class="count">${language.count}</span>`;
        chips.appendChild(chip);
      });
    const videos = document.createElement("a");
    videos.className = "chip";
    videos.href = "#/videos";
    videos.innerHTML = `${iconMarkup("video", "", 13)} Music videos`;
    chips.appendChild(videos);
    fragment.appendChild(chips);
  }

  if (personal) fragment.appendChild(personal);

  data.shelves.forEach((shelf) => {
    if (shelf.items.length) fragment.appendChild(renderShelf(shelf));
  });

  // The full library, as a table, below the shelves.
  if (data.top_tracks.length) {
    const section = document.createElement("section");
    section.className = "shelf";
    const head = document.createElement("div");
    head.className = "shelf-head";
    head.innerHTML = `
      <div>
        <div class="shelf-title"><h2>${text("Todas las canciones", "Everything in the index")}</h2></div>
        <div class="shelf-sub">${fmtCount(data.library.songs)} tracks · sorted by how central they are to the lyric graph</div>
      </div>
      <div class="shelf-tools"><a class="shelf-link" href="#/library">Open library ${iconMarkup("chevron-right", "", 13)}</a></div>`;
    section.appendChild(head);
    section.appendChild(trackTable(data.top_tracks.slice(0, 30), "home:top"));
    const more = document.createElement("a");
    more.className = "btn btn-ghost btn-sm";
    more.href = "#/library";
    more.style.marginTop = "14px";
    more.innerHTML = `Browse all ${fmtCount(data.library.songs)} songs ${iconMarkup("chevron-right", "", 14)}`;
    section.appendChild(more);
    fragment.appendChild(section);
  }

  root.replaceChildren(fragment);

  root.querySelector("[data-home-shuffle]")?.addEventListener("click", () => {
    const pool = data.top_tracks.length ? data.top_tracks : [];
    if (!pool.length) return;
    const queue = [...pool].sort(() => Math.random() - 0.5);
    player.playTrack(queue[0], queue);
  });
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

async function renderSearch(root: HTMLElement, token: number, query: string): Promise<void> {
  if (!query.trim()) {
    showCourseLanding(root);
    const content = root.querySelector<HTMLElement>("#course-catalogue-content")!;
    try {
      const data = await getBootstrap(true);
      if (token !== renderToken) return;
      content.removeAttribute("role");
      if (data.top_tracks.length) {
        content.replaceChildren(trackTable(data.top_tracks.slice(0, 8), "course:catalogue", data.top_tracks));
      } else content.textContent = text("Todavía no hay canciones. Agrega una playlist para empezar.", "There are no songs yet. Add a playlist to get started.");
    } catch {
      if (token === renderToken) content.textContent = text("No se pudo cargar el catálogo. Recarga la página.", "Could not load the catalogue. Reload the page.");
    }
    return;
  }

  const status = document.createElement("p");
  status.className = "course-status";
  status.setAttribute("role", "status");
  status.textContent = text("Buscando en las letras…", "Searching lyrics…");
  root.replaceChildren(status);

  try {
    const payload = await api.courseSearch(query);
    if (token !== renderToken) return;
    recordSearch(query);
    const focusHeading = document.activeElement === document.body;
    const results = courseResults(payload, (track, index, queue, key) =>
      trackRow(track, index, registerSource(key, queue)),
    );
    root.replaceChildren(results);
    if (focusHeading) {
      const heading = results.querySelector("h1");
      if (heading) {
        heading.tabIndex = -1;
        heading.focus({ preventScroll: true });
      }
    }
  } catch {
    if (token !== renderToken) return;
    status.setAttribute("role", "alert");
    status.textContent = text("El buscador no respondió. Intenta de nuevo en unos segundos.", "Search is unavailable. Try again in a few seconds.");
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "course-retry";
    retry.textContent = text("Reintentar", "Try again");
    retry.addEventListener("click", () => void renderSearch(root, token, query), { once: true });
    status.append(" ", retry);
  }
}

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------

function renderImport(root: HTMLElement, token: number): void {
  const section = document.createElement("section");
  section.className = "import-view";
  section.innerHTML = `<div class="page-head"><div>
    <h1>${text("Agregar canciones", "Add songs")}</h1>
    <p>${text("Importa una lista pública o no listada de YouTube o YouTube Music.", "Import a public or unlisted playlist from YouTube or YouTube Music.")}</p>
    </div></div>
    <form class="import-form">
      <label for="playlist-url">${text("Enlace de la playlist", "Playlist link")}</label>
      <div class="course-form"><input id="playlist-url" type="url" required placeholder="https://music.youtube.com/playlist?list=…" />
      <button class="btn btn-primary" type="submit">${iconMarkup("plus", "", 18)} ${text("Importar", "Import")}</button></div>
      <p class="muted">${text("Las letras se recuperan e indexan antes de que las canciones aparezcan en la biblioteca. Las listas privadas de Me gusta no se pueden importar directamente.", "Lyrics are retrieved and indexed before tracks appear in your library. Private Liked Songs playlists cannot be imported directly.")}</p>
    </form>
    <section class="import-progress" hidden><h2>${text("Importación", "Import progress")}</h2><p role="status" id="import-status"></p>
      <button class="btn btn-outline" type="button" id="import-check" hidden>${text("Revisar estado", "Check status")}</button>
    </section>
    <a class="btn btn-outline" href="#/library">${text("Ver biblioteca", "View library")}</a>`;
  root.replaceChildren(section);
  const form = section.querySelector<HTMLFormElement>("form")!;
  const input = form.querySelector<HTMLInputElement>("input")!;
  const submit = form.querySelector<HTMLButtonElement>("button")!;
  const progress = section.querySelector<HTMLElement>(".import-progress")!;
  const status = section.querySelector<HTMLElement>("#import-status")!;
  const check = section.querySelector<HTMLButtonElement>("#import-check")!;
  let jobId = sessionStorage.getItem("upspotify-import-job") || "";
  const stages: Record<string, string> = {
    queued: text("En cola, esperando su turno.", "Queued, waiting to start."),
    indexing: text("Recuperando letras e indexando canciones.", "Retrieving lyrics and indexing tracks."),
    matrix_pending: text("Calculando el índice y las matrices.", "Building the index and matrices."),
    retry_wait: text("Esperando antes de reintentar.", "Waiting before retrying."),
  };
  function show(message: string): void {
    progress.hidden = false;
    status.textContent = message;
  }
  async function poll(): Promise<void> {
    if (token !== renderToken || !jobId) return;
    check.hidden = true;
    submit.disabled = true;
    try {
      const job = await api.importStatus(jobId);
      if (token !== renderToken) return;
      if (job.status === "committed") {
        show(text(`Importación terminada. ${job.added ?? 0} canciones añadidas al catálogo.`, `Import complete. ${job.added ?? 0} songs added to the catalogue.`));
        sessionStorage.removeItem("upspotify-import-job");
        jobId = "";
        submit.disabled = false;
        void getBootstrap(true).catch(() => {});
      } else if (job.status === "error" || job.status === "skipped") {
        show(text("No se pudo completar la importación. Comprueba que la lista sea accesible y vuelve a intentarlo.", "Import could not finish. Check that the playlist is accessible and try again.") + (job.error ? ` (${job.error})` : ""));
        sessionStorage.removeItem("upspotify-import-job");
        jobId = "";
        submit.disabled = false;
      } else {
        show(stages[job.status] || text("Procesando la lista…", "Processing playlist…"));
        window.setTimeout(() => void poll(), 4000);
      }
    } catch {
      if (token !== renderToken) return;
      show(text("No se pudo consultar el estado de la importación.", "Couldn't check import progress."));
      check.hidden = false;
      submit.disabled = false;
    }
  }
  check.addEventListener("click", () => void poll());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!input.value.trim()) return;
    submit.disabled = true;
    check.hidden = true;
    show(text("Añadiendo la playlist a la cola…", "Adding the playlist to the queue…"));
    try {
      const result = await api.importPlaylist(input.value.trim());
      jobId = result.job_id;
      sessionStorage.setItem("upspotify-import-job", jobId);
      if (token === renderToken) void poll();
    } catch {
      if (token !== renderToken) return;
      show(text("No se pudo importar. Verifica el enlace y que la playlist sea pública o no listada.", "Could not import. Verify the link and that the playlist is public or unlisted."));
      submit.disabled = false;
    }
  });
  if (jobId) {
    show(text("Consultando la importación…", "Checking import progress…"));
    void poll();
  }
}

type LibraryTab = "tracks" | "artists" | "playlists" | "videos";

async function renderLibrary(root: HTMLElement, token: number, tab: LibraryTab): Promise<void> {
  skeletonView(root);
  const data = await getBootstrap(true).catch(() => null);
  if (!data || token !== renderToken) {
    if (token === renderToken) root.replaceChildren(errorState(text("No se pudo cargar la biblioteca.", "The library could not be loaded.")));
    return;
  }

  const wrap = document.createElement("div");
  wrap.innerHTML = `
    <div class="page-head">
      <div><h1>${text("Biblioteca", "Everything indexed")}</h1>
      <p>${fmtCount(data.library.songs)} ${text("canciones", "songs")} · ${fmtCount(data.library.artists)} ${text("artistas", "artists")} · ${fmtCount(data.library.synced)} ${text("con letra sincronizada", "with synced lyrics")}</p></div>
    </div>
    <div class="library-toolbar">
      <button class="chip ${tab === "tracks" ? "is-active" : ""}" aria-pressed="${tab === "tracks"}" data-library-tab="tracks">${iconMarkup("music", "", 14)} ${text("Canciones", "Tracks")}</button>
      <button class="chip ${tab === "artists" ? "is-active" : ""}" aria-pressed="${tab === "artists"}" data-library-tab="artists">${iconMarkup("headphones", "", 14)} ${text("Artistas", "Artists")}</button>
      <button class="chip ${tab === "playlists" ? "is-active" : ""}" aria-pressed="${tab === "playlists"}" data-library-tab="playlists">${iconMarkup("list", "", 14)} ${text("Listas", "Playlists")}</button>
      <button class="chip ${tab === "videos" ? "is-active" : ""}" aria-pressed="${tab === "videos"}" data-library-tab="videos">${iconMarkup("video", "", 14)} ${text("Videos", "Videos")}</button>
      <span class="spacer"></span>
      <span class="select-wrap" id="lib-controls"></span>
    </div>
    <div id="library-body"></div>`;
  wrap.querySelectorAll<HTMLElement>("[data-library-tab]").forEach((button) => {
    button.addEventListener("click", () => navigate(`/library/${button.dataset.libraryTab}`));
  });
  root.replaceChildren(wrap);
  const body = wrap.querySelector<HTMLElement>("#library-body")!;
  const controls = wrap.querySelector<HTMLElement>("#lib-controls")!;

  if (tab === "tracks") {
    const all: Track[] = [];
    try {
      let offset = 0;
      let total = Infinity;
      while (offset < total && offset < 5000) {
        const page = await api.tracks(offset, 300);
        if (token !== renderToken) return;
        total = page.total;
        if (!page.tracks.length) break;
        all.push(...page.tracks);
        offset += page.tracks.length;
      }
    } catch (error) {
      body.replaceChildren(errorState(String((error as Error).message || error)));
      return;
    }
    if (token !== renderToken) return;
    if (!all.length) {
      body.innerHTML = `<p class="course-status">${text("No hay canciones en el catálogo. Agrega una playlist para comenzar.", "The catalogue is empty. Add a playlist to get started.")}</p><a class="btn btn-primary" href="#/import">${text("Agregar canciones", "Add songs")}</a>`;
      return;
    }
    const languages = [...new Set(all.map((track) => track.language).filter(Boolean))];
    let language = "";
    let filter = "";
    let sort: "artist" | "title" | "duration" = "artist";
    let shown = 150;

    controls.innerHTML = `
      <label class="sr-only" for="lib-filter">${text("Filtrar por título o artista", "Filter by title or artist")}</label>
      <input class="select" id="lib-filter" type="search" placeholder="${text("Título o artista", "Title or artist")}" />
      <select class="select" aria-label="${text("Filtrar por idioma", "Filter by language")}" id="lib-language">
        <option value="">${text("Todos los idiomas", "All languages")}</option>
        ${languages.map((code) => `<option value="${code}">${escapeHtml(code.toUpperCase())}</option>`).join("")}
      </select>
      <span style="width:8px"></span>
      <select class="select" aria-label="${text("Ordenar canciones", "Sort tracks")}" id="lib-sort">
        <option value="artist">${text("Artista A–Z", "Artist A–Z")}</option>
        <option value="title">${text("Título A–Z", "Title A–Z")}</option>
        <option value="duration">${text("Mayor duración", "Longest first")}</option>
      </select>`;
    const languageSelect = controls.querySelector<HTMLSelectElement>("#lib-language")!;
    const sortSelect = controls.querySelector<HTMLSelectElement>("#lib-sort")!;
    const filterInput = controls.querySelector<HTMLInputElement>("#lib-filter")!;
    const summary = document.createElement("div");
    summary.className = "shelf-sub";
    summary.style.margin = "4px 2px 10px";

    const paint = () => {
      let list = language ? all.filter((track) => track.language === language) : [...all];
      if (filter) {
        const folded = (value: string) => value.normalize("NFD").replace(/\p{M}/gu, "").toLocaleLowerCase();
        list = list.filter((track) => folded(`${track.title} ${track.artist}`).includes(folded(filter)));
      }
      if (sort === "title") list.sort((a, b) => a.title.localeCompare(b.title));
      else if (sort === "duration") list.sort((a, b) => (b.duration || 0) - (a.duration || 0));
      else list.sort((a, b) => a.artist.localeCompare(b.artist) || a.title.localeCompare(b.title));
      summary.textContent = `${list.length} ${text("canciones", "tracks")} · ${fmtDuration(
        list.reduce((sum, track) => sum + (track.duration || 0), 0),
      )}`;
      const holder = document.createElement("div");
      holder.appendChild(summary);
      if (list.length) holder.appendChild(trackTable(list.slice(0, shown), "library:tracks", list));
      else holder.append(text("No hay canciones con este filtro.", "No songs match this filter."));
      if (shown < list.length) {
        const more = document.createElement("button");
        more.className = "btn btn-ghost btn-sm";
        more.style.marginTop = "16px";
        more.textContent = text(`Ver ${Math.min(150, list.length - shown)} más`, `Show ${Math.min(150, list.length - shown)} more`);
        more.addEventListener("click", () => {
          shown += 150;
          paint();
        });
        holder.appendChild(more);
      }
      body.replaceChildren(holder);
    };
    languageSelect.addEventListener("change", () => {
      language = languageSelect.value;
      shown = 150;
      paint();
    });
    filterInput.addEventListener("input", () => {
      filter = filterInput.value.trim();
      shown = 150;
      paint();
    });
    sortSelect.addEventListener("change", () => {
      sort = sortSelect.value as typeof sort;
      shown = 150;
      paint();
    });
    paint();
    return;
  }

  if (tab === "artists") {
    let artists = data.artists;
    try {
      const payload = await api.artists();
      if (token !== renderToken) return;
      if (payload.artists.length) artists = payload.artists;
    } catch {
      /* fall back to the bootstrap subset */
    }
    let shown = 120;
    const paint = () => {
      controls.innerHTML = `<span class="chip small">${iconMarkup("headphones", "", 12)} ${artists.length} artists</span>`;
      const grid = document.createElement("div");
      grid.className = "grid-cards";
      artists.slice(0, shown).forEach((artist) => grid.appendChild(artistCard(artist)));
      const holder = document.createElement("div");
      holder.appendChild(grid);
      if (shown < artists.length) {
        const more = document.createElement("button");
        more.className = "btn btn-ghost btn-sm";
        more.style.marginTop = "16px";
        more.textContent = `Load ${Math.min(120, artists.length - shown)} more of ${artists.length}`;
        more.addEventListener("click", () => {
          shown += 120;
          paint();
        });
        holder.appendChild(more);
      }
      body.replaceChildren(holder);
    };
    paint();
    return;
  }

  if (tab === "playlists") {
    controls.innerHTML = `<span class="chip small">${iconMarkup("list", "", 12)} ${data.playlists.length} playlists</span>`;
    const grid = document.createElement("div");
    grid.className = "grid-cards";
    data.playlists.forEach((playlist) => grid.appendChild(playlistCard(playlist)));
    body.replaceChildren(grid);
    return;
  }

  try {
    let offset = 0;
    let total = 0;
    const videos: Track[] = [];
    const sourceKey = "library:videos";
    const paintVideos = () => {
      registerSource(sourceKey, videos);
      controls.innerHTML = `<span class="chip small">${iconMarkup("video", "", 12)} ${total || videos.length} videos · showing ${videos.length}</span>`;
      const holder = document.createElement("div");
      const grid = document.createElement("div");
      grid.className = "grid-cards";
      videos.forEach((video) => grid.appendChild(trackCard(video, sourceKey, { video: true })));
      holder.appendChild(grid);
      if (videos.length < total) {
        const more = document.createElement("button");
        more.className = "btn btn-ghost btn-sm";
        more.style.marginTop = "16px";
        more.textContent = `Load ${Math.min(120, total - videos.length)} more of ${total}`;
        more.addEventListener("click", async () => {
          more.disabled = true;
          try {
            const page = await api.videos(videos.length, 120);
            videos.push(...page.videos);
            total = page.total;
            paintVideos();
          } catch (error) {
            more.disabled = false;
            emit("error", String((error as Error).message || error));
          }
        });
        holder.appendChild(more);
      }
      body.replaceChildren(holder);
    };
    const page = await api.videos(0, 120);
    if (token !== renderToken) return;
    total = page.total;
    videos.push(...page.videos);
    paintVideos();
  } catch (error) {
    body.replaceChildren(errorState(String((error as Error).message || error)));
  }
}

// ---------------------------------------------------------------------------
// Artist
// ---------------------------------------------------------------------------

async function renderArtist(root: HTMLElement, token: number, artistId: string): Promise<void> {
  skeletonView(root);
  let data;
  try {
    data = await api.artist(artistId);
  } catch (error) {
    if (token === renderToken) root.replaceChildren(errorState(String((error as Error).message || error)));
    return;
  }
  if (token !== renderToken) return;
  const { artist, tracks, similar } = data;
  artistsById.set(artist.id, artist);
  const sourceKey = registerSource(`artist:${artist.id}`, tracks);

  const wrap = document.createElement("div");
  wrap.className = "collection";
  wrap.innerHTML = `
    <div class="collection-hero">
      <div class="collection-backdrop"></div>
      <div class="collection-art is-round">
        <img data-el="art" alt="${escapeHtml(artist.name)}" />
      </div>
      <div class="collection-body">
        <div class="collection-kicker">Artist</div>
        <h1 class="collection-title is-round">${escapeHtml(artist.name)}</h1>
        <div class="collection-desc">${artist.count} indexed ${artist.count === 1 ? "track" : "tracks"} · ${escapeHtml(
          artist.language_name || "",
        )} · lyrics similarity graph</div>
        <div class="collection-meta">
          <b>${fmtCount(artist.count)}</b> songs
          <span class="dot"></span>
          <span>${fmtDuration(tracks.reduce((sum, track) => sum + (track.duration || 0), 0))}</span>
          <span class="dot"></span>
          <span>${tracks.filter((track) => track.synced_lyrics).length} synced</span>
        </div>
        <div class="collection-actions">
          <button class="btn btn-primary" data-play-artist>${iconMarkup("play", "", 17)} ${text("Reproducir", "Play")}</button>
          <button class="btn btn-ghost" data-shuffle-artist>${iconMarkup("shuffle", "", 16)} ${text("Aleatorio", "Shuffle")}</button>
          <button class="btn btn-outline" data-radio-artist>${iconMarkup("radio", "", 15)} ${text("Radio", "Radio")}</button>
        </div>
      </div>
    </div>`;
  setArt(wrap.querySelector("img"), null, artist.art || artist.cover, artist.name, artist.cover);
  wrap.querySelector("[data-play-artist]")?.addEventListener("click", () => {
    if (tracks[0]) player.playTrack(tracks[0], tracks);
  });
  wrap.querySelector("[data-shuffle-artist]")?.addEventListener("click", () => {
    const queue = [...tracks].sort(() => Math.random() - 0.5);
    if (queue[0]) player.playTrack(queue[0], queue);
  });
  wrap.querySelector("[data-radio-artist]")?.addEventListener("click", async () => {
    if (!tracks[0]) return;
    await player.playTrack(tracks[0], [tracks[0]]);
    await player.appendAutomix();
    emit("queue-open", true);
  });

  const trackSection = document.createElement("section");
  trackSection.className = "shelf";
  trackSection.innerHTML = `<div class="shelf-head"><div><div class="shelf-title"><h2>${text("Canciones destacadas", "Popular tracks")}</h2></div>
    <div class="shelf-sub">Ordered by centrality in the lyric similarity model</div></div></div>`;
  trackSection.appendChild(trackTable(tracks, sourceKey));
  wrap.appendChild(trackSection);

  if (similar.length) {
    const section = document.createElement("section");
    section.className = "shelf";
    section.appendChild(sectionHead("Fans also like", "Artists connected through the lyric graph"));
    section.appendChild(shelfRow(similar.map((item) => artistCard(item))));
    wireShelfArrows(section);
    wrap.appendChild(section);
  }
  root.replaceChildren(wrap);
}

// ---------------------------------------------------------------------------
// Playlist
// ---------------------------------------------------------------------------

async function renderPlaylist(root: HTMLElement, token: number, playlistId: string): Promise<void> {
  skeletonView(root);
  let data;
  try {
    data = await api.playlist(playlistId, 0, 250);
  } catch (error) {
    if (token === renderToken) root.replaceChildren(errorState(String((error as Error).message || error)));
    return;
  }
  if (token !== renderToken) return;
  const playlist = data.playlist;
  const total = data.total || data.tracks.length;
  const tracks: Track[] = [...data.tracks];
  playlistsById.set(playlist.id, playlist);
  const sourceKey = `playlist:${playlist.id}`;
  registerSource(sourceKey, tracks);

  const loadAllTracks = async (): Promise<Track[]> => {
    if (tracks.length >= total) return tracks;
    const full = await api.playlist(playlistId, 0, 2000);
    return full.tracks;
  };

  const wrap = document.createElement("div");
  wrap.className = "collection";
  const mosaic = document.createElement("div");
  mosaic.className = "collection-art";
  if (playlist.covers?.length >= 4) {
    mosaic.innerHTML = `<div class="mosaic" data-count="${Math.min(playlist.covers.length, 4)}">${playlist.covers
      .slice(0, 4)
      .map((cover) => `<img src="${cover}" alt="" loading="lazy" />`)
      .join("")}</div>`;
  } else {
    mosaic.innerHTML = `<img data-el="art" alt="" />`;
    setArt(mosaic.querySelector("img"), null, playlist.covers?.[0] || playlist.cover, playlist.title);
  }
  wrap.innerHTML = `
    <div class="collection-hero">
      <div class="collection-backdrop"></div>
    </div>`;
  const hero = wrap.querySelector(".collection-hero")!;
  hero.appendChild(mosaic);
  const body = document.createElement("div");
  body.className = "collection-body";
  body.innerHTML = `
    <div class="collection-kicker">${escapeHtml(playlist.tag || "Playlist")}</div>
    <h1 class="collection-title">${escapeHtml(playlist.title)}</h1>
    <div class="collection-desc">${escapeHtml(playlist.subtitle || "")}</div>
    <div class="collection-meta">
      <b>${playlist.count}</b> tracks
      <span class="dot"></span>
      <span>${fmtDuration(playlist.duration)}</span>
      <span class="dot"></span>
      <span>${playlist.synced ?? "—"} synced</span>
    </div>
    <div class="collection-actions">
      <button class="btn btn-primary" data-play-playlist>${iconMarkup("play", "", 17)} ${text("Reproducir", "Play")}</button>
      <button class="btn btn-ghost" data-shuffle-playlist>${iconMarkup("shuffle", "", 16)} ${text("Aleatorio", "Shuffle")}</button>
      <button class="btn btn-outline" data-radio-playlist>${iconMarkup("radio", "", 15)} ${text("Radio", "Radio")}</button>
    </div>`;
  hero.appendChild(body);

  const playAll = async (shuffle = false) => {
    try {
      let queue = await loadAllTracks();
      if (shuffle) queue = [...queue].sort(() => Math.random() - 0.5);
      if (queue[0]) player.playTrack(queue[0], queue);
    } catch (error) {
      emit("error", String((error as Error).message || error));
    }
  };
  wrap.querySelector("[data-play-playlist]")?.addEventListener("click", () => void playAll(false));
  wrap.querySelector("[data-shuffle-playlist]")?.addEventListener("click", () => void playAll(true));
  wrap.querySelector("[data-radio-playlist]")?.addEventListener("click", async () => {
    if (!tracks[0]) return;
    await player.playTrack(tracks[0], [tracks[0]]);
    await player.appendAutomix();
    emit("queue-open", true);
  });

  const section = document.createElement("section");
  section.className = "shelf";
  section.innerHTML = `<div class="shelf-head"><div><div class="shelf-title"><h2>${text("Canciones", "Tracklist")}</h2></div>
    <div class="shelf-sub">${playlist.subtitle || "Built from your indexed library"}</div></div></div>`;
  const tableHolder = document.createElement("div");
  section.appendChild(tableHolder);
  const paint = () => {
    registerSource(sourceKey, tracks);
    tableHolder.replaceChildren(trackTable(tracks, sourceKey, tracks));
    const old = section.querySelector("[data-playlist-more]");
    old?.remove();
    if (tracks.length < total) {
      const more = document.createElement("button");
      more.dataset.playlistMore = "1";
      more.className = "btn btn-ghost btn-sm";
      more.style.marginTop = "16px";
      more.textContent = `Load ${Math.min(250, total - tracks.length)} more of ${total}`;
      more.addEventListener("click", async () => {
        more.disabled = true;
        try {
          const page = await api.playlist(playlistId, tracks.length, 250);
          tracks.push(...page.tracks);
          paint();
        } catch (error) {
          more.disabled = false;
          emit("error", String((error as Error).message || error));
        }
      });
      section.appendChild(more);
    }
  };
  paint();
  wrap.appendChild(section);
  root.replaceChildren(wrap);
}

// ---------------------------------------------------------------------------
// Videos
// ---------------------------------------------------------------------------

async function renderVideos(root: HTMLElement, token: number): Promise<void> {
  skeletonView(root);
  let payload;
  try {
    payload = await api.videos(0, 120);
  } catch (error) {
    if (token === renderToken) root.replaceChildren(errorState(String((error as Error).message || error)));
    return;
  }
  if (token !== renderToken) return;
  const videos: Track[] = [...payload.videos];
  const total = payload.total;
  const sourceKey = "videos";
  const wrap = document.createElement("div");
  wrap.innerHTML = `
    <div class="page-head">
      <div><h1>${text("Videos musicales", "Press play, watch it")}</h1>
      <p>Every indexed track also streams as video. Theater mode keeps the lyrics beside it.</p></div>
    </div>`;
  const grid = document.createElement("div");
  grid.className = "grid-cards";
  const paint = () => {
    registerSource(sourceKey, videos);
    grid.innerHTML = "";
    videos.forEach((video) => grid.appendChild(trackCard(video, sourceKey, { video: true })));
    const old = wrap.querySelector("[data-video-more]");
    old?.remove();
    if (videos.length < total) {
      const more = document.createElement("button");
      more.dataset.videoMore = "1";
      more.className = "btn btn-ghost btn-sm";
      more.style.margin = "16px 2px 0";
      more.textContent = `Load ${Math.min(120, total - videos.length)} more of ${total}`;
      more.addEventListener("click", async () => {
        more.disabled = true;
        try {
          const page = await api.videos(videos.length, 120);
          videos.push(...page.videos);
          paint();
        } catch (error) {
          more.disabled = false;
          emit("error", String((error as Error).message || error));
        }
      });
      wrap.appendChild(more);
    }
  };
  wrap.appendChild(grid);
  paint();
  root.replaceChildren(wrap);
}
// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

let lastRoute: Route = { name: "home" };

export function currentRoute(): Route {
  return lastRoute;
}

export function parseRoute(): Route {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path] = raw.split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  if (!parts.length) return { name: "search" };
  const [head, ...rest] = parts;
  if (head === "discover" || head === "home") return { name: "home" };
  if (head === "import") return { name: "import" };
  if (head === "search") return { name: "search", query: rest.join("/") };
  if (head === "library") {
    const tab = rest[0];
    return { name: "library", param: tab === "artists" || tab === "playlists" || tab === "videos" ? tab : "tracks" };
  }
  if (head === "artist" && rest[0]) return { name: "artist", param: rest[0] };
  if (head === "playlist" && rest[0]) return { name: "playlist", param: rest[0] };
  if (head === "videos") return { name: "videos" };
  return { name: "search" };
}

export async function renderRoute(route: Route = parseRoute()): Promise<void> {
  const root = document.getElementById("view");
  if (!root) return;
  lastRoute = route;
  const token = ++renderToken;
  emit("route", route);
  emit("view:loading", true);
  try {
    if (route.name === "search") await renderSearch(root, token, route.query || "");
    else if (route.name === "library") await renderLibrary(root, token, (route.param as LibraryTab) || "tracks");
    else if (route.name === "import") renderImport(root, token);
    else if (route.name === "artist" && route.param) await renderArtist(root, token, route.param);
    else if (route.name === "playlist" && route.param) await renderPlaylist(root, token, route.param);
    else if (route.name === "videos") await renderVideos(root, token);
    else await renderHome(root, token);
  } catch (error) {
    if (token === renderToken) root.replaceChildren(errorState(String((error as Error).message || error)));
  } finally {
    emit("view:loading", false);
  }
  if (token !== renderToken) return;
  // keep the active row states in sync with the player
  syncPlayingStates();
}

export function syncPlayingStates(): void {
  const current = player.current?.id;
  document.querySelectorAll<HTMLElement>("[data-track-id]").forEach((element) => {
    const isCurrent = !!current && element.dataset.trackId === current;
    element.classList.toggle("is-playing", isCurrent);
    element.classList.toggle("is-paused", !player.state.playing);
  });
  document.querySelectorAll<HTMLElement>("[data-artist-id]").forEach((element) => {
    element.dataset.active = "";
  });
}

export function findTrack(id: string): Track | null {
  return tracksById.get(id) || null;
}

export function sourceTracks(key: string | undefined, fallback: Track): Track[] {
  if (!key) return [fallback];
  const list = sources.get(key);
  return list?.length ? list : [fallback];
}

// ---------------------------------------------------------------------------
// Delegated view events
// ---------------------------------------------------------------------------

export function bindViewEvents(): void {
  const root = document.getElementById("view");
  if (!root) return;

  root.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    const actionEl = target.closest<HTMLElement>("[data-action]");
    if (!actionEl) return;    const action = actionEl.dataset.action;
    const scope = actionEl.closest<HTMLElement>("[data-track-id], [data-artist-id], [data-playlist-id]");
    const trackId = scope?.dataset.trackId;
    const sourceKey = scope?.dataset.source;

    if (action === "artist") {
      event.preventDefault();
      const artistId = actionEl.dataset.artistId || scope?.dataset.artistId;
      if (artistId) navigate(`/artist/${artistId}`);
      return;
    }

    if (action === "open-artist") {
      const artistId = scope?.dataset.artistId;
      if (artistId) navigate(`/artist/${artistId}`);
      return;
    }

    if (action === "playartist") {
      event.stopPropagation();
      const artistId = scope?.dataset.artistId;
      if (artistId) void playArtist(artistId);
      return;
    }

    if (action === "open-playlist") {
      const playlistId = scope?.dataset.playlistId;
      if (playlistId) navigate(`/playlist/${playlistId}`);
      return;
    }

    if (action === "playlist") {
      event.stopPropagation();
      const playlistId = scope?.dataset.playlistId;
      if (playlistId) void playPlaylist(playlistId);
      return;
    }

    if (action === "play" || action === "playvideo") {
      if (!trackId) return;
      const track = findTrack(trackId);
      if (!track) return;
      const queue = sourceTracks(sourceKey, track);
      player.playTrack(track, queue, { video: action === "playvideo" });
      return;
    }

    if (action === "like") {
      event.stopPropagation();
      if (!trackId) return;
      const liked = player.toggleLike(trackId);
      actionEl.classList.toggle("is-liked", liked);
      actionEl.setAttribute("aria-pressed", String(liked));
      emit("toast", liked ? "Added to your liked songs" : "Removed from liked songs");
      syncLikeButtons(trackId, liked);
      return;
    }

    if (action === "menu") {
      event.stopPropagation();
      if (!trackId) return;
      const track = findTrack(trackId);
      if (!track) return;
      const rect = actionEl.getBoundingClientRect();
      emit("context", { type: "track", track, x: rect.right, y: rect.bottom, source: sourceKey });
      return;
    }

    if (action === "plmenu") {
      event.stopPropagation();
      const playlistId = scope?.dataset.playlistId;
      const playlist = playlistId ? playlistsById.get(playlistId) : null;
      if (!playlist) return;
      const rect = actionEl.getBoundingClientRect();
      emit("context", { type: "playlist", playlist, x: rect.right, y: rect.bottom });
      return;
    }
  });

  root.addEventListener("contextmenu", (event) => {
    const card = (event.target as HTMLElement).closest<HTMLElement>(
      "[data-track-id], [data-playlist-id]",
    );
    if (!card) return;
    event.preventDefault();
    if (card.dataset.playlistId) {
      const playlist = playlistsById.get(card.dataset.playlistId);
      if (playlist) {
        emit("context", {
          type: "playlist",
          playlist,
          x: event.clientX,
          y: event.clientY,
        });
      }
      return;
    }
    const track = card.dataset.trackId ? findTrack(card.dataset.trackId) : null;
    if (track) {
      emit("context", {
        type: "track",
        track,
        x: event.clientX,
        y: event.clientY,
        source: card.dataset.source,
      });
    }
  });

  root.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const target = event.target as HTMLElement;
    if (target.closest("input, select, textarea")) return;
    const actionEl = target.closest<HTMLElement>("[data-action]");
    if (!actionEl || actionEl !== target) return;
    event.preventDefault();
    actionEl.click();
  });
}

export function syncLikeButtons(trackId: string, liked: boolean): void {
  document.querySelectorAll<HTMLElement>(`[data-track-id="${trackId}"] [data-action="like"]`).forEach((button) => {
    button.classList.toggle("is-liked", liked);
    button.setAttribute("aria-pressed", String(liked));
  });
  const playerLike = document.getElementById("btn-like");
  if (playerLike && player.current?.id === trackId) {
    playerLike.classList.toggle("is-liked", liked);
    playerLike.setAttribute("aria-pressed", String(liked));
  }
}

export async function playPlaylist(playlistId: string): Promise<void> {
  try {
    const data = await api.playlist(playlistId, 0, 2000);
    if (data.tracks[0]) player.playTrack(data.tracks[0], data.tracks);
  } catch (error) {
    emit("error", String((error as Error).message || error));
  }
}

export async function playArtist(artistId: string): Promise<void> {
  try {
    const data = await api.artist(artistId);
    if (data.tracks[0]) player.playTrack(data.tracks[0], data.tracks);
  } catch (error) {
    emit("error", String((error as Error).message || error));
  }
}

export function currentBootstrap(): Bootstrap | null {
  return bootstrap;
}

export function resetBootstrap(): void {
  bootstrap = null;
  bootstrapPromise = null;
}
