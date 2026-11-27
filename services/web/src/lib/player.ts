import { api } from "./api";
import { emit } from "./bus";
import { clamp } from "./format";
import type { SessionPayload, StreamPayload, Track } from "./types";

type Mode = "audio" | "video";
type Repeat = "off" | "all" | "one";

export interface PlayerState {
  queue: Track[];
  order: number[];
  orderIndex: number;
  current: Track | null;
  playing: boolean;
  loading: boolean;
  buffering: boolean;
  error: string | null;
  position: number;
  duration: number;
  volume: number;
  muted: boolean;
  shuffle: boolean;
  repeat: Repeat;
  mode: Mode;
  theater: boolean;
  mini: boolean;
  automix: boolean;
  usingIframe: boolean;
  session: SessionPayload | null;
}

const STORE_KEY = "lirify.player.v1";
const VOLUME_KEY = "lirify.volume.v1";

declare global {
  interface Window {
    YT?: any;
    onYouTubeIframeAPIReady?: () => void;
    __lirifyYtPromise?: Promise<any>;
  }
}

function loadYouTubeApi(): Promise<any> {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (window.__lirifyYtPromise) return window.__lirifyYtPromise;
  window.__lirifyYtPromise = new Promise((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      previous?.();
      resolve(window.YT);
    };
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    script.async = true;
    script.onerror = () => reject(new Error("The YouTube IFrame API could not be loaded."));
    document.head.appendChild(script);
    window.setTimeout(() => {
      if (window.YT?.Player) resolve(window.YT);
    }, 8000);
  });
  return window.__lirifyYtPromise;
}

class YouTubeBridge {
  private player: any = null;
  private host: HTMLElement;
  private token = 0;
  private resizeObserver: ResizeObserver | null = null;
  ready = false;
  private onPosition?: (seconds: number, duration: number) => void;
  private onState?: (state: "playing" | "paused" | "ended") => void;
  private onError?: (message: string) => void;

  constructor(host: HTMLElement) {
    this.host = host;
  }

  private fit(): void {
    if (!this.player) return;
    const rect = this.host.getBoundingClientRect();
    const width = Math.max(320, Math.round(rect.width));
    const height = Math.max(180, Math.round(rect.height));
    try {
      this.player.setSize?.(width, height);
    } catch {
      /* not ready */
    }
    const frame = this.host.querySelector("iframe");
    if (frame) {
      frame.style.width = "100%";
      frame.style.height = "100%";
      frame.style.position = "absolute";
      frame.style.inset = "0";
    }
  }

  async load(
    videoId: string,
    startAt: number,
    handlers: {
      onPosition: (seconds: number, duration: number) => void;
      onState: (state: "playing" | "paused" | "ended") => void;
      onError: (message: string) => void;
    },
    volume = 0.85,
    muted = false,
  ): Promise<void> {
    const token = ++this.token;
    this.onPosition = handlers.onPosition;
    this.onState = handlers.onState;
    this.onError = handlers.onError;
    this.destroy();
    const YT = await loadYouTubeApi();
    if (token !== this.token) return;

    const mount = document.createElement("div");
    mount.className = "yt-frame-mount";
    this.host.innerHTML = "";
    this.host.appendChild(mount);

    await new Promise<void>((resolve) => {
      this.player = new YT.Player(mount, {
        videoId,
        host: "https://www.youtube-nocookie.com",
        playerVars: {
          autoplay: 1,
          controls: 0,
          disablekb: 1,
          modestbranding: 1,
          rel: 0,
          playsinline: 1,
          iv_load_policy: 3,
          origin: location.origin,
          start: Math.max(0, Math.floor(startAt || 0)),
        },
        events: {
          onReady: (event: any) => {
            if (token !== this.token) return;
            this.ready = true;
            try {
              event.target.setVolume(Math.round(volume * 100));
              if (muted) event.target.mute();
              if (startAt > 0) event.target.seekTo(startAt, true);
              event.target.playVideo();
            } catch {
              /* player not ready enough */
            }
            this.fit();
            this.resizeObserver?.disconnect();
            this.resizeObserver = new ResizeObserver(() => this.fit());
            this.resizeObserver.observe(this.host);
            window.setTimeout(() => this.fit(), 250);
            resolve();
          },
          onStateChange: (event: any) => {
            if (token !== this.token) return;
            const YTState = window.YT?.PlayerState;
            if (!YTState) return;
            if (event.data === YTState.PLAYING) this.onState?.("playing");
            else if (event.data === YTState.PAUSED) this.onState?.("paused");
            else if (event.data === YTState.ENDED) this.onState?.("ended");
          },
          onError: () => {
            if (token === this.token) this.onError?.("YouTube refused to play this video.");
          },
        },
      });
    });
  }

