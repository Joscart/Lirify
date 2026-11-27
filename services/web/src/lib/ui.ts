import { api } from "./api";
import { inLanguage, language, text } from "./locale";
import { emit, on } from "./bus";
import { clamp, debounce, escapeHtml, fmtTime, seededBars } from "./format";
import { iconMarkup } from "./icons";
import { lyrics } from "./lyrics";
import { recordPlay } from "./history";
import { player } from "./player";
import type { Bootstrap, Playlist, Track } from "./types";
import {
  bindViewEvents,
  currentBootstrap,
  findTrack,
  getBootstrap,
  navigate,
  parseRoute,
  playPlaylist,
  renderRoute,
  sourceTracks,
  syncLikeButtons,
  syncPlayingStates,
} from "./views";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T | null;
const $$ = <T extends HTMLElement = HTMLElement>(selector: string) =>
  Array.from(document.querySelectorAll<T>(selector));
const mobileNavigation = matchMedia("(max-width: 980px)");

function setMobileMenu(open: boolean): void {
  document.body.dataset.menu = open ? "open" : "closed";
  $("btn-menu")?.setAttribute("aria-expanded", String(open));
  const sidebar = $("sidebar");
  if (sidebar) sidebar.inert = mobileNavigation.matches && !open;
  if (open) sidebar?.querySelector<HTMLElement>(".nav-item")?.focus();
}

const MINI_KEY = "lirify.mini.v1";

let lastWaveId = "__unset__";
let contextPayload: any = null;
let contextOpenedAt = 0;
let suggestTimer: number | undefined;
let suggestToken = 0;
let relatedCache = new Map<string, Track[]>();
let relatedFor = "";
let lastRouteName = "";

function setImage(
  img: HTMLImageElement | null,
  fallback: HTMLElement | null,
  primary: string,
  secondary = "",
): void {
  if (!img) return;
  img.hidden = false;
  img.decoding = "async";
  img.onerror = () => {
    if (secondary && img.src !== secondary) {
      img.src = secondary;
      return;
    }
    img.hidden = true;
    if (fallback) fallback.style.display = "grid";
  };
  img.onload = () => {
    if (fallback) fallback.style.display = "none";
  };
  if (img.dataset.src === primary) return;
  img.dataset.src = primary;
  img.src = primary;
}

// ---------------------------------------------------------------------------
// Toasts
// ---------------------------------------------------------------------------

function addToast(message: string, variant: "info" | "error" = "info"): void {
  const host = $("toasts");
  if (!host) return;
  const el = document.createElement("div");
  el.className = `toast${variant === "error" ? " is-error" : ""}`;
  el.innerHTML = `${iconMarkup(variant === "error" ? "wave" : "sparkles", "", 16)}<span>${escapeHtml(
    message,
  )}</span>`;
  host.appendChild(el);
  while (host.children.length > 4) host.firstElementChild?.remove();
  window.setTimeout(() => {
    el.classList.add("is-leaving");
    window.setTimeout(() => el.remove(), 220);
  }, 3800);
}

// ---------------------------------------------------------------------------
// Player chrome
// ---------------------------------------------------------------------------

function renderPlayerMeta(): void {
  const track = player.state.current;
  const title = $("pb-title");
  const artist = $("pb-artist");
  const art = $<HTMLImageElement>("pb-art-img");
  const fallback = $("pb-art-fallback");
  const like = $("btn-like");
  const miniTitle = $("mini-title");
  const miniArtist = $("mini-artist");
  const miniArt = $<HTMLImageElement>("mini-art");
  const miniFallback = $("mini-art-fallback");

  if (title) title.textContent = track?.title || text("Nada en reproducción", "Nothing playing");
  if (artist) artist.textContent = track?.artist || text("Elige una canción para empezar", "Pick a track to start");
  if (miniTitle) miniTitle.textContent = track?.title || text("Nada en reproducción", "Nothing playing");
  if (miniArtist) miniArtist.textContent = track?.artist || "—";

  if (track) {
    setImage(art, fallback, track.thumb, track.art);
    setImage(miniArt, miniFallback, track.thumb, track.art);
  } else {
    if (art) art.hidden = true;
    if (fallback) fallback.style.display = "grid";
    if (miniArt) miniArt.hidden = true;
    if (miniFallback) miniFallback.style.display = "grid";
  }

  if (like && track) {
    const liked = player.isLiked(track.id);
    like.classList.toggle("is-liked", liked);
    like.setAttribute("aria-pressed", String(liked));
  }

  const theaterTitle = $("theater-title");
  const theaterArtist = $("theater-artist");
  const theaterTrack = $("theater-track");
  const theaterTrackArtist = $("theater-track-artist");
  const theaterArt = $<HTMLImageElement>("theater-art");
  const theaterCover = $<HTMLImageElement>("theater-cover");
  if (theaterTitle) theaterTitle.textContent = track?.title || text("Video", "Theater");
  if (theaterArtist) theaterArtist.textContent = track?.artist || text("Nada en reproducción", "Nothing playing");
  if (theaterTrack) theaterTrack.textContent = track?.title || text("Nada en reproducción", "Nothing playing");
  if (theaterTrackArtist) theaterTrackArtist.textContent = track?.artist || "";
  if (track) {
    if (theaterArt) setImage(theaterArt, null, track.thumb, track.art);
    if (theaterCover) {
      setImage(theaterCover, null, track.thumb, track.art);
      theaterCover.alt = track.title;
    }
  }
  const openYt = $<HTMLAnchorElement>("theater-open-yt");
  if (openYt) {
    openYt.href = track ? track.youtube_url || `https://www.youtube.com/watch?v=${track.video_id}` : "#";
    openYt.style.visibility = track ? "visible" : "hidden";
  }

  document.title = track ? `${track.title} · ${track.artist} — UPSpotify` : text("UPSpotify · Busca canciones por su letra", "UPSpotify · Find songs by lyrics");
}

