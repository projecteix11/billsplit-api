package middleware

import (
	"net/http"
	"os"
	"slices"
	"strings"
)

var allowedMethods = "GET, POST, PATCH, DELETE, OPTIONS"
var allowedHeaders = "Content-Type, Authorization"

// CORS returns a middleware that sets CORS headers based on CORS_ORIGINS env var
func CORS(next http.Handler) http.Handler {
	origins := strings.Split(
		getEnvOr("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174"),
		",",
	)
	for i, o := range origins {
		origins[i] = strings.TrimSpace(o)
	}

	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if slices.Contains(origins, origin) {
			w.Header().Set("Access-Control-Allow-Origin", origin)
		}
		w.Header().Set("Access-Control-Allow-Methods", allowedMethods)
		w.Header().Set("Access-Control-Allow-Headers", allowedHeaders)

		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func getEnvOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