  position(): number {
    try {
      return this.player?.getCurrentTime?.() || 0;
    } catch {
      return 0;
    }
  }

  duration(): number {
    try {
      return this.player?.getDuration?.() || 0;
    } catch {
      return 0;
    }
  }

  play(): void {
    try {
      this.player?.playVideo?.();
    } catch {
      /* noop */
    }
  }

  pause(): void {
    try {
      this.player?.pauseVideo?.();
    } catch {
      /* noop */
    }
  }

  seek(seconds: number): void {
    try {
      this.player?.seekTo?.(Math.max(0, seconds), true);
    } catch {
      /* noop */
    }
  }

  setVolume(volume: number): void {
    try {
      this.player?.setVolume?.(Math.round(clamp(volume, 0, 1) * 100));
    } catch {
      /* noop */
    }
  }

  setMuted(muted: boolean): void {
    try {
      if (muted) this.player?.mute?.();
      else this.player?.unMute?.();
    } catch {
      /* noop */
    }
  }

  destroy(): void {
    this.ready = false;
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    try {
      this.player?.destroy?.();
    } catch {
      /* noop */
    }
    this.player = null;
    this.host.innerHTML = "";
  }
}

export class PlayerEngine {
  state: PlayerState = {
    queue: [],
    order: [],
    orderIndex: -1,
    current: null,
    playing: false,
    loading: false,
    buffering: false,
    error: null,
    position: 0,
    duration: 0,
    volume: 0.8,
    muted: false,
    shuffle: false,
    repeat: "off",
    mode: "audio",
    theater: false,
    mini: false,
    automix: true,
    usingIframe: false,
    session: null,
  };

  private audio!: HTMLAudioElement;
  private videoHost: HTMLElement | null = null;
  private fallbackHost: HTMLElement | null = null;
  private bridge: YouTubeBridge | null = null;
  private bridgeTimer: number | undefined;
  private streams = new Map<string, { proxy: string; at: number; duration: number }>();
  private pendingStreams = new Map<string, Promise<StreamPayload>>();
  private preloader: HTMLAudioElement | null = null;
  private playToken = 0;
  private sessionTimer: number | undefined;
  private sessionInFlight = false;
  private likes = new Set<string>();
  private started = false;
  private tickRaf = 0;
  private lastTrackId = "";

  init(): void {
    if (this.started) return;
    this.started = true;
    this.audio = document.getElementById("audio") as HTMLAudioElement;
    this.videoHost = document.getElementById("yt-stage");
    this.fallbackHost = document.getElementById("yt-audio");
    this.audio.preload = "auto";
    this.audio.crossOrigin = "anonymous";

    const storedVolume = Number(localStorage.getItem(VOLUME_KEY));
    if (Number.isFinite(storedVolume) && storedVolume >= 0) {
      this.state.volume = clamp(storedVolume, 0, 1);
    }
    this.audio.volume = this.state.volume;

    this.audio.addEventListener("play", () => {
      this.state.playing = true;
      this.state.buffering = false;
      this.postSession();
      emit("playback", this.state);
    });
    this.audio.addEventListener("pause", () => {
      this.state.playing = false;
      this.postSession();
      emit("playback", this.state);
    });
    this.audio.addEventListener("waiting", () => {
      this.state.buffering = true;
      emit("playback", this.state);
    });
    this.audio.addEventListener("playing", () => {
      this.state.buffering = false;
      this.state.loading = false;
      emit("playback", this.state);
    });
    this.audio.addEventListener("durationchange", () => {
      if (Number.isFinite(this.audio.duration)) this.state.duration = this.audio.duration;
    });
    this.audio.addEventListener("loadedmetadata", () => {
      if (Number.isFinite(this.audio.duration)) {
        this.state.duration = this.audio.duration;
        const current = this.state.current;
        if (current) current.duration = this.audio.duration;
      }
      emit("playback", this.state);
    });
    this.audio.addEventListener("timeupdate", () => {
      if (!this.state.usingIframe) this.state.position = this.audio.currentTime;
    });
    this.audio.addEventListener("ended", () => this.handleEnded());
    this.audio.addEventListener("error", () => this.handleAudioError());

    this.loadLikes();
    this.restore();
    this.sessionTimer = window.setInterval(() => this.postSession(), 1200);
    this.updateMediaSessionActions();
    this.startTick();
  }

