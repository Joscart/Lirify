package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"lirify/go-ui/internal/lirifypb"
)

// Server holds the HTTP surface. It never touches a database: every handler is a
// thin JSON adapter over one gRPC call.
type Server struct {
	cfg    Config
	client *Client
	tmpl   templateExecutor
	hub    *Hub
}

type templateExecutor interface {
	ExecuteTemplate(w io.Writer, name string, data any) error
}

func (s *Server) routes(mux *http.ServeMux) {
	mux.HandleFunc("GET /", s.index)
	mux.HandleFunc("GET /health", s.health)
	mux.HandleFunc("GET /readyz", s.ready)
	// Kept for container-local probes only: the *.run.app edge intercepts
	// /healthz with its own 404 page, so it must not be the public endpoint.
	mux.HandleFunc("GET /healthz", s.health)
	mux.HandleFunc("GET /api/config", s.config)
	mux.HandleFunc("GET /api/stats", s.stats)
	// Alias so `/stats` does not silently 404 on the dashboard host; the
	// python-backend route with the same name lives on a different origin.
	mux.HandleFunc("GET /stats", s.stats)
	mux.HandleFunc("GET /api/queue", s.queue)
	mux.HandleFunc("GET /api/cache", s.cache)
	mux.HandleFunc("GET /api/matrices/preview", s.matrixPreview)
	mux.HandleFunc("GET /api/tracks", s.tracks)
	for _, method := range []string{"GET", "POST", "PUT", "DELETE"} {
		mux.HandleFunc(method+" /api/db/", s.requireLocal(s.dbProxy))
	}
	mux.HandleFunc("GET /api/events", s.events)
	// Mutating routes exist only for the laptop dashboard. On Cloud Run every one
	// of them answers 403 without dialling python-backend.
	mux.HandleFunc("POST /api/extract", s.requireLocal(s.extract))
	mux.HandleFunc("POST /api/index", s.requireLocal(s.indexPlaylist))
	mux.HandleFunc("POST /api/queue", s.requireLocal(s.queuePlaylists))
	mux.HandleFunc("POST /api/retry", s.requireLocal(s.retry))
	mux.HandleFunc("GET /api/local-index", s.requireLocal(s.localIndex))
	mux.HandleFunc("POST /api/publish", s.requireLocal(s.publish))
	mux.HandleFunc("GET /docs", s.docs)
}

// requireLocal guards every write/publish route with the dashboard role.
func (s *Server) requireLocal(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !s.cfg.LocalMode {
			writeJSON(w, http.StatusForbidden, map[string]any{
				"code":   "read_only_serving_dashboard",
				"detail": "This dashboard is read-only (DASHBOARD_MODE=readonly). Indexing runs on the local-indexer stack.",
			})
			return
		}
		next(w, r)
	}
}

// ---------------------------------------------------------------------------
// Page + meta
// ---------------------------------------------------------------------------

func (s *Server) index(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	data := map[string]any{
		"LocalMode": s.cfg.LocalMode,
		"Mode":      s.cfg.Mode,
	}
	if err := s.tmpl.ExecuteTemplate(w, "index.html", data); err != nil {
		http.Error(w, "template error", http.StatusInternalServerError)
	}
}

// health is the Cloud Run startup/liveness endpoint. It reports the process, not
// the backend: python-backend scales to zero, so a cold backend must not fail this
// service's own startup probe.
func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status":  "ok",
		"service": "go-webui",
		"mode":    s.cfg.Mode,
		"grpc":    s.cfg.GRPCTarget,
		"tls":     !s.cfg.Insecure,
	})
}

// ready reports whether the python-backend gRPC channel answers.
func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 4*time.Second)
	defer cancel()
	if err := s.client.Ping(ctx); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"status": "degraded",
			"error":  err.Error(),
			"grpc":   s.cfg.GRPCTarget,
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ready", "grpc": s.cfg.GRPCTarget})
}

func (s *Server) config(w http.ResponseWriter, r *http.Request) {
	docs := s.cfg.BackendURL + "/docs"
	writeJSON(w, http.StatusOK, map[string]any{
		"docs_url":   docs,
		"player_url": s.cfg.PlayerURL,
		"backend":    s.cfg.BackendURL,
		"grpc":       s.cfg.GRPCTarget,
		"mode":       s.cfg.Mode,
		"local_mode": s.cfg.LocalMode,
	})
}

