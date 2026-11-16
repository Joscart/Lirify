// Command go-ui is the Lirify playlist indexer and operations dashboard.
//
// It is a stateless Cloud Run service: every read and write goes to
// python-backend over gRPC/TLS (:443). go-ui holds no database credentials and
// writes nothing to disk; the only in-memory state is the fan-out hub that
// relays the python-backend stats stream to connected browsers via SSE.
package main

import (
	"context"
	"embed"
	"errors"
	"html/template"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

//go:embed templates/*
var tmplFS embed.FS

func main() {
	cfg, err := loadConfig()
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	client, err := dialBackend(cfg)
	if err != nil {
		log.Fatalf("gRPC dial %s: %v", cfg.GRPCTarget, err)
	}
	defer client.Close()

	tmpl, err := template.ParseFS(tmplFS, "templates/*.html")
	if err != nil {
		log.Fatalf("templates: %v", err)
	}

	hub := NewHub()
	app := &Server{cfg: cfg, client: client, tmpl: tmpl, hub: hub}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	go hub.Run(ctx, client)

	mux := http.NewServeMux()
	app.routes(mux)

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           requestLog(mux),
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       75 * time.Second,
	}

	go func() {
		log.Printf("go-ui listening on :%s (gRPC -> %s, tls=%v)", cfg.Port, cfg.GRPCTarget, !cfg.Insecure)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("listen: %v", err)
		}
	}()

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutdownCtx)
	log.Print("go-ui stopped")
}

func requestLog(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		if r.URL.Path != "/api/events" {
			log.Printf("%s %s %s", r.Method, r.URL.Path, time.Since(start).Round(time.Millisecond))
		}
	})
}