  // -- queue ---------------------------------------------------------------

  get current(): Track | null {
    const index = this.state.order[this.state.orderIndex];
    return index === undefined ? null : this.state.queue[index] || null;
  }

  setQueue(queue: Track[], startIndex = 0, video = false): void {
    this.state.queue = [...queue];
    this.state.order = queue.map((_, index) => index);
    this.state.orderIndex = clamp(startIndex, 0, Math.max(0, queue.length - 1));
    if (this.state.shuffle) this.rebuildShuffle(this.state.order[this.state.orderIndex]);
    this.persist();
    emit("queue", this.state);
    if (video) this.state.mode = "video";
  }

  async playTrack(track: Track, queue?: Track[], options?: { video?: boolean; at?: number }): Promise<void> {
    if (!this.audio) this.init();
    let startIndex = this.state.orderIndex;
    if (queue && queue.length) {
      startIndex = Math.max(0, queue.findIndex((item) => item.id === track.id));
      this.setQueue(queue, startIndex, !!options?.video);
    } else if (!this.state.queue.some((item) => item.id === track.id)) {
      this.setQueue([track], 0, !!options?.video);
    } else if (this.current?.id !== track.id) {
      const baseIndex = this.state.queue.findIndex((item) => item.id === track.id);
      const orderPos = this.state.order.indexOf(baseIndex);
      this.state.orderIndex = orderPos >= 0 ? orderPos : 0;
    }

    if (options?.video) {
      this.state.mode = "video";
      this.state.theater = true;
      this.state.current = track;
      this.state.position = options.at || 0;
      this.state.duration = track.duration || 0;
      this.state.loading = true;
      emit("track", track);
      emit("theater", true);
      emit("playback", this.state);
      this.persist();
      requestAnimationFrame(() => void this.startVideoBridge());
      return;
    }

    await this.loadAudioTrack(track, options?.at || 0);
  }

  async startVideoBridge(): Promise<void> {
    const track = this.current;
    if (!track || !this.videoHost) return;
    this.audio.pause();
    this.state.usingIframe = true;
    this.state.loading = true;
    this.bridge = new YouTubeBridge(this.videoHost);
    try {
      await this.bridge.load(
        track.video_id,
        this.state.position,
        {
          onPosition: (seconds, duration) => {
            this.state.position = seconds;
            if (duration) {
              this.state.duration = duration;
              track.duration = duration;
            }
            this.state.playing = true;
            this.state.loading = false;
          },
          onState: (value) => {
            this.state.playing = value === "playing";
            if (value === "ended") this.handleEnded();
            emit("playback", this.state);
          },
          onError: (message) => this.failVideo(message),
        },
        this.state.volume,
        this.state.muted,
      );
      this.state.loading = false;
      this.clearBridgeTimer();
      this.bridgeTimer = window.setInterval(() => {
        if (!this.bridge || this.state.mode !== "video") return;
        const seconds = this.bridge.position();
        const duration = this.bridge.duration();
        if (seconds) this.state.position = seconds;
        if (duration) this.state.duration = duration;
        emit("playback", this.state);
      }, 250);
      emit("playback", this.state);
      this.postSession();
    } catch (error) {
      this.failVideo(error instanceof Error ? error.message : "Video playback failed.");
    }
  }

  private failVideo(message: string): void {
    this.state.error = message;
    this.state.loading = false;
    this.state.usingIframe = false;
    this.state.mode = "audio";
    this.state.theater = false;
    this.bridge?.destroy();
    this.bridge = null;
    this.clearBridgeTimer();
    emit("theater", false);
    emit("playback", this.state);
    emit("error", message);
    const track = this.current;
    if (track) void this.loadAudioTrack(track, this.state.position);
  }

