package handlers

import (
	"encoding/json"
	"net/http"

	"billsplit/api/internal/services"
	"billsplit/api/internal/types"

	"github.com/go-chi/chi/v5"
)

// CreateOrder handles POST /api/orders
func CreateOrder(w http.ResponseWriter, r *http.Request) {
	var body struct {
		TableID     string               `json:"tableId"`
		TableNumber int                  `json:"tableNumber"`
		Items       []types.NewOrderItem `json:"items"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		jsonBadRequest(w, "invalid JSON body")
		return
	}
	if body.TableID == "" || body.TableNumber == 0 || len(body.Items) == 0 {
		jsonBadRequest(w, "tableId, tableNumber and items[] are required")
		return
	}

	order, err := services.CreateOrder(body.TableID, body.TableNumber, body.Items)
	if err != nil {
		jsonServerError(w, err)
		return
	}
	jsonCreated(w, order)
}

// GetOrderByID handles GET /api/orders/{orderId}
func GetOrderByID(w http.ResponseWriter, r *http.Request) {
	orderID := chi.URLParam(r, "orderId")
	order, err := services.GetOrderByID(orderID)
	if err != nil {
		jsonServerError(w, err)
		return
	}
	if order == nil {
		jsonNotFound(w, "Order not found")
		return
	}
	jsonOK(w, order)
}

// AddItemsToOrder handles POST /api/orders/{orderId}/items
func AddItemsToOrder(w http.ResponseWriter, r *http.Request) {
	orderID := chi.URLParam(r, "orderId")

	var body struct {
		Items []types.NewOrderItem `json:"items"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		jsonBadRequest(w, "invalid JSON body")
		return
	}
	if len(body.Items) == 0 {
		jsonBadRequest(w, "items[] is required")
		return
	}

	if err := services.AddItemsToOrder(orderID, body.Items); err != nil {
		jsonServerError(w, err)
		return
	}
	jsonOK(w, nil)
}

// CloseOrder handles PATCH /api/orders/{orderId}/close
func CloseOrder(w http.ResponseWriter, r *http.Request) {
	orderID := chi.URLParam(r, "orderId")
	if err := services.CloseOrder(orderID); err != nil {
		jsonServerError(w, err)
		return
	}
	jsonOK(w, nil)
}

// GetOpenOrderForTable handles GET /api/tables/{tableId}/open-order
func GetOpenOrderForTable(w http.ResponseWriter, r *http.Request) {
	tableID := chi.URLParam(r, "tableId")
	order, err := services.GetOpenOrderForTable(tableID)
	if err != nil {
		jsonServerError(w, err)
		return
	}
	if order == nil {
		jsonNotFound(w, "No open order for this table")
		return
	}
	jsonOK(w, order)
}

// ListOrders handles GET /api/orders (protected — management only)
func ListOrders(w http.ResponseWriter, r *http.Request) {
	status := r.URL.Query().Get("status")
	if status == "" {
		status = "open"
	}
	if status != "open" && status != "closed" {
		jsonBadRequest(w, "status must be open or closed")
		return
	}

	orders, err := services.FetchOrders(status)
	if err != nil {
		jsonServerError(w, err)
		return
	}
	jsonOK(w, orders)
}