function renderTransport(): void {
  const state = player.state;
  const play = $("btn-play");
  const playIcon = play?.querySelector<SVGElement>(".icon-play");
  const pauseIcon = play?.querySelector<SVGElement>(".icon-pause");
  if (play) {
    const playing = state.playing;
    if (playIcon) playIcon.hidden = playing;
    if (pauseIcon) pauseIcon.hidden = !playing;
    play.setAttribute("aria-label", playing ? text("Pausar", "Pause") : text("Reproducir", "Play"));
    play.dataset.loading = String(state.loading && !state.playing);
    play.dataset.tip = state.loading ? text("Cargando…", "Loading…") : playing ? text("Pausar", "Pause") : text("Reproducir", "Play");
  }
  const theaterPlay = $("t-play");
  if (theaterPlay) {
    const iconPlay = theaterPlay.querySelector<SVGElement>(".icon-play");
    const iconPause = theaterPlay.querySelector<SVGElement>(".icon-pause");
    if (iconPlay) iconPlay.hidden = state.playing;
    if (iconPause) iconPause.hidden = !state.playing;
  }
  const miniPlay = $("mini-play");
  if (miniPlay) {
    miniPlay.innerHTML = iconMarkup(state.playing ? "pause" : "play", "", 16);
  }

  const shuffle = $("btn-shuffle");
  shuffle?.classList.toggle("is-on", state.shuffle);
  shuffle?.setAttribute("aria-pressed", String(state.shuffle));

  const repeat = $("btn-repeat");
  if (repeat) {
    const isOn = state.repeat !== "off";
    repeat.classList.toggle("is-on", isOn);
    repeat.setAttribute("aria-pressed", String(isOn));
    repeat.setAttribute(
      "aria-label",
      state.repeat === "one" ? text("Repetir una", "Repeat one") : state.repeat === "all" ? text("Repetir todas", "Repeat all") : text("Repetición desactivada", "Repeat off"),
    );
    repeat.innerHTML = iconMarkup(state.repeat === "one" ? "repeat-one" : "repeat", "", 16);
  }

  const mute = $("btn-mute");
  if (mute) {
    const icon = state.muted || state.volume === 0 ? "volume-mute" : state.volume < 0.45 ? "volume-low" : "volume-high";
    mute.innerHTML = iconMarkup(icon, "", 17);
    mute.setAttribute("aria-label", state.muted ? text("Activar sonido", "Unmute") : text("Silenciar", "Mute"));
  }
  const fill = $("volume-fill");
  if (fill) fill.style.setProperty("--v", `${Math.round((state.muted ? 0 : state.volume) * 100)}%`);
  const volume = $("volume");
  volume?.setAttribute("aria-valuenow", String(Math.round((state.muted ? 0 : state.volume) * 100)));

  const video = $("btn-video");
  video?.classList.toggle("is-on", state.mode === "video");
  const theaterModeLabel = $("theater-mode-label");
  if (theaterModeLabel) theaterModeLabel.textContent = state.mode === "video" ? text("Modo audio", "Audio mode") : text("Ver video", "Watch video");
  const theaterMode = $("theater-mode");
  if (theaterMode) theaterMode.classList.toggle("is-on", state.mode === "video");
  $("theater-video")?.classList.toggle("is-video", state.mode === "video");
  $("btn-lyrics")?.classList.toggle("is-on", document.body.dataset.lyrics === "open");
}

function renderProgress(): void {
  const state = player.state;
  const duration = state.duration || state.current?.duration || 0;
  const position = Math.max(0, state.position || 0);
  const pct = duration > 0 ? clamp((position / duration) * 100, 0, 100) : 0;
  const label = fmtTime(position);
  const total = fmtTime(duration);

  for (const id of ["seek-wave", "t-wave"]) {
    const wave = $(id);
    if (wave) wave.style.setProperty("--p", `${pct}%`);
  }
  const currentLabel = $("seek-current");
  if (currentLabel) currentLabel.textContent = label;
  const durationLabel = $("seek-duration");
  if (durationLabel) durationLabel.textContent = total;
  const tCurrent = $("t-current");
  if (tCurrent) tCurrent.textContent = label;
  const tDuration = $("t-duration");
  if (tDuration) tDuration.textContent = total;

  const mobile = $("mobile-progress-fill");
  if (mobile) mobile.style.width = `${pct}%`;
  const mobileSeek = $("mobile-seek");
  if (mobileSeek) {
    mobileSeek.setAttribute("aria-valuenow", String(Math.round(pct)));
    mobileSeek.setAttribute("aria-valuetext", `${label} of ${total}`);
  }
  const mini = $("mini-progress-fill");
  if (mini) mini.style.width = `${pct}%`;

  const seek = $("seek");
  if (seek) {
    seek.setAttribute("aria-valuenow", String(Math.round(pct)));
    seek.setAttribute("aria-valuetext", `${label} of ${total}`);
  }
  const tSeek = $("t-seek");
  if (tSeek) {
    tSeek.setAttribute("aria-valuenow", String(Math.round(pct)));
    tSeek.setAttribute("aria-valuetext", `${label} of ${total}`);
  }
}

function buildWave(track: Track | null): void {
  const id = track?.id || "";
  if (lastWaveId === id) return;
  lastWaveId = id;
  const bars = seededBars(id || "lirify", 84);
  for (const [baseId, playedId] of [
    ["wave-base", "wave-played"],
    ["t-wave-base", "t-wave-played"],
  ]) {
    const base = $(baseId);
    const played = $(playedId);
    if (!base || !played) continue;
    base.innerHTML = "";
    played.innerHTML = "";
    const baseFragment = document.createDocumentFragment();
    const playedFragment = document.createDocumentFragment();
    for (let index = 0; index < bars.length; index++) {
      const height = Math.round(5 + bars[index] * 19);
      const span = document.createElement("span");
      span.style.height = `${height}px`;
      baseFragment.appendChild(span);
      const clone = span.cloneNode() as HTMLElement;
      playedFragment.appendChild(clone);
    }
    base.appendChild(baseFragment);
    played.appendChild(playedFragment);
  }
}

function renderAllChrome(): void {
  renderPlayerMeta();
  renderTransport();
  renderProgress();
  renderTheater();
  renderQueue();
}

// ---------------------------------------------------------------------------
// Accent
// ---------------------------------------------------------------------------