func (s *Server) docs(w http.ResponseWriter, r *http.Request) {
	if s.cfg.BackendURL == "" {
		http.Error(w, "PYTHON_BACKEND_URL is not configured", http.StatusNotFound)
		return
	}
	http.Redirect(w, r, s.cfg.BackendURL+"/docs", http.StatusTemporaryRedirect)
}

// ---------------------------------------------------------------------------
// Read endpoints
// ---------------------------------------------------------------------------

func (s *Server) stats(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := s.client.context(r.Context())
	defer cancel()
	payload, err := s.client.api.GetIndexStats(ctx, &lirifypb.GetIndexStatsRequest{})
	if err != nil {
		writeRPCError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, statsJSON(payload))
}

func (s *Server) queue(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := s.client.context(r.Context())
	defer cancel()
	payload, err := s.client.api.GetIndexStats(ctx, &lirifypb.GetIndexStatsRequest{})
	if err != nil {
		writeRPCError(w, err)
		return
	}
	stashed := 0
	for _, job := range payload.Jobs {
		if job.Status == "matrix_pending" {
			stashed++
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"playlist_queue":  payload.PlaylistPending,
		"matrix_queue":    payload.MatrixPending,
		"stashed_batches": stashed,
		"cached_lyrics":   payload.CachedLyrics,
		"failed_songs":    payload.FailedSongs,
		"storage":         payload.TracksStore,
		"jobs":            jobsJSON(payload.Jobs),
		"generated_at":    payload.GeneratedAt,
	})
}

func (s *Server) cache(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := s.client.context(r.Context())
	defer cancel()
	payload, err := s.client.api.GetFailedSongs(ctx, &lirifypb.GetFailedSongsRequest{Limit: 100})
	if err != nil {
		writeRPCError(w, err)
		return
	}
	failed := make([]map[string]any, 0, len(payload.Failed))
	for _, row := range payload.Failed {
		failed = append(failed, map[string]any{
			"video_id": row.VideoId,
			"title":    row.Title,
			"artist":   row.Artist,
			"reason":   row.Reason,
			"attempts": row.Attempts,
			"last_try": row.LastTry,
			"duration": row.Duration,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"cached_lyrics":          payload.CachedLyrics,
		"failed_songs":           payload.Total,
		"max_attempts":           payload.MaxAttempts,
		"retry_interval_seconds": payload.RetryIntervalSeconds,
		"failed":                 failed,
	})
}

// tracks is the read-only catalogue view: every committed song with the metadata
// the indexer published (title, artist, language, duration).
func (s *Server) tracks(w http.ResponseWriter, r *http.Request) {
	offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 || limit > 500 {
		limit = 100
	}
	ctx, cancel := s.client.context(r.Context())
	defer cancel()
	payload, err := s.client.api.ListTracks(ctx, &lirifypb.ListTracksRequest{
		Offset: int32(offset),
		Limit:  int32(limit),
	})
	if err != nil {
		writeRPCError(w, err)
		return
	}
	rows := make([]map[string]any, 0, len(payload.Tracks))
	for _, track := range payload.Tracks {
		rows = append(rows, map[string]any{
			"video_id": track.VideoId,
			"title":    track.Title,
			"artist":   track.Artist,
			"language": track.Language,
			"backend":  track.Backend,
			"duration": track.Duration,
			"thumb":    track.Thumb,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"total":  payload.Total,
		"offset": offset,
		"limit":  limit,
		"tracks": rows,
	})
}

// dbProxy forwards the database CRUD surface to the standalone local indexer.
// The browser stays on this origin; the admin API listens on 127.0.0.1 only and
// is never exposed by the cloud dashboard.
func (s *Server) dbProxy(w http.ResponseWriter, r *http.Request) {
	if s.cfg.AdminURL == "" {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"detail": "ADMIN_API_URL is not configured for local mode",
		})
		return
	}
	path := strings.TrimPrefix(r.URL.Path, "/api/db")
	target := s.cfg.AdminURL + "/db" + path
	if r.URL.RawQuery != "" {
		target += "?" + r.URL.RawQuery
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 8<<20))
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "could not read body"})
		return
	}
	request, err := http.NewRequestWithContext(r.Context(), r.Method, target, bytes.NewReader(body))
	if err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]any{"detail": err.Error()})
		return
	}
	if contentType := r.Header.Get("Content-Type"); contentType != "" {
		request.Header.Set("Content-Type", contentType)
	}
	request.Header.Set("Accept", "application/json")

	// Rebuild/reset can re-embed thousands of songs: allow a long request.
	client := &http.Client{Timeout: 2 * time.Hour}
	response, err := client.Do(request)
	if err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]any{"detail": "local indexer unreachable: " + err.Error()})
		return
	}
	defer response.Body.Close()
	if contentType := response.Header.Get("Content-Type"); contentType != "" {
		w.Header().Set("Content-Type", contentType)
	}
	w.WriteHeader(response.StatusCode)
	_, _ = io.Copy(w, response.Body)
}

