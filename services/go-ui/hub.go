package main

import (
	"context"
	"encoding/json"
	"log"
	"strconv"
	"sync"
	"time"

	"lirify/go-ui/internal/lirifypb"
)

// Hub keeps one gRPC WatchIndexStats stream to python-backend and fans the
// results out to every connected browser. Browsers get SSE, not gRPC: no
// generated JavaScript is needed and EventSource reconnects on its own.
type Hub struct {
	mu        sync.RWMutex
	subs      map[chan []byte]struct{}
	last      *lirifypb.IndexStats
	jobStates map[string]string
}

func NewHub() *Hub {
	return &Hub{
		subs:      make(map[chan []byte]struct{}),
		jobStates: make(map[string]string),
	}
}

func (h *Hub) Subscribe() chan []byte {
	channel := make(chan []byte, 8)
	h.mu.Lock()
	h.subs[channel] = struct{}{}
	h.mu.Unlock()
	return channel
}

func (h *Hub) Unsubscribe(channel chan []byte) {
	h.mu.Lock()
	if _, ok := h.subs[channel]; ok {
		delete(h.subs, channel)
		close(channel)
	}
	h.mu.Unlock()
}

func (h *Hub) broadcast(payload map[string]any) {
	encoded, err := json.Marshal(payload)
	if err != nil {
		return
	}
	frame := append(append([]byte("data: "), encoded...), []byte("\n\n")...)

	h.mu.RLock()
	defer h.mu.RUnlock()
	for channel := range h.subs {
		select {
		case channel <- frame:
		default:
			// Slow client: drop this frame rather than blocking the watcher.
		}
	}
}

// Snapshot returns the last stats as the JSON shape the dashboard expects.
func (h *Hub) Snapshot() map[string]any {
	h.mu.RLock()
	defer h.mu.RUnlock()
	if h.last == nil {
		return map[string]any{
			"indexed_songs": 0,
			"queue": map[string]any{
				"playlist_pending": 0,
				"matrix_pending":   0,
			},
		}
	}
	payload := statsJSON(h.last)
	return payload
}

// Run reconnects the watch stream forever; Cloud Run scales to zero, so the
// stream will break regularly and must be re-established, not treated as fatal.
func (h *Hub) Run(ctx context.Context, client *Client) {
	for ctx.Err() == nil {
		stream, err := client.api.WatchIndexStats(
			ctx,
			&lirifypb.WatchIndexStatsRequest{IntervalSeconds: client.cfg.WatchSeconds},
		)
		if err != nil {
			log.Printf("watch: open failed: %v", err)
			sleepOrDone(ctx, 3*time.Second)
			continue
		}
		for {
			stats, err := stream.Recv()
			if err != nil {
				if ctx.Err() == nil {
					log.Printf("watch: stream closed: %v", err)
				}
				break
			}
			h.publish(stats)
		}
		sleepOrDone(ctx, 2*time.Second)
	}
}

func sleepOrDone(ctx context.Context, d time.Duration) {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ctx.Done():
	case <-timer.C:
	}
}

func (h *Hub) publish(stats *lirifypb.IndexStats) {
	h.mu.Lock()
	previous := h.last
	h.last = stats
	changed := previous == nil || previous.IndexedSongs != stats.IndexedSongs

	// Translate job transitions into the event vocabulary the dashboard logs.
	events := make([]map[string]any, 0, 4)
	for _, job := range stats.Jobs {
		status := job.Status
		if previousStatus, seen := h.jobStates[job.JobId]; !seen || previousStatus != status {
			h.jobStates[job.JobId] = status
			events = append(events, map[string]any{
				"event":     "status",
				"stage":     "job",
				"job_id":    job.JobId,
				"status":    status,
				"job_stage": job.Stage,
				"message":   jobStatusMessage(job),
				"url":       job.Url,
				"added":     job.Added,
				"ts":        time.Now().Unix(),
			})
		}
	}
	added := 0
	if previous != nil {
		added = int(stats.IndexedSongs - previous.IndexedSongs)
	}
	h.mu.Unlock()

	if added > 0 {
		events = append(events, map[string]any{
			"event":   "status",
			"stage":   "commit",
			"message": "Index grew by " + strconv.Itoa(added) + " songs",
			"added":   added,
			"ts":      time.Now().Unix(),
		})
	}

	// Always nudge the dashboard so counters follow the watch tick.
	h.broadcast(map[string]any{
		"event":         "stats",
		"indexed_songs": stats.IndexedSongs,
		"queue": map[string]any{
			"playlist_pending": stats.PlaylistPending,
			"matrix_pending":   stats.MatrixPending,
		},
		"ts": time.Now().Unix(),
	})
	for _, event := range events {
		h.broadcast(event)
	}
	if changed && previous != nil {
		log.Printf("index grew to %d songs", stats.IndexedSongs)
	}
}

func jobStatusMessage(job *lirifypb.Job) string {
	switch job.Status {
	case "queued":
		return "Queued " + job.Url
	case "indexing":
		return "Scraping " + job.Url
	case "matrix_pending":
		return "Stashed; waiting for the matrix worker"
	case "committed":
		return "Committed " + strconv.Itoa(int(job.Added)) + " songs"
	case "skipped":
		return "Skipped (duplicate or filtered)"
	case "error":
		if job.Error != "" {
			return "Failed: " + job.Error
		}
		return "Failed"
	default:
		return job.Status
	}
}
