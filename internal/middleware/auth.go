package middleware

import (
	"context"
	"net/http"
	"strings"

	"billsplit/api/internal/db"
)

type contextKey string

const UserIDKey contextKey = "userID"

// Auth verifies a Supabase JWT from the Authorization header
func Auth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		header := r.Header.Get("Authorization")
		if !strings.HasPrefix(header, "Bearer ") {
			jsonError(w, "Missing or invalid Authorization header", http.StatusUnauthorized)
			return
		}

		token := header[7:]
		userID, err := db.DB.VerifyToken(token)
		if err != nil {
			jsonError(w, "Invalid or expired token", http.StatusUnauthorized)
			return
		}

		ctx := context.WithValue(r.Context(), UserIDKey, userID)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func jsonError(w http.ResponseWriter, msg string, status int) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	w.Write([]byte(`{"data":null,"error":"` + msg + `"}`)) //nolint:errcheck
}