func (s *Server) matrixPreview(w http.ResponseWriter, r *http.Request) {
	size, _ := strconv.Atoi(r.URL.Query().Get("size"))
	if size == 0 {
		size = 12
	}
	ctx, cancel := s.client.context(r.Context())
	defer cancel()
	payload, err := s.client.api.MatrixPreview(ctx, &lirifypb.MatrixPreviewRequest{Size: int32(size)})
	if err != nil {
		writeRPCError(w, err)
		return
	}
	matrices := map[string]any{}
	for name, matrix := range payload.Matrices {
		values := make([][]float64, 0, len(matrix.Rows))
		for _, row := range matrix.Rows {
			values = append(values, row.Values)
		}
		matrices[name] = map[string]any{
			"shape":  matrix.Shape,
			"values": values,
		}
	}
	songs := make([]map[string]any, 0, len(payload.Songs))
	for _, song := range payload.Songs {
		songs = append(songs, map[string]any{
			"video_id": song.VideoId,
			"title":    song.Title,
			"artist":   song.Artist,
			"language": song.Language,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"shape":    payload.Shape,
		"size":     payload.Size,
		"songs":    songs,
		"matrices": matrices,
		"weights":  payload.Weights,
	})
}

// ---------------------------------------------------------------------------
// Write endpoints
// ---------------------------------------------------------------------------

type playlistRequest struct {
	URL    string   `json:"url"`
	URLs   []string `json:"urls"`
	Limit  *int32   `json:"limit"`
	Source string   `json:"source"`
}

func decode(r *http.Request) (playlistRequest, error) {
	var body playlistRequest
	if r.Body == nil {
		return body, errors.New("missing body")
	}
	decoder := json.NewDecoder(io.LimitReader(r.Body, 64<<10))
	if err := decoder.Decode(&body); err != nil {
		return body, err
	}
	body.URL = strings.TrimSpace(body.URL)
	body.Source = strings.TrimSpace(body.Source)
	if body.Source == "" {
		body.Source = "go-webui"
	}
	return body, nil
}

func (s *Server) extract(w http.ResponseWriter, r *http.Request) {
	body, err := decode(r)
	if err != nil || body.URL == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "url is required"})
		return
	}
	var limit int32
	if body.Limit != nil {
		limit = *body.Limit
	}
	ctx, cancel := s.client.context(r.Context())
	defer cancel()
	payload, err := s.client.api.ExtractVideoIds(ctx, &lirifypb.ExtractVideoIdsRequest{
		PlaylistUrl: body.URL,
		Limit:       limit,
	})
	if err != nil {
		writeRPCError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"count":     payload.Count,
		"ids":       payload.VideoIds,
		"extracted": true,
		"persisted": false,
	})
}

func (s *Server) indexPlaylist(w http.ResponseWriter, r *http.Request) {
	body, err := decode(r)
	if err != nil || body.URL == "" {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "url is required"})
		return
	}
	var limit int32
	if body.Limit != nil {
		limit = *body.Limit
	}
	ctx, cancel := s.client.context(r.Context())
	defer cancel()
	job, err := s.client.api.IndexPlaylist(ctx, &lirifypb.IndexPlaylistRequest{
		PlaylistUrl: body.URL,
		Limit:       limit,
		Source:      body.Source,
	})
	if err != nil {
		writeRPCError(w, err)
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]any{
		"status": job.Status,
		"added":  job.Added,
		"job":    jobJSON(job),
	})
}

func (s *Server) queuePlaylists(w http.ResponseWriter, r *http.Request) {
	body, err := decode(r)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "invalid json"})
		return
	}
	urls := body.URLs
	if body.URL != "" {
		urls = append([]string{body.URL}, urls...)
	}
	if len(urls) == 0 {
		writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "url or urls is required"})
		return
	}
	var limit int32
	if body.Limit != nil {
		limit = *body.Limit
	}
	ctx, cancel := s.client.context(r.Context())
	defer cancel()
	payload, err := s.client.api.QueuePlaylists(ctx, &lirifypb.QueuePlaylistsRequest{
		PlaylistUrls: urls,
		Limit:        limit,
		Source:       body.Source,
	})
	if err != nil {
		writeRPCError(w, err)
		return
	}
	ids := make([]string, 0, len(payload.Jobs))
	for _, job := range payload.Jobs {
		ids = append(ids, job.JobId)
	}
	writeJSON(w, http.StatusAccepted, map[string]any{
		"queued":     len(ids),
		"jobs":       ids,
		"queue_size": payload.QueueSize,
	})
}