function fillSidebar(data: Bootstrap): void {
  const list = $("sidebar-playlists");
  if (list) {
    const picks = [
      ...data.playlists.filter((playlist) => ["for-you", "fresh", "deep-cuts"].includes(playlist.id)),
      ...data.playlists.filter((playlist) => playlist.id.startsWith("lang-")),
      ...data.playlists.filter((playlist) => playlist.id.startsWith("artist-")),
    ].slice(0, 9);
    list.innerHTML = picks
      .map((playlist) => {
        const cover = playlist.covers?.[0] || playlist.cover;
        return `<li>
          <a class="sidebar-playlist" href="#/playlist/${encodeURIComponent(playlist.id)}" data-sidebar-playlist="${escapeHtml(
            playlist.id,
          )}">
            ${cover ? `<img src="${cover}" alt="" loading="lazy" />` : `<span class="mosaic"></span>`}
            <span class="meta"><b>${escapeHtml(playlist.title)}</b><span>${playlist.count} ${
              playlist.count === 1 ? text("canción", "track") : text("canciones", "tracks")
            }</span></span>
          </a>
        </li>`;
      })
      .join("");
  }
  const title = $("index-title");
  if (title) title.textContent = text(
    `${data.library.songs} canciones en el catálogo`,
    `${data.library.songs} songs in the catalogue`,
  );
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

function navKey(): string {
  const route = parseRoute();
  if (route.name === "home") return "home";
  if (route.name === "search") return "search";
  if (route.name === "videos") return "videos";
  if (route.name === "import") return "import";
  return "library";
}

function onRouteChange(): void {
  const route = parseRoute();
  document.body.dataset.searchLanding = String(route.name === "search" && !route.query);
  lastRouteName = route.name;
  $$("[data-nav]").forEach((item) => {
    const active = item.dataset.nav === navKey();
    item.classList.toggle("is-active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  const scroller = $("view-scroll");
  if (scroller) scroller.scrollTop = 0;
  const input = $<HTMLInputElement>("search-input");
  if (input) {
    if (route.name === "search") {
      if (document.activeElement !== input) input.value = route.query || "";
    } else {
      input.value = "";
      if (document.activeElement === input) input.blur();
    }
  }
  const clear = $("search-clear");
  if (clear) clear.hidden = !input?.value;
  closeMobileMenu();
  if (window.innerWidth < 1180) {
    setLyricsOpen(false);
    setQueueOpen(false);
  }
  hideSuggestions();
  void renderRoute(route);
}

function setHistoryNav(): void {
  const back = $<HTMLButtonElement>("btn-back");
  const forward = $<HTMLButtonElement>("btn-forward");
  if (back) back.onclick = () => history.back();
  if (forward) forward.onclick = () => history.forward();
}

// ---------------------------------------------------------------------------
// Search / suggestions
// ---------------------------------------------------------------------------

function hideSuggestions(): void {
  suggestToken++;
  const host = $("search-suggest");
  if (host) {
    host.hidden = true;
    host.innerHTML = "";
  }
}

async function showSuggestions(query: string): Promise<void> {
  const host = $("search-suggest");
  if (!host || query.trim().length < 2) {
    hideSuggestions();
    return;
  }
  const token = ++suggestToken;
  try {
    const payload = await api.search(query, 6);
    if (token !== suggestToken) return;
    if (!payload.tracks.length) {
      hideSuggestions();
      return;
    }
    host.innerHTML = `
      <div class="suggest-label">Songs & lyrics</div>
      ${payload.tracks
        .slice(0, 5)
        .map(
          (track) => `<button type="button" class="suggest-item" data-suggest-id="${track.id}">
            <img src="${track.thumb}" alt="" loading="lazy" />
            <span class="meta"><b>${escapeHtml(track.title)}</b><span>${escapeHtml(track.artist)}</span></span>
            <span class="go">${iconMarkup("play", "", 13)}</span>
          </button>`,
        )
        .join("")}
      <button type="button" class="suggest-all" data-suggest-all="${escapeHtml(query)}">
        See all results for “${escapeHtml(query)}”
      </button>`;
    host.hidden = false;
    host.querySelectorAll<HTMLButtonElement>("[data-suggest-id]").forEach((button) => {
      button.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        const track = payload.tracks.find((item) => item.id === button.dataset.suggestId);
        if (track) {
          player.playTrack(track, payload.tracks);
          hideSuggestions();
        }
      });
    });
    host.querySelector<HTMLButtonElement>("[data-suggest-all]")?.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      hideSuggestions();
      navigate(`/search/${encodeURIComponent(query)}`);
    });
  } catch {
    if (token === suggestToken) hideSuggestions();
  }
}

function bindSearch(): void {
  const input = $<HTMLInputElement>("search-input");
  const form = $<HTMLFormElement>("search-form");
  const clear = $("search-clear");
  if (!input || !form) return;

  const liveSearch = debounce(() => {
    if (lastRouteName !== "search") return;
    const query = input.value.trim();
    const path = query ? `#/search/${encodeURIComponent(query)}` : "#/search";
    history.replaceState(null, "", path);
    void renderRoute(parseRoute());
  }, 320);

  input.addEventListener("input", () => {
    if (clear) clear.hidden = !input.value;
    window.clearTimeout(suggestTimer);
    const query = input.value.trim();
    if (query.length >= 2) {
      suggestTimer = window.setTimeout(() => void showSuggestions(query), 190);
    } else {
      hideSuggestions();
    }
    liveSearch();
  });

  input.addEventListener("focus", () => {
    if (input.value.trim().length >= 2) void showSuggestions(input.value.trim());
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideSuggestions();
      input.blur();
    }
  });

  document.addEventListener("pointerdown", (event) => {
    if (!form.contains(event.target as Node)) hideSuggestions();
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = input.value.trim();
    hideSuggestions();
    if (query) navigate(`/search/${encodeURIComponent(query)}`);
    else navigate("/search");
  });

  clear?.addEventListener("click", () => {
    input.value = "";
    clear.hidden = true;
    hideSuggestions();
    input.focus();
    if (lastRouteName === "search") navigate("/search");
  });
}

// ---------------------------------------------------------------------------
// Panels
// ---------------------------------------------------------------------------

function setLyricsOpen(open: boolean): void {
  document.body.dataset.lyrics = open ? "open" : "closed";
  $("lyrics-panel")?.setAttribute("aria-hidden", String(!open));
  $("btn-lyrics")?.classList.toggle("is-on", open);
  $("btn-lyrics")?.setAttribute("aria-pressed", String(open));
  $("btn-lyrics-top")?.classList.toggle("is-on", open);
  $("btn-lyrics-top")?.setAttribute("aria-pressed", String(open));
  if (!open) {
    const panel = $("lyrics-panel");
    if (panel?.classList.contains("is-expanded")) {
      panel.classList.remove("is-expanded");
      const expand = $("lyrics-expand");
      if (expand) {
        expand.innerHTML = iconMarkup("expand", "", 15);
        expand.setAttribute("aria-label", text("Expandir letra", "Expand lyrics"));
      }
    }
  } else {
    if (window.innerWidth < 1180) setQueueOpen(false);
    lyrics.follow();
    lyrics.tick(true);
  }
}

function toggleLyrics(): void {
  setLyricsOpen(document.body.dataset.lyrics !== "open");
}

function toggleLyricsExpand(): void {
  const panel = $("lyrics-panel");
  if (!panel) return;
  const expanded = panel.classList.toggle("is-expanded");
  const track = player.state.current;
  if (expanded && track) {
    panel.style.setProperty("--cover-url", `url("${track.thumb}")`);
  }
  $("lyrics-expand")!.innerHTML = iconMarkup(expanded ? "minimize" : "expand", "", 15);
  $("lyrics-expand")?.setAttribute("aria-label", expanded ? text("Contraer letra", "Shrink lyrics") : text("Expandir letra", "Expand lyrics"));
  if (expanded) {
    lyrics.tick(true);
    lyrics.follow();
  }
}

