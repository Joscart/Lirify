import { api } from "./api";
import { emit, on } from "./bus";
import { escapeHtml } from "./format";
import { player } from "./player";
import type { LyricLine, LyricsPayload, Track } from "./types";

interface RenderedWord {
  el: HTMLElement;
  start: number;
  end: number;
}

interface RenderedLine {
  el: HTMLElement;
  words: RenderedWord[];
  start: number;
  end: number;
}

interface LyricsView {
  mount: HTMLElement;
  scroller: HTMLElement;
  lines: RenderedLine[];
  active: number;
  wordIndex: number;
}

const OFFSET_KEY = "lirify.lyrics.offset.v1";
const cache = new Map<string, LyricsPayload>();

function parseOffset(): number {
  const stored = Number(localStorage.getItem(OFFSET_KEY));
  return Number.isFinite(stored) ? stored : 0;
}

class LyricsController {
  data: LyricsPayload | null = null;
  offset = parseOffset();
  private views: LyricsView[] = [];
  private panelMount: HTMLElement | null = null;
  private theaterMount: HTMLElement | null = null;
  private loading = false;
  private token = 0;
  private lastUserScroll = 0;
  private following = true;
  private active = -1;
  private starts: number[] = [];
  private currentTrack: Track | null = null;
  private emptyEls: HTMLElement[] = [];

  init(): void {
    this.panelMount = document.getElementById("lyrics-list");
    this.theaterMount = document.getElementById("theater-lyrics");
    const panelBody = document.getElementById("lyrics-body");
    const theaterBody = document.getElementById("theater-lyrics-body");
    if (this.panelMount && panelBody) {
      this.views.push({ mount: this.panelMount, scroller: panelBody, lines: [], active: -1, wordIndex: -1 });
      panelBody.addEventListener("wheel", () => this.noteUserScroll(), { passive: true });
      panelBody.addEventListener("touchstart", () => this.noteUserScroll(), { passive: true });
    }
    if (this.theaterMount && theaterBody) {
      this.views.push({ mount: this.theaterMount, scroller: theaterBody, lines: [], active: -1, wordIndex: -1 });
      theaterBody.addEventListener("wheel", () => this.noteUserScroll(), { passive: true });
    }
    const empty = document.getElementById("lyrics-empty");
    if (empty) this.emptyEls.push(empty);
    const theaterEmpty = document.getElementById("theater-lyrics-empty");
    if (theaterEmpty) this.emptyEls.push(theaterEmpty);

    this.panelMount?.addEventListener("click", (event) => this.onLineClick(event));
    this.theaterMount?.addEventListener("click", (event) => this.onLineClick(event));

    on("track", (track: Track) => void this.load(track));
    on("seek", () => {
      this.active = -1;
      this.tick(true);
    });
    this.updateOffsetLabel();
  }

  private noteUserScroll(): void {
    this.lastUserScroll = Date.now();
    this.following = false;
    emit("lyrics:follow", false);
  }

  follow(): void {
    this.following = true;
    this.lastUserScroll = 0;
    emit("lyrics:follow", true);
    this.scrollToActive(true);
  }

  private onLineClick(event: Event): void {
    const target = (event.target as HTMLElement).closest(".lyric-line") as HTMLElement | null;
    if (!target) return;
    const time = Number(target.dataset.t);
    if (!Number.isFinite(time)) return;
    player.seek(Math.max(0, time - this.offset));
    if (!player.state.playing) void player.play();
    this.follow();
  }

  setOffset(seconds: number): void {
    this.offset = Math.round(Math.max(-15, Math.min(15, seconds)) * 100) / 100;
    localStorage.setItem(OFFSET_KEY, String(this.offset));
    this.updateOffsetLabel();
    this.active = -1;
    this.tick(true);
  }

  adjustOffset(delta: number): void {
    this.setOffset(this.offset + delta);
  }

  private updateOffsetLabel(): void {
    const label = document.getElementById("lyrics-offset");
    if (label) label.textContent = `${this.offset > 0 ? "+" : ""}${this.offset.toFixed(1)}s`;
  }

