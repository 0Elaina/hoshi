package config

import (
	"errors"
	"fmt"
	"os"
	"strings"
)

type Config struct {
	HTTPAddr      string
	PostgresDSN   string
	RedisAddr     string
	RedisPassword string
}

func Load() (Config, error) {
	httpAddr, err := addressFromEnv("HOSHI_HTTP_ADDR", "127.0.0.1:8080")
	if err != nil {
		return Config{}, err
	}
	redisAddr, err := addressFromEnv("HOSHI_REDIS_ADDR", "127.0.0.1:6379")
	if err != nil {
		return Config{}, err
	}

	postgresDSN := strings.TrimSpace(os.Getenv("HOSHI_POSTGRES_DSN"))
	if postgresDSN == "" {
		return Config{}, errors.New("HOSHI_POSTGRES_DSN is required")
	}
	redisPassword := os.Getenv("HOSHI_REDIS_PASSWORD")
	if redisPassword == "" {
		return Config{}, errors.New("HOSHI_REDIS_PASSWORD is required")
	}

	return Config{
		HTTPAddr:      httpAddr,
		PostgresDSN:   postgresDSN,
		RedisAddr:     redisAddr,
		RedisPassword: redisPassword,
	}, nil
}

func addressFromEnv(key, fallback string) (string, error) {
	value, exists := os.LookupEnv(key)
	if !exists {
		return fallback, nil
	}
	value = strings.TrimSpace(value)
	if value == "" {
		return "", fmt.Errorf("%s must not be empty", key)
	}
	return value, nil
}