function setQueueOpen(open: boolean): void {
  document.body.dataset.queue = open ? "open" : "closed";
  $("queue-drawer")?.setAttribute("aria-hidden", String(!open));
  $("btn-queue")?.classList.toggle("is-on", open);
  $("btn-queue")?.setAttribute("aria-pressed", String(open));
  $("btn-queue-top")?.classList.toggle("is-on", open);
  $("btn-queue-top")?.setAttribute("aria-pressed", String(open));
  if (open) {
    if (window.innerWidth < 1180) setLyricsOpen(false);
    renderQueue();
    if (document.querySelector('[data-queue-tab="related"].is-active')) void loadRelated(true);
  }
}

function toggleQueue(): void {
  setQueueOpen(document.body.dataset.queue !== "open");
}

function setTheaterOpen(open: boolean): void {
  document.body.dataset.theater = open ? "open" : "closed";
  $("theater")?.setAttribute("aria-hidden", String(!open));
  if (open) {
    setQueueOpen(false);
    setMini(false);
    renderTheater();
    lyrics.tick(true);
    lyrics.follow();
  }
}

function openTheater(forceVideo = false): void {
  const track = player.state.current;
  if (!track) {
    addToast(text("Reproduce una canción para abrir el video.", "Play a track first to open the theater."));
    return;
  }
  setTheaterOpen(true);
  if (forceVideo) player.setMode("video");
  else {
    renderTheater();
    requestAnimationFrame(() => lyrics.tick(true));
  }
}

function closeTheater(): void {
  if (player.state.mode === "video") {
    player.closeVideo();
  } else {
    setTheaterOpen(false);
    if (player.state.usingIframe) player.stopVideoBridge();
  }
}

function renderTheater(): void {
  const state = player.state;
  const track = state.current;
  const theater = $("theater");
  const isVideo = state.mode === "video";
  theater?.classList.toggle("is-video", isVideo);
  $("theater-video")?.classList.toggle("is-video", isVideo);
  const cover = $<HTMLImageElement>("theater-cover");
  if (cover && track) {
    setImage(cover, null, track.thumb, track.art);
    cover.alt = track.title;
    theater?.style.setProperty("--cover-url", `url("${track.thumb}")`);
  }
  const empty = $("theater-empty");
  if (empty) empty.hidden = true;
  const modeLabel = $("theater-mode-label");
  if (modeLabel) modeLabel.textContent = isVideo ? text("Modo audio", "Audio mode") : text("Ver video", "Watch video");
  const toggle = $("theater-lyrics-toggle");
  toggle?.setAttribute("aria-pressed", String(!theater?.classList.contains("is-lyrics-hidden")));
}

function setMini(enabled: boolean): void {
  player.state.mini = enabled;
  document.body.dataset.mini = enabled ? "on" : "off";
  localStorage.setItem(MINI_KEY, enabled ? "on" : "off");
  $("btn-mini")?.classList.toggle("is-on", enabled);
  player.persistPosition();
}

function toggleMini(): void {
  setMini(document.body.dataset.mini !== "on");
}

// ---------------------------------------------------------------------------
// Queue
// ---------------------------------------------------------------------------

function queueRow(
  track: Track,
  options: { current?: boolean; orderPosition?: number; related?: boolean } = {},
): string {
  const remove = options.related
    ? `<button class="icon-btn tiny" data-related-add="${track.id}" aria-label="${text("Agregar a la cola", "Add to queue")}">${iconMarkup("plus", "", 14)}</button>`
    : options.current
      ? `<button class="icon-btn tiny" data-queue-toggle aria-label="${text("Reproducir o pausar", "Play or pause")}">${iconMarkup(
          player.state.playing ? "pause" : "play",
          "",
          14,
        )}</button>`
      : options.orderPosition !== undefined
        ? `<button class="icon-btn tiny" data-q-remove="${options.orderPosition}" aria-label="${text("Quitar de la cola", "Remove from queue")}">${iconMarkup(
            "close",
            "",
            14,
          )}</button>`
        : "";
  return `<div class="queue-item${options.current ? " is-current" : ""}" ${
    options.related
      ? `data-related-play="${track.id}"`
      : options.orderPosition !== undefined
        ? `data-q-jump="${options.orderPosition}"`
        : ""
  } data-track-id="${track.id}">
    <img src="${track.thumb}" alt="" loading="lazy" />
    <div class="meta"><b>${escapeHtml(track.title)}</b><span>${escapeHtml(track.artist)}</span></div>
    ${remove}
  </div>`;
}

function renderQueue(): void {
  const now = $("queue-now");
  const next = $("queue-next");
  const history = $("queue-history");
  const count = $("queue-count");
  const historyLabel = document.querySelector<HTMLElement>("[data-queue-history-label]");
  if (!now || !next || !history) return;
  const current = player.state.current;
  now.innerHTML = current ? queueRow(current, { current: true }) : `<div class="queue-label">Nothing playing yet</div>`;
  const upcoming = player.upcoming(40);
  next.innerHTML = upcoming.length
    ? upcoming
        .map(({ track, orderPosition }) => queueRow(track, { orderPosition }))
        .join("")
    : `<div class="queue-label" style="letter-spacing:0;text-transform:none;color:var(--text-4)">The queue is empty — Automix will refill it when this track ends.</div>`;
  const played = player.history(8);
  history.innerHTML = played.map((track) => queueRow(track)).join("");
  if (historyLabel) historyLabel.hidden = !played.length;
  if (count) count.textContent = `${upcoming.length} ${upcoming.length === 1 ? "track" : "tracks"}`;
  $("queue-automix")?.classList.toggle("is-on", player.state.automix);
  $("queue-automix")?.setAttribute("aria-checked", String(player.state.automix));
  if (!current) relatedFor = "";
}

async function loadRelated(force = false): Promise<void> {
  const host = $("queue-related");
  if (!host) return;
  const current = player.state.current;
  if (!current) {
    host.innerHTML = `<div class="queue-label" style="letter-spacing:0;text-transform:none">Play a track to see related songs.</div>`;
    return;
  }
  if (!force && relatedFor === current.id && relatedCache.has(current.id)) {
    renderRelated(host, relatedCache.get(current.id)!);
    return;
  }
  host.innerHTML = `<div class="queue-label">Reading the similarity matrix…</div>`;
  try {
    const data = await api.radio(current.id, 14);
    relatedCache.set(current.id, data.recommendations);
    relatedFor = current.id;
    renderRelated(host, data.recommendations);
  } catch {
    host.innerHTML = `<div class="queue-label" style="letter-spacing:0;text-transform:none">Related songs are unavailable right now.</div>`;
  }
}

