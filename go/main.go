package main

import (
	"fmt"
	"log"
	"net/http"
	"os"

	"billsplit/api/internal/db"
	"billsplit/api/internal/handlers"
	"billsplit/api/internal/middleware"

	"github.com/go-chi/chi/v5"
	chiMiddleware "github.com/go-chi/chi/v5/middleware"
	"github.com/joho/godotenv"
)

func main() {
	// Load .env in development (ignored if the file is absent)
	godotenv.Load("../.env") //nolint:errcheck

	// Initialize Supabase client
	db.Init()

	r := chi.NewRouter()

	// Global middleware
	r.Use(chiMiddleware.Recoverer)
	r.Use(middleware.CORS)

	// Health check
	r.Get("/api/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"status":"ok"}`)) //nolint:errcheck
	})

	// ── Dishes ────────────────────────────────────────────────────────────────
	r.Get("/api/dishes", handlers.GetDishes)
	r.Get("/api/categories", handlers.GetCategories)

	// ── Orders (public) ───────────────────────────────────────────────────────
	r.Post("/api/orders", handlers.CreateOrder)
	r.Get("/api/orders/{orderId}", handlers.GetOrderByID)
	r.Post("/api/orders/{orderId}/items", handlers.AddItemsToOrder)
	r.Patch("/api/orders/{orderId}/close", handlers.CloseOrder)
	r.Get("/api/tables/{tableId}/open-order", handlers.GetOpenOrderForTable)

	// ── Orders (management — JWT required) ───────────────────────────────────
	r.With(middleware.Auth).Get("/api/orders", handlers.ListOrders)

	// ── Order items ───────────────────────────────────────────────────────────
	r.With(middleware.Auth).Patch("/api/order-items/{itemId}/kitchen-status", handlers.UpdateKitchenStatus)
	r.Patch("/api/order-items/payment-status", handlers.UpdatePaymentStatus)

	// ── Payments ──────────────────────────────────────────────────────────────
	r.Post("/api/payments", handlers.CreatePayment)
	r.Post("/api/payments/redsys-sign", handlers.RedsysSign)

	port := os.Getenv("PORT")
	if port == "" {
		port = "3001"
	}

	fmt.Printf("BillSplit API (Go) running on http://localhost:%s\n", port)
	if err := http.ListenAndServe(":"+port, r); err != nil {
		log.Fatal(err)
	}
}