  stopVideoBridge(): void {
    this.bridge?.destroy();
    this.bridge = null;
    this.clearBridgeTimer();
    this.state.usingIframe = false;
  }

  private clearBridgeTimer(): void {
    if (this.bridgeTimer) {
      window.clearInterval(this.bridgeTimer);
      this.bridgeTimer = undefined;
    }
  }

  async loadAudioTrack(track: Track, at = 0): Promise<void> {
    const token = ++this.playToken;
    this.stopVideoBridge();
    this.state.mode = "audio";
    this.state.current = track;
    this.state.error = null;
    this.state.loading = true;
    this.state.buffering = true;
    this.state.position = at;
    this.state.duration = track.duration || 0;
    this.lastTrackId = track.id;
    emit("track", track);
    emit("playback", this.state);
    this.persist();
    this.updateMediaSession(track);
    this.warmNext();

    try {
      const stream = await this.ensureStream(track);
      if (token !== this.playToken) return;
      const url = api.proxy(track.id);
      this.audio.src = url;
      this.audio.load();
      const onMetadata = () => {
        this.audio.removeEventListener("loadedmetadata", onMetadata);
        if (token !== this.playToken) return;
        if (at > 0) {
          try {
            this.audio.currentTime = at;
          } catch {
            /* metadata not seekable yet */
          }
        }
      };
      this.audio.addEventListener("loadedmetadata", onMetadata);
      try {
        await this.audio.play();
      } catch (error) {
        if (token !== this.playToken) return;
        if ((error as DOMException)?.name === "AbortError") return;
        this.state.playing = false;
        this.state.loading = false;
        this.state.buffering = false;
        emit("playback", this.state);
        emit("error", "Autoplay was blocked — press play to start.");
      }
      if (token !== this.playToken) return;
      this.state.loading = false;
      emit("playback", this.state);
      this.postSession();
    } catch (error) {
      if (token !== this.playToken) return;
      this.state.loading = false;
      this.state.buffering = false;
      this.state.error = error instanceof Error ? error.message : "Stream unavailable.";
      emit("playback", this.state);
      emit("error", this.state.error);
      this.useIframeFallback("Stream unavailable — switching to YouTube playback.");
    }
  }

  private handleAudioError(): void {
    if (!this.state.current || this.state.loading) return;
    this.useIframeFallback("The audio stream dropped — falling back to YouTube.");
  }

  async useIframeFallback(reason?: string): Promise<void> {
    const track = this.current;
    if (!track || !this.fallbackHost || this.state.usingIframe) return;
    this.state.usingIframe = true;
    this.state.loading = true;
    if (reason) emit("toast", reason);
    this.bridge = new YouTubeBridge(this.fallbackHost);
    try {
      await this.bridge.load(
        track.video_id,
        this.state.position,
        {
          onPosition: (seconds, duration) => {
            this.state.position = seconds;
            if (duration) this.state.duration = duration;
            this.state.playing = true;
            this.state.loading = false;
          },
          onState: (value) => {
            this.state.playing = value === "playing";
            if (value === "ended") this.handleEnded();
            emit("playback", this.state);
          },
          onError: (message) => {
            this.state.error = message;
            this.state.loading = false;
            emit("playback", this.state);
            emit("error", message);
          },
        },
        this.state.volume,
        this.state.muted,
      );
      this.state.loading = false;
      emit("playback", this.state);
      this.clearBridgeTimer();
      this.bridgeTimer = window.setInterval(() => {
        if (!this.bridge) return;
        const seconds = this.bridge.position();
        const duration = this.bridge.duration();
        if (seconds) this.state.position = seconds;
        if (duration) this.state.duration = duration;
        emit("playback", this.state);
      }, 300);
    } catch {
      this.state.loading = false;
      emit("playback", this.state);
    }
  }

