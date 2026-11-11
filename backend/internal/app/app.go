package app

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"time"

	"github.com/redis/go-redis/v9"

	"hoshi/backend/internal/config"
	"hoshi/backend/internal/httpserver"
	"hoshi/backend/internal/postgres"
)

func Run(ctx context.Context, cfg config.Config) error {
	db, err := postgres.Open(cfg.PostgresDSN)
	if err != nil {
		return fmt.Errorf("open PostgreSQL: %w", err)
	}
	pool, err := db.DB()
	if err != nil {
		return fmt.Errorf("get PostgreSQL connection pool: %w", err)
	}
	defer pool.Close()

	redisClient := redis.NewClient(&redis.Options{
		Addr:     cfg.RedisAddr,
		Password: cfg.RedisPassword,
	})
	defer redisClient.Close()

	listener, err := net.Listen("tcp", cfg.HTTPAddr)
	if err != nil {
		return fmt.Errorf("listen on %s: %w", cfg.HTTPAddr, err)
	}
	server := &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           httpserver.NewRouter(),
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
	slog.Info("HTTP server listening", "addr", listener.Addr().String())

	serveErr := make(chan error, 1)
	go func() {
		serveErr <- server.Serve(listener)
	}()

	select {
	case err = <-serveErr:
	case <-ctx.Done():
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := server.Shutdown(shutdownCtx); err != nil {
			return errors.Join(fmt.Errorf("shut down HTTP server: %w", err), server.Close())
		}
		err = <-serveErr
	}
	if err != nil && !errors.Is(err, http.ErrServerClosed) {
		return fmt.Errorf("serve HTTP: %w", err)
	}
	return nil
}
