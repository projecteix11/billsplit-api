package handlers

import (
	"encoding/json"
	"net/http"
	"slices"

	"billsplit/api/internal/services"

	"github.com/go-chi/chi/v5"
)

var validKitchenStatuses = []string{"pending", "cooking", "ready", "delivered"}
var validPaymentStatuses = []string{"unassigned", "assigned", "paid"}

// UpdateKitchenStatus handles PATCH /api/order-items/{itemId}/kitchen-status (protected)
func UpdateKitchenStatus(w http.ResponseWriter, r *http.Request) {
	itemID := chi.URLParam(r, "itemId")

	var body struct {
		Status string `json:"status"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		jsonBadRequest(w, "invalid JSON body")
		return
	}
	if !slices.Contains(validKitchenStatuses, body.Status) {
		jsonBadRequest(w, "status must be one of: pending, cooking, ready, delivered")
		return
	}

	if err := services.UpdateItemKitchenStatus(itemID, body.Status); err != nil {
		jsonServerError(w, err)
		return
	}
	jsonOK(w, nil)
}

// UpdatePaymentStatus handles PATCH /api/order-items/payment-status
func UpdatePaymentStatus(w http.ResponseWriter, r *http.Request) {
	var body struct {
		ItemIDs []string `json:"itemIds"`
		Status  string   `json:"status"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		jsonBadRequest(w, "invalid JSON body")
		return
	}
	if len(body.ItemIDs) == 0 {
		jsonBadRequest(w, "itemIds[] is required")
		return
	}
	if !slices.Contains(validPaymentStatuses, body.Status) {
		jsonBadRequest(w, "status must be one of: unassigned, assigned, paid")
		return
	}

	if err := services.UpdateItemsPaymentStatus(body.ItemIDs, body.Status); err != nil {
		jsonServerError(w, err)
		return
	}
	jsonOK(w, nil)
}
