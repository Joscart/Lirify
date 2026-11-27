package main

import (
	"context"
	"fmt"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/backoff"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/keepalive"

	"lirify/go-ui/internal/lirifypb"
)

// Config is everything go-ui needs. It intentionally contains no database
// credentials: the only outbound dependency is the python-backend gRPC endpoint.
type Config struct {
	Port         string
	GRPCTarget   string
	Insecure     bool // local docker compose only; Cloud Run always uses TLS
	BackendURL   string
	PlayerURL    string
	AdminURL     string
	CallTimeout  time.Duration
	WatchSeconds int32
	// Mode is "readonly" (Cloud Run serving dashboard) or "local" (laptop
	// indexer dashboard). Only local mode exposes write endpoints and controls;
	// the cloud binary answers 403 to every mutating route.
	Mode      string
	LocalMode bool
}

func env(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}

func loadConfig() (Config, error) {
	mode := strings.ToLower(strings.TrimSpace(env("DASHBOARD_MODE", "readonly")))
	if mode != "local" && mode != "indexer" && mode != "readonly" && mode != "serving" {
		mode = "readonly"
	}
	local := mode == "local" || mode == "indexer"
	if local {
		mode = "local"
	} else {
		mode = "readonly"
	}
	cfg := Config{
		Port:         env("PORT", "8080"),
		GRPCTarget:   strings.TrimSpace(os.Getenv("GRPC_TARGET")),
		BackendURL:   strings.TrimRight(env("PYTHON_BACKEND_URL", ""), "/"),
		PlayerURL:    env("PUBLIC_PLAYER_URL", "https://lirify.joscart.win"),
		AdminURL:     strings.TrimRight(strings.TrimSpace(os.Getenv("ADMIN_API_URL")), "/"),
		CallTimeout:  20 * time.Second,
		WatchSeconds: 5,
		Mode:         mode,
		LocalMode:    local,
	}

	if raw := os.Getenv("GRPC_TIMEOUT_SECONDS"); raw != "" {
		if seconds, err := strconv.Atoi(raw); err == nil && seconds > 0 {
			cfg.CallTimeout = time.Duration(seconds) * time.Second
		}
	}
	if raw := os.Getenv("WATCH_INTERVAL_SECONDS"); raw != "" {
		if seconds, err := strconv.Atoi(raw); err == nil && seconds >= 2 && seconds <= 60 {
			cfg.WatchSeconds = int32(seconds)
		}
	}

	// Derive the gRPC target from the backend URL when it is not given: Cloud Run
	// serves gRPC on 443 and terminates TLS for us.
	if cfg.GRPCTarget == "" && cfg.BackendURL != "" {
		if parsed, err := url.Parse(cfg.BackendURL); err == nil && parsed.Host != "" {
			port := parsed.Port()
			if port == "" {
				switch parsed.Scheme {
				case "http":
					port = "80"
				default:
					port = "443"
				}
			}
			cfg.GRPCTarget = net.JoinHostPort(parsed.Hostname(), port)
		}
	}
	if cfg.GRPCTarget == "" {
		cfg.GRPCTarget = "127.0.0.1:50051"
	}

	cfg.Insecure = strings.EqualFold(env("GRPC_TLS", "true"), "false")
	return cfg, nil
}

func dialBackend(cfg Config) (*Client, error) {
	opts := []grpc.DialOption{
		grpc.WithDefaultCallOptions(
			grpc.MaxCallRecvMsgSize(16<<20),
			grpc.MaxCallSendMsgSize(16<<20),
		),
		grpc.WithConnectParams(grpc.ConnectParams{
			Backoff:           backoff.DefaultConfig,
			MinConnectTimeout: 5 * time.Second,
		}),
		grpc.WithKeepaliveParams(keepalive.ClientParameters{
			Time:                60 * time.Second,
			Timeout:             20 * time.Second,
			PermitWithoutStream: false,
		}),
	}

	if cfg.Insecure {
		opts = append(opts, grpc.WithTransportCredentials(insecure.NewCredentials()))
	} else {
		host, _, err := net.SplitHostPort(cfg.GRPCTarget)
		if err != nil {
			host = cfg.GRPCTarget
		}
		opts = append(opts, grpc.WithTransportCredentials(
			credentials.NewClientTLSFromCert(nil, host),
		))
	}

	// NewClient is non-blocking: the first RPC establishes the connection, so a
	// Cloud Run cold start can serve /health before python-backend wakes up.
	conn, err := grpc.NewClient(cfg.GRPCTarget, opts...)
	if err != nil {
		return nil, err
	}
	return &Client{
		conn:    conn,
		api:     lirifypb.NewLirifyServiceClient(conn),
		indexer: lirifypb.NewLirifyIndexerServiceClient(conn),
		cfg:     cfg,
	}, nil
}

// Client wraps the generated stub with the shared per-call timeout.
type Client struct {
	conn    *grpc.ClientConn
	api     lirifypb.LirifyServiceClient
	indexer lirifypb.LirifyIndexerServiceClient
	cfg     Config
}

func (c *Client) Close() error { return c.conn.Close() }

func (c *Client) context(parent context.Context) (context.Context, context.CancelFunc) {
	if parent == nil {
		parent = context.Background()
	}
	return context.WithTimeout(parent, c.cfg.CallTimeout)
}

// Ping is used by /readyz and does not require an index.
func (c *Client) Ping(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	_, err := c.api.GetIndexStats(ctx, &lirifypb.GetIndexStatsRequest{})
	if err != nil {
		return fmt.Errorf("python-backend unreachable: %w", err)
	}
	return nil
}
