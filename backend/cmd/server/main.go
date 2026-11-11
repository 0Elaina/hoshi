package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"hoshi/backend/internal/app"
	"hoshi/backend/internal/config"
)

func main() {
	if err := run(); err != nil {
		slog.Error("server exited", "error", err)
		os.Exit(1)
	}
}

func run() error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	cfg, err := config.Load()
	if err != nil {
		return err
	}

	return app.Run(ctx, cfg)
}