  async load(track: Track): Promise<void> {
    this.currentTrack = track;
    const token = ++this.token;
    this.data = null;
    this.active = -1;
    this.starts = [];
    this.following = true;
    emit("lyrics:follow", true);

    const titleEl = document.getElementById("lyrics-title");
    const artistEl = document.getElementById("lyrics-artist");
    const sourceEl = document.getElementById("lyrics-source");
    const syncEl = document.getElementById("lyrics-sync");
    const theaterTitle = document.getElementById("theater-title");
    const theaterArtist = document.getElementById("theater-artist");
    if (titleEl) titleEl.textContent = track.title;
    if (artistEl) artistEl.textContent = track.artist;
    if (theaterTitle) theaterTitle.textContent = track.title;
    if (theaterArtist) theaterArtist.textContent = track.artist;
    if (sourceEl) sourceEl.textContent = track.lyrics_source || "lyrics";
    if (syncEl) {
      syncEl.textContent = track.synced_lyrics ? "synced" : "unsynced";
      syncEl.dataset.state = track.synced_lyrics ? "synced" : "plain";
    }
    this.showLoading();

    const cached = cache.get(track.id);
    if (cached) {
      this.apply(cached);
      return;
    }
    try {
      const payload = await api.lyrics(track.id);
      if (token !== this.token) return;
      if (cache.size > 120) cache.clear();
      cache.set(track.id, payload);
      this.apply(payload);
    } catch (error) {
      if (token !== this.token) return;
      this.loading = false;
      this.renderEmpty("Lyrics could not be loaded for this track.");
      emit("lyrics:loaded", null);
    }
  }

  private showLoading(): void {
    this.loading = true;
    this.emptyEls.forEach((el) => (el.hidden = true));
    for (const view of this.views) {
      view.active = -1;
      view.wordIndex = -1;
      view.lines = [];
      view.mount.innerHTML = Array.from({ length: 7 })
        .map(
          (_, index) =>
            `<div class="lyric-skeleton" style="width:${52 + ((index * 17) % 44)}%"></div>`,
        )
        .join("");
      view.mount.classList.add("is-loading");
    }
  }

  private renderEmpty(message: string): void {
    for (const view of this.views) {
      view.mount.innerHTML = "";
      view.mount.classList.remove("is-loading");
    }
    this.emptyEls.forEach((el) => {
      el.hidden = false;
      const text = el.querySelector("[data-empty-text]");
      if (text) text.textContent = message;
    });
    emit("lyrics:loaded", null);
  }

  private apply(payload: LyricsPayload): void {
    this.loading = false;
    this.data = payload;
    this.starts = payload.lines
      .filter((line) => line.t !== null)
      .map((line) => line.t as number);
    this.active = -1;

    const sourceEl = document.getElementById("lyrics-source");
    const syncEl = document.getElementById("lyrics-sync");
    if (sourceEl) sourceEl.textContent = payload.source || "lyrics";
    if (syncEl) {
      syncEl.textContent = payload.synced ? "synced" : "unsynced";
      syncEl.dataset.state = payload.synced ? "synced" : "plain";
    }

    if (!payload.lines?.length) {
      this.renderEmpty(
        payload.source === "instrumental"
          ? "This track is instrumental — no lyrics were found."
          : "No lyrics are indexed for this track yet.",
      );
      return;
    }
    this.emptyEls.forEach((el) => (el.hidden = true));

    for (const view of this.views) {
      view.mount.classList.remove("is-loading");
      view.mount.classList.toggle("is-synced", payload.synced);
      view.mount.innerHTML = "";
      view.lines = [];
      view.active = -1;
      view.wordIndex = -1;
      const fragment = document.createDocumentFragment();
      payload.lines.forEach((line, index) => {
        const rendered = this.renderLine(line, index, payload);
        view.lines.push(rendered);
        fragment.appendChild(rendered.el);
      });
      view.mount.appendChild(fragment);
      view.scroller.scrollTop = 0;
    }
    this.tick(true);
    emit("lyrics:loaded", payload);
  }

  private renderLine(line: LyricLine, index: number, payload: LyricsPayload): RenderedLine {
    const element = document.createElement("button");
    element.type = "button";
    element.className = "lyric-line";
    element.style.setProperty("--i", String(Math.min(index, 24)));
    if (line.t === null) {
      element.classList.add("is-unsynced");
      element.innerHTML = `<span class="lyr-word"><span class="lyr-word__text">${escapeHtml(line.text)}</span></span>`;
      return { el: element, words: [], start: 0, end: 0 };
    }
    element.dataset.t = String(line.t);
    const nextLine = payload.lines[index + 1];
    const end = nextLine?.t !== null && nextLine?.t !== undefined ? nextLine.t : line.t + 4.5;
    const words: RenderedWord[] = [];
    const text = line.text || "♪";
    const parts = text.split(/(\s+)/).filter((part) => part.trim().length);

    if (line.words?.length) {
      const explicit = line.words;
      explicit.forEach((word, wordIndex) => {
        const wordEnd = explicit[wordIndex + 1]?.t ?? end;
        const span = document.createElement("span");
        span.className = "lyr-word";
        span.innerHTML = `<span class="lyr-word__text">${escapeHtml(word.text)}</span>`;
        element.appendChild(span);
        element.appendChild(document.createTextNode(" "));
        words.push({ el: span, start: word.t, end: wordEnd });
      });
    } else {
      const totalChars = parts.reduce((sum, part) => sum + part.length + 1, 0) || 1;
      let cursor = line.t;
      parts.forEach((part) => {
        const duration = ((part.length + 1) / totalChars) * Math.max(0.8, end - line.t);
        const span = document.createElement("span");
        span.className = "lyr-word";
        span.innerHTML = `<span class="lyr-word__text">${escapeHtml(part)}</span>`;
        element.appendChild(span);
        element.appendChild(document.createTextNode(" "));
        words.push({ el: span, start: cursor, end: cursor + duration });
        cursor += duration;
      });
    }
    return { el: element, words, start: line.t, end };
  }