function renderRelated(host: HTMLElement, tracks: Track[]): void {
  host.innerHTML = tracks
    .map(
      (track, index) => `<div class="queue-item" data-related-play="${track.id}">
        <span class="grip">${String(index + 1).padStart(2, "0")}</span>
        <img src="${track.thumb}" alt="" loading="lazy" />
        <div class="meta"><b>${escapeHtml(track.title)}</b><span>${escapeHtml(track.artist)}</span></div>
        <button class="icon-btn tiny" data-related-add="${track.id}" aria-label="${text("Agregar a la cola", "Add to queue")}">${iconMarkup(
          "plus",
          "",
          14,
        )}</button>
      </div>`,
    )
    .join("");
}

function bindQueue(): void {
  $("btn-queue")?.addEventListener("click", toggleQueue);
  $("btn-queue-top")?.addEventListener("click", toggleQueue);
  $("queue-close")?.addEventListener("click", () => setQueueOpen(false));
  $("queue-clear")?.addEventListener("click", () => {
    player.clearUpcoming();
    renderQueue();
    addToast(text("Cola vaciada", "Cleared the upcoming queue"));
  });
  $("queue-automix")?.addEventListener("click", () => {
    player.setAutomix(!player.state.automix);
    renderQueue();
  });
  $$<HTMLButtonElement>("[data-queue-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$("[data-queue-tab]").forEach((item) => {
        item.classList.toggle("is-active", item === tab);
        item.setAttribute("aria-selected", String(item === tab));
      });
      $$<HTMLElement>("[data-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.panel !== tab.dataset.queueTab;
      });
      if (tab.dataset.queueTab === "related") void loadRelated();
    });
  });
  $("queue-body")?.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    const add = target.closest<HTMLElement>("[data-related-add]");
    if (add) {
      event.stopPropagation();
      const track = findTrack(add.dataset.relatedAdd || "") ||
        relatedCache.get(relatedFor)?.find((item) => item.id === add.dataset.relatedAdd);
      if (track) player.addToQueue(track);
      return;
    }
    const remove = target.closest<HTMLElement>("[data-q-remove]");
    if (remove) {
      event.stopPropagation();
      const position = Number(remove.dataset.qRemove);
      if (Number.isFinite(position)) player.removeFromQueue(position);
      renderQueue();
      return;
    }
    const jump = target.closest<HTMLElement>("[data-q-jump]");
    if (jump) {
      const position = Number(jump.dataset.qJump);
      if (Number.isFinite(position)) player.jumpTo(position);
      return;
    }
    const relatedPlay = target.closest<HTMLElement>("[data-related-play]");
    if (relatedPlay) {
      const id = relatedPlay.dataset.relatedPlay || "";
      const list = relatedCache.get(relatedFor) || [];
      const track = list.find((item) => item.id === id);
      if (track) player.playTrack(track, list);
      return;
    }
    if (target.closest("[data-queue-toggle]")) player.toggle();
  });
}

// ---------------------------------------------------------------------------
// Context menu
// ---------------------------------------------------------------------------

interface ContextItem {
  label: string;
  icon: string;
  action: string;
  danger?: boolean;
  hint?: string;
  separator?: boolean;
}

function openContext(payload: any): void {
  contextPayload = payload;
  const menu = $("ctx-menu");
  if (!menu) return;
  let heading = "";
  let items: ContextItem[] = [];
  if (payload.type === "track") {
    const track: Track = payload.track;
    heading = `<b>${escapeHtml(track.title)}</b><span>${escapeHtml(track.artist)}</span>`;
    items = [
      { label: "Play now", icon: "play", action: "play" },
      { label: "Play next", icon: "list", action: "next" },
      { label: text("Agregar a la cola", "Add to queue"), icon: "plus", action: "queue" },
      { label: "Start radio", icon: "radio", action: "radio" },
      { separator: true, label: "", icon: "", action: "" },
      { label: "Watch music video", icon: "video", action: "video" },
      { label: "Go to artist", icon: "headphones", action: "artist" },
      { label: "Open lyrics", icon: "mic", action: "lyrics" },
      { separator: true, label: "", icon: "", action: "" },
      {
        label: player.isLiked(track.id) ? "Remove from liked" : "Add to liked",
        icon: "heart",
        action: "like",
      },
      { label: "Copy link", icon: "link", action: "copy" },
      { label: "Open on YouTube", icon: "external", action: "youtube" },
    ];
  } else if (payload.type === "playlist") {
    const playlist: Playlist = payload.playlist;
    heading = `<b>${escapeHtml(playlist.title)}</b><span>${playlist.count} tracks · ${escapeHtml(
      playlist.tag || "playlist",
    )}</span>`;
    items = [
      { label: text("Reproducir", "Play"), icon: "play", action: "playlist-play" },
      { label: "Shuffle", icon: "shuffle", action: "playlist-shuffle" },
      { label: "Open playlist", icon: "list", action: "playlist-open" },
      { separator: true, label: "", icon: "", action: "" },
      { label: "Copy link", icon: "link", action: "playlist-copy" },
    ];
  }
  menu.innerHTML = `
    <div class="ctx-head">${heading}</div>
    ${items
      .map((item) =>
        item.separator
          ? `<div class="ctx-sep"></div>`
          : `<button class="ctx-item${item.danger ? " is-danger" : ""}" data-ctx="${item.action}">
              ${iconMarkup(item.icon, "", 16)}
              <span>${escapeHtml(item.label)}</span>
              ${item.hint ? `<span class="ctx-hint">${item.hint}</span>` : ""}
            </button>`,
      )
      .join("")}`;
  menu.classList.add("is-open");
  contextOpenedAt = Date.now();
  const rect = menu.getBoundingClientRect();
  const x = Math.min(window.innerWidth - rect.width - 12, Math.max(12, payload.x));
  const y = Math.min(window.innerHeight - rect.height - 12, Math.max(12, payload.y));
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
}

function closeContext(): void {
  $("ctx-menu")?.classList.remove("is-open");
  contextPayload = null;
}

