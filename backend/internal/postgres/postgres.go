package postgres

import (
	"time"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

func Open(dsn string) (*gorm.DB, error) {
	return gorm.Open(postgres.Open(dsn), &gorm.Config{
		NowFunc: func() time.Time {
			return time.Now().UTC()
		},
	})
}