  private ensureStream(track: Track): Promise<StreamPayload> {
    const cached = this.streams.get(track.id);
    if (cached && Date.now() - cached.at < 80 * 60 * 1000) {
      this.learnDuration(track, cached.duration);
      return Promise.resolve({
        video_id: track.id,
        kind: "audio",
        proxy_url: cached.proxy,
        expires_at: cached.at + 80 * 60 * 1000,
        duration: cached.duration,
        resolver: "cache",
      });
    }
    const pending = this.pendingStreams.get(track.id);
    if (pending) return pending;
    const promise = api
      .stream(track.id, true)
      .then((payload) => {
        if (payload.available === false || !payload.proxy_url) {
          this.pendingStreams.delete(track.id);
          throw new Error(payload.error || "Stream unavailable.");
        }
        this.streams.set(track.id, {
          proxy: payload.proxy_url,
          at: Date.now(),
          duration: payload.duration || track.duration,
        });
        this.pendingStreams.delete(track.id);
        this.learnDuration(track, payload.duration);
        return payload;
      })
      .catch((error) => {
        this.pendingStreams.delete(track.id);
        throw error;
      });
    this.pendingStreams.set(track.id, promise);
    return promise;
  }

  private learnDuration(track: Track, duration?: number): void {
    if (!duration) return;
    track.duration = duration;
    track.duration_estimated = false;
    if (this.state.current?.id === track.id && this.state.mode === "audio") {
      this.state.duration = duration;
    }
    emit("duration", { id: track.id, duration });
  }

  private warmNext(): void {
    const next = this.peekNext();
    if (!next) return;
    if (this.streams.has(next.id)) {
      this.preload(next);
      return;
    }
    api
      .stream(next.id, true)
      .then((payload) => {
        if (payload.available === false || !payload.proxy_url) return;
        this.streams.set(next.id, {
          proxy: payload.proxy_url,
          at: Date.now(),
          duration: payload.duration || next.duration,
        });
        this.learnDuration(next, payload.duration);
        // Only warm the byte cache once a stream is known to resolve, or the
        // preloader's proxy request turns an unavailable track into a 502 in
        // the console on every play.
        this.preload(next);
      })
      .catch(() => {});
  }

  /** Warm the browser's byte cache for the next track without playing it. */
  private preload(track: Track): void {
    if (!this.preloader) {
      this.preloader = new Audio();
      this.preloader.preload = "auto";
      this.preloader.volume = 0;
    }
    const url = api.proxy(track.id);
    if (this.preloader.src !== url) {
      this.preloader.src = url;
      try {
        this.preloader.load();
      } catch {
        /* noop */
      }
    }
  }

  peekNext(): Track | null {
    let position = this.state.orderIndex + 1;
    if (position >= this.state.order.length) {
      if (this.state.repeat !== "all") return null;
      position = 0;
    }
    const index = this.state.order[position];
    return index === undefined ? null : this.state.queue[index] || null;
  }

  // -- transport -----------------------------------------------------------

  async play(): Promise<void> {
    if (this.state.usingIframe && this.bridge) {
      this.bridge.play();
      return;
    }
    if (!this.current) {
      if (this.state.queue.length) {
        const track = this.state.queue[this.state.order[this.state.orderIndex < 0 ? 0 : this.state.orderIndex]];
        if (track) await this.loadAudioTrack(track);
      }
      return;
    }
    if (this.state.mode === "video") {
      if (!this.bridge) await this.startVideoBridge();
      else this.bridge.play();
      return;
    }
    if (!this.audio.src) {
      await this.loadAudioTrack(this.current, this.state.position);
      return;
    }
    try {
      await this.audio.play();
    } catch {
      emit("error", "Playback was blocked by the browser.");
    }
  }

  pause(): void {
    if (this.state.usingIframe && this.bridge) {
      this.bridge.pause();
      this.state.playing = false;
      this.postSession();
      emit("playback", this.state);
      return;
    }
    if (this.state.mode === "video" && this.bridge) {
      this.bridge.pause();
      this.state.playing = false;
      this.postSession();
      emit("playback", this.state);
      return;
    }
    this.audio.pause();
  }

  toggle(): void {
    if (this.state.playing) this.pause();
    else void this.play();
  }

  async next(auto = false): Promise<void> {
    if (!this.state.order.length) return;
    if (auto && this.state.repeat === "one") {
      this.seek(0);
      void this.play();
      return;
    }
    let nextPos = this.state.orderIndex + 1;
    if (nextPos >= this.state.order.length) {
      const appended = auto ? await this.appendAutomix() : false;
      if (this.state.repeat === "all" || appended) {
        nextPos = appended ? this.state.orderIndex + 1 : 0;
      } else {
        this.pause();
        this.seek(0);
        return;
      }
    }
    this.jumpToOrder(nextPos);
  }