func (s *Server) retry(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := s.client.context(r.Context())
	defer cancel()
	payload, err := s.client.api.RetryFailed(ctx, &lirifypb.RetryFailedRequest{})
	if err != nil {
		writeRPCError(w, err)
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]any{
		"started":         payload.Started,
		"already_running": payload.AlreadyRunning,
		"message":         payload.Message,
	})
}

// localIndex describes the Qwen3 vocabulary + inverted index on disk.
func (s *Server) localIndex(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := s.client.context(r.Context())
	defer cancel()
	payload, err := s.client.indexer.GetLocalIndex(ctx, &lirifypb.GetLocalIndexRequest{})
	if err != nil {
		writeRPCError(w, err)
		return
	}
	info := payload.Info
	if info == nil {
		writeJSON(w, http.StatusOK, map[string]any{})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"directory":            info.Directory,
		"tokenizer":            info.Tokenizer,
		"tokenizer_backend":    info.TokenizerBackend,
		"embedding_provider":   info.EmbeddingProvider,
		"documents":            info.Documents,
		"vocabulary_terms":     info.VocabularyTerms,
		"inverted_terms":       info.InvertedTerms,
		"vocabulary_bytes":     info.VocabularyBytes,
		"inverted_index_bytes": info.InvertedIndexBytes,
		"updated_at":           info.UpdatedAt,
		"vocabulary_path":      info.VocabularyPath,
		"inverted_index_path":  info.InvertedIndexPath,
	})
}

type publishRequest struct {
	RebuildLocalIndex bool  `json:"rebuild_local_index"`
	Limit             int32 `json:"limit"`
}

// publish writes the committed index through to Atlas + Qdrant and (optionally)
// rebuilds the local Qwen3 vocabulary + inverted index.
func (s *Server) publish(w http.ResponseWriter, r *http.Request) {
	var body publishRequest
	if r.Body != nil {
		if err := json.NewDecoder(io.LimitReader(r.Body, 8<<10)).Decode(&body); err != nil && !errors.Is(err, io.EOF) {
			writeJSON(w, http.StatusBadRequest, map[string]any{"detail": "invalid json"})
			return
		}
	}
	ctx, cancel := s.client.context(r.Context())
	defer cancel()
	payload, err := s.client.indexer.PublishToCloud(ctx, &lirifypb.PublishToCloudRequest{
		RebuildLocalIndex: body.RebuildLocalIndex,
		Limit:             body.Limit,
	})
	if err != nil {
		writeRPCError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"published":        payload.Published,
		"unchanged":        payload.Unchanged,
		"songs":            payload.Songs,
		"vectors":          payload.Vectors,
		"vocabulary_terms": payload.VocabularyTerms,
		"inverted_terms":   payload.InvertedTerms,
		"directory":        payload.Directory,
		"message":          payload.Message,
		"published_at":     payload.PublishedAt,
	})
}

// ---------------------------------------------------------------------------
// SSE fan-out
// ---------------------------------------------------------------------------

func (s *Server) events(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache, no-transform")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)

	channel := s.hub.Subscribe()
	defer s.hub.Unsubscribe(channel)

	// Prime the client with a snapshot so the dashboard paints immediately.
	snapshot := s.hub.Snapshot()
	writeSSE(w, map[string]any{
		"event":         "connected",
		"indexed_songs": snapshot["indexed_songs"],
		"queue":         snapshot["queue"],
		"revision":      snapshot["revision"],
		"ts":            time.Now().Unix(),
	})
	flusher.Flush()

	keepalive := time.NewTicker(25 * time.Second)
	defer keepalive.Stop()

	for {
		select {
		case <-r.Context().Done():
			return
		case payload, open := <-channel:
			if !open {
				return
			}
			if _, err := w.Write(payload); err != nil {
				return
			}
			flusher.Flush()
		case <-keepalive.C:
			if _, err := io.WriteString(w, ": keepalive\n\n"); err != nil {
				return
			}
			flusher.Flush()
		}
	}
}