  tick(force = false): void {
    if (!this.data?.synced || !this.data.lines.length) return;
    const time = player.alignedTime() + this.offset;
    const index = this.activeAt(time);
    for (const view of this.views) {
      if (!view.lines.length) continue;
      if (index !== view.active) {
        this.setActive(view, index);
      }
      if (index >= 0) this.updateWords(view, index, time);
    }
    if (force) {
      for (const view of this.views) this.updateWords(view, index, time);
    }
  }

  private activeAt(time: number): number {
    const starts = this.starts;
    if (!starts.length) return -1;
    if (time < starts[0]) return -1;
    let low = 0;
    let high = starts.length - 1;
    while (low < high) {
      const mid = Math.ceil((low + high) / 2);
      if (starts[mid] <= time) low = mid;
      else high = mid - 1;
    }
    return low;
  }

  private setActive(view: LyricsView, index: number): void {
    const previous = view.active;
    view.active = index;
    view.wordIndex = -1;
    if (previous >= 0 && view.lines[previous]) {
      const line = view.lines[previous];
      line.el.classList.remove("is-active");
      line.el.classList.add("is-past");
      for (const word of line.words) {
        word.el.classList.add("is-sung");
        word.el.classList.remove("is-current");
      }
    }
    if (index >= 0 && view.lines[index]) {
      const line = view.lines[index];
      line.el.classList.remove("is-past");
      line.el.classList.add("is-active");
      for (const word of line.words) {
        word.el.classList.remove("is-sung", "is-current");
        word.el.style.removeProperty("--wp");
      }
      if (line.start >= 0) this.scrollToActive(false, view);
    }
    if (this.active !== index) {
      this.active = index;
      emit("lyrics:active", index);
    }
    // Mark the lines around the active one so the fade reads as a gradient.
    view.lines.forEach((line, lineIndex) => {
      line.el.classList.toggle("is-near", Math.abs(lineIndex - index) === 1);
    });
  }

  private updateWords(view: LyricsView, index: number, time: number): void {
    const line = view.lines[index];
    if (!line || !line.words.length) return;
    let wordIndex = -1;
    for (let i = 0; i < line.words.length; i++) {
      if (line.words[i].start <= time) wordIndex = i;
      else break;
    }
    if (wordIndex !== view.wordIndex) {
      view.wordIndex = wordIndex;
      line.words.forEach((word, i) => {
        word.el.classList.toggle("is-sung", i < wordIndex);
        word.el.classList.toggle("is-current", i === wordIndex);
        if (i !== wordIndex) word.el.style.removeProperty("--wp");
      });
    }
    const word = line.words[wordIndex];
    if (word) {
      const progress = Math.max(
        0,
        Math.min(1, (time - word.start) / Math.max(0.08, word.end - word.start)),
      );
      word.el.style.setProperty("--wp", progress.toFixed(3));
    }
  }

  private scrollToActive(smooth: boolean, only?: LyricsView): void {
    if (!this.following) return;
    if (!smooth && Date.now() - this.lastUserScroll < 1800) return;
    const views = only ? [only] : this.views;
    for (const view of views) {
      if (view.active < 0) continue;
      const line = view.lines[view.active];
      if (!line) continue;
      const top =
        line.el.offsetTop - view.scroller.clientHeight / 2 + line.el.clientHeight / 2;
      try {
        view.scroller.scrollTo({ top: Math.max(0, top), behavior: smooth ? "smooth" : "auto" });
      } catch {
        view.scroller.scrollTop = Math.max(0, top);
      }
    }
  }

  hasLyrics(): boolean {
    return !!this.data?.lines.length;
  }

  isLoading(): boolean {
    return this.loading;
  }

  currentTrackId(): Track | null {
    return this.currentTrack;
  }
}

export const lyrics = new LyricsController();