  prev(): void {
    if (this.current && this.state.position > 4) {
      this.seek(0);
      return;
    }
    if (this.state.orderIndex > 0) this.jumpToOrder(this.state.orderIndex - 1);
    else this.seek(0);
  }

  jumpTo(orderPosition: number): void {
    this.jumpToOrder(orderPosition);
  }

  private jumpToOrder(position: number): void {
    if (position < 0 || position >= this.state.order.length) return;
    this.state.orderIndex = position;
    const track = this.current;
    if (!track) return;
    this.state.position = 0;
    if (this.state.mode === "video") {
      this.stopVideoBridge();
      this.state.theater = true;
      emit("track", track);
      emit("playback", this.state);
      void this.startVideoBridge();
    } else {
      void this.loadAudioTrack(track, 0);
    }
  }

  seek(seconds: number): void {
    const duration = this.state.duration || this.current?.duration || 0;
    const target = clamp(seconds, 0, duration || 1e6);
    this.state.position = target;
    if (this.state.usingIframe && this.bridge) this.bridge.seek(target);
    else if (this.state.mode === "audio") {
      try {
        this.audio.currentTime = target;
      } catch {
        /* no media yet */
      }
    }
    emit("seek", target);
    emit("playback", this.state);
    this.postSession();
  }

  seekBy(delta: number): void {
    this.seek(this.state.position + delta);
  }

  setVolume(volume: number): void {
    this.state.volume = clamp(volume, 0, 1);
    this.state.muted = this.state.volume === 0 ? true : false;
    this.audio.volume = this.state.volume;
    this.audio.muted = this.state.muted;
    this.bridge?.setVolume(this.state.volume);
    this.bridge?.setMuted(this.state.muted);
    localStorage.setItem(VOLUME_KEY, String(this.state.volume));
    emit("volume", this.state);
  }

  toggleMute(): void {
    this.state.muted = !this.state.muted;
    this.audio.muted = this.state.muted;
    this.bridge?.setMuted(this.state.muted);
    emit("volume", this.state);
  }

  setMode(mode: Mode): void {
    if (mode === this.state.mode) return;
    if (mode === "video") {
      this.state.mode = "video";
      this.state.theater = true;
      emit("theater", true);
      emit("playback", this.state);
      // The theater element must be visible before the iframe starts.
      requestAnimationFrame(() => void this.startVideoBridge());
    } else {
      this.stopVideoBridge();
      this.state.mode = "audio";
      const at = this.state.position;
      const track = this.current;
      if (track) void this.loadAudioTrack(track, at);
    }
  }

  closeVideo(): void {
    const at = this.state.position;
    this.stopVideoBridge();
    this.state.theater = false;
    this.state.mode = "audio";
    emit("theater", false);
    emit("playback", this.state);
    const track = this.current;
    if (track) void this.loadAudioTrack(track, at);
  }

  // -- queue extras --------------------------------------------------------

  playNext(track: Track): void {
    const exists = this.state.queue.findIndex((item) => item.id === track.id);
    let index = exists;
    if (index < 0) {
      index = this.state.queue.push(track) - 1;
    }
    const filtered = this.state.order.filter((value) => value !== index);
    const insertAt = Math.min(filtered.length, this.state.orderIndex + 1);
    filtered.splice(insertAt, 0, index);
    this.state.order = filtered;
    // Keep the pointer on the currently playing track after the reorder.
    const currentIndex = this.state.order.indexOf(
      this.state.queue.findIndex((item) => item.id === this.current?.id),
    );
    if (currentIndex >= 0) this.state.orderIndex = currentIndex;
    this.persist();
    emit("queue", this.state);
    emit("toast", `Playing next: ${track.title}`);
  }

  addToQueue(track: Track): void {
    const exists = this.state.queue.findIndex((item) => item.id === track.id);
    let index = exists;
    if (index < 0) index = this.state.queue.push(track) - 1;
    if (!this.state.order.includes(index)) this.state.order.push(index);
    this.persist();
    emit("queue", this.state);
    emit("toast", `Added to queue: ${track.title}`);
  }