function bindContext(): void {
  const menu = $("ctx-menu");
  menu?.addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLElement>("[data-ctx]");
    if (!button || !contextPayload) return;
    const action = button.dataset.ctx;
    const payload = contextPayload;
    closeContext();
    if (payload.type === "playlist") {
      const playlist: Playlist = payload.playlist;
      if (action === "playlist-play") void playPlaylist(playlist.id);
      else if (action === "playlist-shuffle") {
        api.playlist(playlist.id, 0, 2000).then((data) => {
          const queue = [...data.tracks].sort(() => Math.random() - 0.5);
          if (queue[0]) player.playTrack(queue[0], queue);
        }).catch((error) => addToast(String(error.message || error), "error"));
      } else if (action === "playlist-open") navigate(`/playlist/${playlist.id}`);
      else if (action === "playlist-copy") {
        navigator.clipboard
          ?.writeText(`${location.origin}${location.pathname}#/playlist/${playlist.id}`)
          .then(() => addToast(text("Enlace de la lista copiado", "Playlist link copied")))
          .catch(() => addToast(text("No se pudo copiar el enlace", "Could not copy the link"), "error"));
      }
      return;
    }
    const track: Track = payload.track;
    const queue = sourceTracks(payload.source, track);
    if (action === "play") player.playTrack(track, queue);
    else if (action === "next") player.playNext(track);
    else if (action === "queue") player.addToQueue(track);
    else if (action === "radio") {
      void player.playTrack(track, [track]).then(() => player.appendAutomix());
      setQueueOpen(true);
    } else if (action === "video") player.playTrack(track, queue, { video: true });
    else if (action === "artist") navigate(`/artist/${track.artist_id}`);
    else if (action === "lyrics") {
      if (player.state.current?.id !== track.id) void player.playTrack(track, queue);
      document.body.dataset.lyrics = "open";
      setLyricsOpen(true);
    } else if (action === "like") {
      const liked = player.toggleLike(track.id);
      syncLikeButtons(track.id, liked);
      addToast(liked ? text("Canción añadida a tus favoritos", "Added to your liked songs") : text("Canción quitada de tus favoritos", "Removed from liked songs"));
      renderPlayerMeta();
    } else if (action === "copy") {
      navigator.clipboard
        ?.writeText(track.youtube_url || `https://www.youtube.com/watch?v=${track.video_id}`)
        .then(() => addToast(text("Enlace de YouTube copiado", "YouTube link copied")))
        .catch(() => addToast(text("No se pudo copiar el enlace", "Could not copy the link"), "error"));
    } else if (action === "youtube") {
      window.open(track.youtube_url || `https://www.youtube.com/watch?v=${track.video_id}`, "_blank", "noopener");
    }
  });

  document.addEventListener("pointerdown", (event) => {
    const menu = $("ctx-menu");
    if (!menu?.classList.contains("is-open")) return;
    if (!menu.contains(event.target as Node)) closeContext();
  });
  let scrollTimer: number | undefined;
  $("view-scroll")?.addEventListener("scroll", () => {
    window.clearTimeout(scrollTimer);
    scrollTimer = window.setTimeout(() => {
      // A click that scrolls its target into view must not eat its own menu.
      if (Date.now() - contextOpenedAt < 350) return;
      closeContext();
    }, 120);
    $("topbar")?.classList.toggle("is-stuck", ($("view-scroll")?.scrollTop || 0) > 8);
  }, { passive: true });
}

// ---------------------------------------------------------------------------
// Player binding
// ---------------------------------------------------------------------------

function bindPlayer(): void {
  $("btn-play")?.addEventListener("click", () => player.toggle());
  $("btn-prev")?.addEventListener("click", () => player.prev());
  $("btn-next")?.addEventListener("click", () => void player.next());
  $("btn-shuffle")?.addEventListener("click", () => {
    player.toggleShuffle();
    renderTransport();
  });
  $("btn-repeat")?.addEventListener("click", () => {
    player.cycleRepeat();
    renderTransport();
  });
  $("btn-mute")?.addEventListener("click", () => {
    player.toggleMute();
    renderTransport();
  });
  $("btn-like")?.addEventListener("click", () => {
    const track = player.state.current;
    if (!track) return;
    const liked = player.toggleLike(track.id);
    likeButton(liked, track.id);
  });
  $("btn-more")?.addEventListener("click", (event) => {
    const track = player.state.current;
    if (!track) return;
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    emit("context", {
      type: "track",
      track,
      x: rect.right,
      y: rect.top - 8,
      source: undefined,
    });
  });
  const openNowPlaying = () => {
    if (!player.state.current) {
      addToast(text("Elige primero una canción.", "Pick a song first."));
      return;
    }
    if (window.innerWidth < 980) setLyricsOpen(true);
    else openTheater(false);
  };
  $("pb-art")?.addEventListener("click", openNowPlaying);
  $("pb-title")?.addEventListener("click", openNowPlaying);
  for (const element of [$("pb-art"), $("pb-title")]) {
    element?.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      openNowPlaying();
    });
  }
  $("pb-artist")?.addEventListener("click", () => {
    const track = player.state.current;
    if (track) navigate(`/artist/${track.artist_id}`);
  });
  $("btn-video")?.addEventListener("click", () => {
    if (!player.state.current) return addToast(text("Elige una canción para ver el video.", "Pick a song to watch."));
    if (player.state.mode === "video") {
      player.setMode("audio");
    } else {
      openTheater(true);
    }
  });
  $("btn-theater")?.addEventListener("click", () => openTheater(false));
  $("btn-lyrics")?.addEventListener("click", toggleLyrics);
  $("btn-lyrics-top")?.addEventListener("click", toggleLyrics);
  $("btn-mini")?.addEventListener("click", toggleMini);
  $("mini-expand")?.addEventListener("click", () => setMini(false));
  $("mini-play")?.addEventListener("click", () => player.toggle());
  $("mini-next")?.addEventListener("click", () => void player.next());
  $("mini-art")?.addEventListener("click", openNowPlaying);

  bindWaveform($("seek"), $("seek-wave"));
  bindWaveform($("t-seek"), $("t-wave"));
  bindVolume();
  bindMobileSeek();
}

function bindMobileSeek(): void {
  const bar = $("mobile-seek");
  if (!bar) return;
  const percent = (event: PointerEvent) => {
    const rect = bar.getBoundingClientRect();
    return clamp((event.clientX - rect.left) / Math.max(1, rect.width), 0, 1);
  };
  const commit = (event: PointerEvent) => {
    const duration = player.state.duration || player.state.current?.duration || 0;
    if (!duration) return;
    player.seek(percent(event) * duration);
  };
  bar.addEventListener("pointerdown", (event) => {
    if (!player.state.current) return;
    bar.setPointerCapture(event.pointerId);
    commit(event);
  });
  bar.addEventListener("pointermove", (event) => {
    if ((event.buttons & 1) === 0) return;
    commit(event);
  });
  bar.addEventListener("pointerup", (event) => {
    commit(event);
    try {
      bar.releasePointerCapture(event.pointerId);
    } catch {
      /* noop */
    }
  });
  bar.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    player.seekBy(event.key === "ArrowRight" ? 5 : -5);
  });
}