func writeSSE(w io.Writer, payload any) {
	encoded, err := json.Marshal(payload)
	if err != nil {
		return
	}
	_, _ = io.WriteString(w, "data: ")
	_, _ = w.Write(encoded)
	_, _ = io.WriteString(w, "\n\n")
}

// ---------------------------------------------------------------------------
// JSON helpers
// ---------------------------------------------------------------------------

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	encoder := json.NewEncoder(w)
	encoder.SetEscapeHTML(false)
	_ = encoder.Encode(payload)
}

func writeRPCError(w http.ResponseWriter, err error) {
	code := http.StatusBadGateway
	st, ok := status.FromError(err)
	if ok {
		switch st.Code() {
		case codes.InvalidArgument:
			code = http.StatusBadRequest
		case codes.NotFound:
			code = http.StatusNotFound
		case codes.Unauthenticated:
			code = http.StatusUnauthorized
		case codes.PermissionDenied:
			code = http.StatusForbidden
		case codes.ResourceExhausted:
			code = http.StatusTooManyRequests
		case codes.Unavailable, codes.DeadlineExceeded:
			code = http.StatusServiceUnavailable
		}
	}
	writeJSON(w, code, map[string]any{
		"detail": err.Error(),
		"code":   st.Code().String(),
	})
}

func statsJSON(payload *lirifypb.IndexStats) map[string]any {
	total := int(payload.IndexedSongs)
	languages := payload.Languages
	if languages == nil {
		languages = map[string]int32{}
	}
	backends := payload.Backends
	if backends == nil {
		backends = map[string]int32{}
	}
	queue := map[string]any{
		"playlist_pending": payload.PlaylistPending,
		"matrix_pending":   payload.MatrixPending,
		"jobs":             len(payload.Jobs),
		"cached_lyrics":    payload.CachedLyrics,
		"failed_songs":     payload.FailedSongs,
	}
	files := []string{}
	if payload.TracksStore != "" {
		files = append(files, "tracks:"+payload.TracksStore)
	}
	if payload.VectorsStore != "" {
		files = append(files, "vectors:"+payload.VectorsStore)
	}
	return map[string]any{
		"indexed_songs":      total,
		"video_ids":          payload.VideoIds,
		"vocabulary_size":    payload.VocabularySize,
		"inverted_terms":     payload.InvertedTerms,
		"lyrics_tokens":      payload.LyricsTokens,
		"languages":          languages,
		"backends":           backends,
		"weights":            payload.Weights,
		"lyrics_providers":   payload.LyricsProviders,
		"top_terms":          payload.TopTerms,
		"allowed_languages":  []string{},
		"jaccard_scope":      payload.JaccardScope,
		"matrix_shape":       []int{total, total},
		"matrices_available": payload.MatricesAvailable,
		"jobs":               len(payload.Jobs),
		"queue":              queue,
		"storage": map[string]any{
			"tracks":            payload.TracksStore,
			"vectors":           payload.VectorsStore,
			"stateless":         payload.Stateless,
			"max_indexed_songs": payload.MaxIndexedSongs,
		},
		"files":              files,
		"generated_at":       payload.GeneratedAt,
		"revision":           payload.Revision,
		"serve_only":         payload.ServeOnly,
		"mode":               payload.Mode,
		"embedding_provider": payload.EmbeddingProvider,
		"tokenizer":          payload.Tokenizer,
		"local_index": map[string]any{
			"vocabulary_terms": payload.LocalVocabularyTerms,
			"inverted_terms":   payload.LocalInvertedTerms,
			"directory":        payload.LocalIndexDir,
		},
	}
}

func jobsJSON(jobs []*lirifypb.Job) []map[string]any {
	out := make([]map[string]any, 0, len(jobs))
	for _, job := range jobs {
		out = append(out, jobJSON(job))
	}
	return out
}

func jobJSON(job *lirifypb.Job) map[string]any {
	if job == nil {
		return map[string]any{}
	}
	return map[string]any{
		"job_id":     job.JobId,
		"action":     job.Action,
		"url":        job.Url,
		"status":     job.Status,
		"stage":      job.Stage,
		"error":      job.Error,
		"error_code": job.ErrorCode,
		"retry_mode": job.RetryMode,
		"added":      job.Added,
		"attempts":   job.Attempts,
		"source":     job.Source,
		"created_at": job.CreatedAt,
		"updated_at": job.UpdatedAt,
	}
}