  removeFromQueue(orderPosition: number): void {
    if (orderPosition < 0 || orderPosition >= this.state.order.length) return;
    if (orderPosition === this.state.orderIndex) return;
    const [removed] = this.state.order.splice(orderPosition, 1);
    if (orderPosition < this.state.orderIndex) this.state.orderIndex -= 1;
    this.state.queue = this.state.queue.filter((_, index) => index !== removed);
    this.state.order = this.state.order.map((value) => (value > removed ? value - 1 : value));
    this.persist();
    emit("queue", this.state);
  }

  clearUpcoming(): void {
    const currentBase = this.state.queue.findIndex((item) => item.id === this.current?.id);
    if (currentBase < 0) return;
    const currentTrack = this.state.queue[currentBase];
    this.state.queue = [currentTrack];
    this.state.order = [0];
    this.state.orderIndex = 0;
    this.persist();
    emit("queue", this.state);
  }

  async appendAutomix(): Promise<boolean> {
    if (!this.state.automix) return false;
    const seed = this.current;
    if (!seed) return false;
    try {
      const radio = await api.radio(seed.id, 12);
      const known = new Set(this.state.queue.map((item) => item.id));
      const additions = radio.recommendations.filter((item) => !known.has(item.id)).slice(0, 8);
      if (!additions.length) return false;
      for (const track of additions) {
        const index = this.state.queue.push(track) - 1;
        this.state.order.push(index);
      }
      this.persist();
      emit("queue", this.state);
      emit("toast", `Automix added ${additions.length} similar tracks`);
      return true;
    } catch {
      return false;
    }
  }

  setAutomix(enabled: boolean): void {
    this.state.automix = enabled;
    this.persist();
    emit("queue", this.state);
  }

  toggleShuffle(): void {
    this.state.shuffle = !this.state.shuffle;
    if (this.state.shuffle) {
      this.rebuildShuffle(this.state.order[this.state.orderIndex]);
    } else {
      const baseIndex = this.state.queue.findIndex((item) => item.id === this.current?.id);
      this.state.order = this.state.queue.map((_, index) => index);
      this.state.orderIndex = baseIndex >= 0 ? baseIndex : 0;
    }
    this.persist();
    emit("queue", this.state);
  }

  private rebuildShuffle(currentBaseIndex: number | undefined): void {
    const indexes = this.state.queue.map((_, index) => index);
    const rest = indexes.filter((index) => index !== currentBaseIndex);
    for (let i = rest.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [rest[i], rest[j]] = [rest[j], rest[i]];
    }
    this.state.order = currentBaseIndex === undefined ? rest : [currentBaseIndex, ...rest];
    this.state.orderIndex = 0;
  }

  cycleRepeat(): void {
    const sequence: Repeat[] = ["off", "all", "one"];
    this.state.repeat = sequence[(sequence.indexOf(this.state.repeat) + 1) % sequence.length];
    this.persist();
    emit("queue", this.state);
  }

  upcoming(limit = 40): Array<{ track: Track; orderPosition: number }> {
    const out: Array<{ track: Track; orderPosition: number }> = [];
    for (let position = this.state.orderIndex + 1; position < this.state.order.length; position++) {
      const base = this.state.order[position];
      const track = this.state.queue[base];
      if (track) out.push({ track, orderPosition: position });
      if (out.length >= limit) break;
    }
    return out;
  }

  history(limit = 12): Track[] {
    const out: Track[] = [];
    for (let position = this.state.orderIndex - 1; position >= 0; position--) {
      const base = this.state.order[position];
      const track = this.state.queue[base];
      if (track) out.push(track);
      if (out.length >= limit) break;
    }
    return out;
  }

  // -- playback clock / session -------------------------------------------

  alignedTime(): number {
    if (this.state.loading) return this.state.position;
    if (this.state.usingIframe && this.bridge) return this.bridge.position();
    if (this.audio?.readyState > 0 && Number.isFinite(this.audio.currentTime)) return this.audio.currentTime;
    return this.state.position;
  }

  sessionLine(): number | null {
    const index = this.state.session?.line_index;
    return typeof index === "number" ? index : null;
  }