function likeButton(liked: boolean, trackId: string): void {
  const button = $("btn-like");
  button?.classList.toggle("is-liked", liked);
  button?.setAttribute("aria-pressed", String(liked));
  syncLikeButtons(trackId, liked);
  renderPlayerMeta();
  addToast(liked ? text("Canción añadida a tus favoritos", "Added to your liked songs") : text("Canción quitada de tus favoritos", "Removed from liked songs"));
}

function bindWaveform(container: HTMLElement | null, wave: HTMLElement | null): void {
  if (!container || !wave) return;
  let dragging = false;
  const percentAt = (event: PointerEvent) => {
    const rect = wave.getBoundingClientRect();
    return clamp((event.clientX - rect.left) / Math.max(1, rect.width), 0, 1);
  };
  const paint = (pct: number) => {
    wave.style.setProperty("--p", `${pct * 100}%`);
    const duration = player.state.duration || player.state.current?.duration || 0;
    if (container.id === "seek") {
      const label = $("seek-current");
      if (label) label.textContent = fmtTime(pct * duration);
    } else {
      const label = $("t-current");
      if (label) label.textContent = fmtTime(pct * duration);
    }
  };
  const commit = (event: PointerEvent) => {
    const duration = player.state.duration || player.state.current?.duration || 0;
    if (!duration) return;
    player.seek(percentAt(event) * duration);
    paint(percentAt(event));
  };
  wave.addEventListener("pointerdown", (event) => {
    if (!player.state.current) return;
    dragging = true;
    wave.classList.add("is-dragging");
    wave.setPointerCapture(event.pointerId);
    paint(percentAt(event));
    event.preventDefault();
  });
  wave.addEventListener("pointermove", (event) => {
    const pct = percentAt(event);
    const tooltip = $("seek-tooltip");
    if (tooltip) {
      const duration = player.state.duration || player.state.current?.duration || 0;
      tooltip.textContent = fmtTime(pct * duration);
      tooltip.style.setProperty("--x", `${pct * 100}%`);
    }
    if (dragging) paint(pct);
  });
  wave.addEventListener("pointerup", (event) => {
    if (!dragging) return;
    dragging = false;
    wave.classList.remove("is-dragging");
    try {
      wave.releasePointerCapture(event.pointerId);
    } catch {
      /* pointer already released */
    }
    commit(event);
  });
  wave.addEventListener("pointercancel", () => {
    dragging = false;
    wave.classList.remove("is-dragging");
  });

  container.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight" && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const duration = player.state.duration || player.state.current?.duration || 0;
    if (event.key === "Home") player.seek(0);
    else if (event.key === "End") player.seek(duration);
    else player.seekBy((event.key === "ArrowRight" ? 1 : -1) * (event.shiftKey ? 30 : 5));
  });
}

function bindVolume(): void {
  const volume = $("volume");
  if (!volume) return;
  let dragging = false;
  const percent = (event: PointerEvent) => {
    const rect = volume.getBoundingClientRect();
    return clamp((event.clientX - rect.left) / Math.max(1, rect.width), 0, 1);
  };
  const update = (value: number) => {
    player.setVolume(value);
    renderTransport();
  };
  volume.addEventListener("pointerdown", (event) => {
    dragging = true;
    volume.setPointerCapture(event.pointerId);
    update(percent(event));
  });
  volume.addEventListener("pointermove", (event) => {
    if (dragging) update(percent(event));
  });
  volume.addEventListener("pointerup", (event) => {
    if (!dragging) return;
    dragging = false;
    update(percent(event));
    try {
      volume.releasePointerCapture(event.pointerId);
    } catch {
      /* noop */
    }
  });
  volume.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    player.setVolume(player.state.volume + (event.key === "ArrowRight" ? 0.05 : -0.05));
    renderTransport();
  });
}

function bindPanels(): void {
  $("lyrics-close")?.addEventListener("click", () => {
    const panel = $("lyrics-panel");
    if (panel?.classList.contains("is-expanded")) {
      toggleLyricsExpand();
      return;
    }
    setLyricsOpen(false);
  });
  $("lyrics-expand")?.addEventListener("click", toggleLyricsExpand);
  $("lyrics-offset-minus")?.addEventListener("click", () => lyrics.adjustOffset(-0.25));
  $("lyrics-offset-plus")?.addEventListener("click", () => lyrics.adjustOffset(0.25));
  $("lyrics-follow")?.addEventListener("click", () => lyrics.follow());
  $("theater-lyrics-follow")?.addEventListener("click", () => lyrics.follow());
  on("lyrics:follow", (following: boolean) => {
    for (const id of ["lyrics-follow", "theater-lyrics-follow"]) {
      const button = $(id);
      if (button) {
        button.hidden = following;
        button.classList.toggle("is-visible", !following);
      }
    }
  });

  $("theater-close")?.addEventListener("click", closeTheater);
  $("theater-mode")?.addEventListener("click", () => {
    if (player.state.mode === "video") player.setMode("audio");
    else player.setMode("video");
    renderTheater();
  });
  $("theater-lyrics-toggle")?.addEventListener("click", () => {
    const theater = $("theater");
    if (!theater) return;
    const hidden = theater.classList.toggle("is-lyrics-hidden");
    $("theater-lyrics-toggle")?.setAttribute("aria-pressed", String(!hidden));
  });
  $("t-play")?.addEventListener("click", () => player.toggle());
  $("t-prev")?.addEventListener("click", () => player.prev());
  $("t-next")?.addEventListener("click", () => void player.next());

  $("btn-menu")?.addEventListener("click", () => {
    setMobileMenu(document.body.dataset.menu !== "open");
  });
  $("scrim")?.addEventListener("click", () => {
    closeMobileMenu();
    $("btn-menu")?.focus();
  });
  mobileNavigation.addEventListener("change", closeMobileMenu);
  $$<HTMLElement>("[data-nav]").forEach((item) => item.addEventListener("click", closeMobileMenu));
  $$<HTMLElement>(".sidebar-playlist").forEach((item) => item.addEventListener("click", closeMobileMenu));
}

function closeMobileMenu(): void {
  setMobileMenu(false);
}

// ---------------------------------------------------------------------------
// Keyboard
// ---------------------------------------------------------------------------

function isTypingTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element) return false;
  return (
    element.tagName === "INPUT" ||
    element.tagName === "TEXTAREA" ||
    element.tagName === "SELECT" ||
    element.isContentEditable
  );
}