  private async postSession(): Promise<void> {
    if (!this.current) return;
    if (this.sessionInFlight) return;
    this.sessionInFlight = true;
    const track = this.current;
    const position = this.state.position;
    const duration = this.state.duration || track.duration || 0;
    try {
      const session = await api.session({
        video_id: track.id,
        position,
        duration,
        state: this.state.playing ? "playing" : "paused",
      });
      this.state.session = session;
      emit("session", session);
    } catch {
      /* keep interpolating locally */
    } finally {
      this.sessionInFlight = false;
    }
  }

  async refreshSession(): Promise<void> {
    await this.postSession();
  }

  // -- media session -------------------------------------------------------

  private updateMediaSession(track: Track): void {
    if (!("mediaSession" in navigator)) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: track.title,
        artist: track.artist,
      album: "UPSpotify",
        artwork: [{ src: track.thumb, sizes: "480x360", type: "image/jpeg" }],
      });
    } catch {
      /* unsupported metadata */
    }
  }

  private updateMediaSessionActions(): void {
    if (!("mediaSession" in navigator)) return;
    const handlers: Array<[MediaSessionAction, MediaSessionActionHandler]> = [
      ["play", () => void this.play()],
      ["pause", () => this.pause()],
      ["nexttrack", () => void this.next()],
      ["previoustrack", () => this.prev()],
      ["seekto", (details) => {
        if (typeof details.seekTime === "number") this.seek(details.seekTime);
      }],
    ];
    for (const [action, handler] of handlers) {
      try {
        navigator.mediaSession.setActionHandler(action, handler);
      } catch {
        /* action unsupported */
      }
    }
  }

  // -- persistence ---------------------------------------------------------

  private persist(): void {
    try {
      localStorage.setItem(
        STORE_KEY,
        JSON.stringify({
          queue: this.state.queue.slice(0, 120),
          order: this.state.order.slice(0, 200),
          orderIndex: this.state.orderIndex,
          position: this.state.position,
          shuffle: this.state.shuffle,
          repeat: this.state.repeat,
          automix: this.state.automix,
          mini: this.state.mini,
        }),
      );
    } catch {
      /* quota */
    }
  }

  private restore(): void {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (!raw) return;
      const data = JSON.parse(raw);
      if (!Array.isArray(data.queue) || !data.queue.length) return;
      this.state.queue = data.queue;
      this.state.order = Array.isArray(data.order) && data.order.length
        ? data.order.filter((value: number) => value >= 0 && value < data.queue.length)
        : data.queue.map((_: Track, index: number) => index);
      this.state.orderIndex = clamp(Number(data.orderIndex) || 0, 0, this.state.order.length - 1);
      this.state.shuffle = !!data.shuffle;
      this.state.repeat = ["off", "all", "one"].includes(data.repeat) ? data.repeat : "off";
      this.state.automix = data.automix !== false;
      this.state.mini = !!data.mini;
      const track = this.current;
      if (track) {
        this.state.current = track;
        this.state.duration = track.duration || 0;
        this.state.position = Number(data.position) || 0;
        emit("track", track);
      }
      emit("queue", this.state);
    } catch {
      /* corrupt state */
    }
  }

  persistPosition(): void {
    this.persist();
  }

  // -- likes ---------------------------------------------------------------

  private loadLikes(): void {
    try {
      const stored = JSON.parse(localStorage.getItem("lirify.likes.v1") || "[]");
      if (Array.isArray(stored)) this.likes = new Set(stored);
    } catch {
      /* ignore */
    }
  }

  isLiked(id: string): boolean {
    return this.likes.has(id);
  }

  toggleLike(id: string): boolean {
    if (!id) return false;
    if (this.likes.has(id)) this.likes.delete(id);
    else this.likes.add(id);
    localStorage.setItem("lirify.likes.v1", JSON.stringify([...this.likes]));
    emit("likes", this.likes);
    return this.likes.has(id);
  }

  // -- tick / ended --------------------------------------------------------

  private startTick(): void {
    const loop = () => {
      if (this.state.playing) {
        if (this.state.mode === "audio" && !this.state.usingIframe) {
          this.state.position = this.audio.currentTime || this.state.position;
        }
        emit("tick", this.state);
      }
      this.tickRaf = requestAnimationFrame(loop);
    };
    this.tickRaf = requestAnimationFrame(loop);
  }

  private handleEnded(): void {
    emit("ended", this.state);
    void this.next(true);
  }
}

export const player = new PlayerEngine();