function bindKeyboard(): void {
  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented) return;
    if (event.key === "Escape") {
      if ($("ctx-menu")?.classList.contains("is-open")) return closeContext();
      if ($("search-suggest") && !$("search-suggest")!.hidden) return hideSuggestions();
      if ($("lyrics-panel")?.classList.contains("is-expanded")) return toggleLyricsExpand();
      if (document.body.dataset.theater === "open") return closeTheater();
      if (document.body.dataset.lyrics === "open" && window.innerWidth < 900) return setLyricsOpen(false);
      if (document.body.dataset.queue === "open") return setQueueOpen(false);
      if (document.body.dataset.menu === "open") {
        closeMobileMenu();
        $("btn-menu")?.focus();
      }
      return;
    }
    if (isTypingTarget(event.target)) return;
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const interactive = (event.target as HTMLElement | null)?.closest?.(
      "button, a, input, select, textarea, [role='button'], [role='slider'], [role='switch']",
    );
    if (interactive) return;

    switch (event.key.toLowerCase()) {
      case " ":
        event.preventDefault();
        player.toggle();
        break;
      case "arrowright":
        event.preventDefault();
        player.seekBy(event.shiftKey ? 30 : 5);
        break;
      case "arrowleft":
        event.preventDefault();
        player.seekBy(event.shiftKey ? -30 : -5);
        break;
      case "arrowup":
        event.preventDefault();
        player.setVolume(player.state.volume + 0.05);
        renderTransport();
        break;
      case "arrowdown":
        event.preventDefault();
        player.setVolume(player.state.volume - 0.05);
        renderTransport();
        break;
      case "m":
        player.toggleMute();
        renderTransport();
        break;
      case "l":
        toggleLyrics();
        break;
      case "q":
        toggleQueue();
        break;
      case "t":
        if (document.body.dataset.theater === "open") closeTheater();
        else openTheater(false);
        break;
      case "v":
        if (player.state.current) {
          if (player.state.mode === "video") player.setMode("audio");
          else openTheater(true);
        }
        break;
      case "/":
        event.preventDefault();
        ($<HTMLInputElement>("course-query") || $<HTMLInputElement>("search-input"))?.focus();
        break;
      default:
        break;
    }
  });
}

// ---------------------------------------------------------------------------
// Bus wiring
// ---------------------------------------------------------------------------

function bindBus(): void {
  on("toast", (message: string) => addToast(message));
  on("error", (message: string) => addToast(message, "error"));
  on("context", openContext);
  on("queue-open", (open: boolean) => setQueueOpen(open));
  on("theater", (open: boolean) => setTheaterOpen(open));
  on("lyrics:loaded", () => lyrics.tick(true));
  on("bootstrap", (data: Bootstrap) => {
    fillSidebar(data);
  });

  on("track", (track: Track) => {
    // Listening history and recommendation seeds never leave this browser.
    recordPlay(track);
    buildWave(track);
    renderPlayerMeta();
    renderTransport();
    renderQueue();
    renderTheater();
    relatedFor = "";
    if (window.innerWidth >= 1180) {
      // Loading lyrics for the new track is handled by the lyrics controller.
    }
  });
  on("playback", () => {
    renderTransport();
    renderProgress();
    renderPlayerMeta();
    renderQueue();
    syncPlayingStates();
    lyrics.tick(true);
  });
  on("queue", () => {
    renderTransport();
    renderQueue();
  });
  on("tick", () => {
    renderProgress();
    lyrics.tick();
  });
  on("volume", () => renderTransport());
  on("session", () => lyrics.tick(true));
  on("likes", () => renderPlayerMeta());
  on("duration", (payload: { id: string; duration: number }) => {
    if (player.state.current?.id === payload.id) {
      renderProgress();
    }
    document.querySelectorAll<HTMLElement>(`[data-track-id="${payload.id}"]`).forEach((element) => {
      const value = fmtTime(payload.duration);
      element.querySelectorAll<HTMLElement>(".card-duration, .track-duration").forEach((label) => {
        label.hidden = false;
        label.textContent = value;
      });
    });
  });
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

function bindTheme(): void {
  const root = document.documentElement;
  const button = $("theme-toggle");
  const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  const system = matchMedia("(prefers-color-scheme: light)");
  let manual = false;
  try {
    const saved = localStorage.getItem("lirify-theme");
    manual = saved === "light" || saved === "dark";
  } catch {}

  function applyTheme(theme: "light" | "dark"): void {
    root.dataset.theme = theme;
    button?.setAttribute("aria-pressed", String(theme === "dark"));
    if (themeColor) themeColor.content = theme === "dark" ? "#171b29" : "#f6f2e9";
  }

  applyTheme(root.dataset.theme === "light" ? "light" : "dark");
  button?.addEventListener("click", () => {
    const theme = root.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(theme);
    manual = true;
    try {
      localStorage.setItem("lirify-theme", theme);
    } catch {}
  });
  system.addEventListener("change", (event) => {
    if (!manual) applyTheme(event.matches ? "light" : "dark");
  });
  document.querySelector(".skip-link")?.addEventListener("click", (event) => {
    event.preventDefault();
    $("view")?.focus();
  });
}

function boot(): void {
  bindTheme();
  const locale = $<HTMLSelectElement>("language-select");
  locale?.addEventListener("change", () => {
    location.assign(inLanguage(location.href, locale.value === "en" ? "en" : "es"));
  });
  const indexer = $<HTMLAnchorElement>("indexer-link");
  if (indexer) indexer.href = "#/library";
  document.body.dataset.lyrics = "closed";
  document.body.dataset.queue = "closed";
  document.body.dataset.theater = "closed";
  document.body.dataset.menu = "closed";

  bindBus();
  lyrics.init();
  bindViewEvents();
  bindPlayer();
  bindPanels();
  bindQueue();
  bindContext();
  bindSearch();
  bindKeyboard();
  setHistoryNav();
  player.init();
  (window as any).__lirify = { player, lyrics };
  const miniStored = localStorage.getItem(MINI_KEY);
  if (miniStored === "on") setMini(true);
  else document.body.dataset.mini = "off";

  renderAllChrome();
  buildWave(player.state.current);
  lastRouteName = parseRoute().name;

  window.addEventListener("hashchange", onRouteChange);
  if (!location.hash) history.replaceState(null, "", "#/");
  onRouteChange();

  getBootstrap()
    .then(fillSidebar)
    .catch(() => {
      const label = $("index-title");
      if (label) label.textContent = text("Catálogo no disponible", "Catalogue unavailable");
      $("sidebar-playlists")?.replaceChildren();
    });

  window.addEventListener("pagehide", () => player.persistPosition());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) player.persistPosition();
  });

  // The lyrics panel is the point of a lyrics-first player: open it on desktop.
  if (window.innerWidth >= 1240) setLyricsOpen(true);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot, { once: true });
} else {
  boot();
}
