package handlers

import (
	"encoding/json"
	"net/http"

	"billsplit/api/internal/services"
)

// CreatePayment handles POST /api/payments
func CreatePayment(w http.ResponseWriter, r *http.Request) {
	var body struct {
		OrderID string  `json:"orderId"`
		Amount  float64 `json:"amount"`
		Method  string  `json:"method"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		jsonBadRequest(w, "invalid JSON body")
		return
	}
	if body.OrderID == "" || body.Amount == 0 || body.Method == "" {
		jsonBadRequest(w, "orderId, amount and method are required")
		return
	}

	payment, err := services.CreatePayment(body.OrderID, body.Amount, body.Method)
	if err != nil {
		jsonServerError(w, err)
		return
	}
	jsonCreated(w, payment)
}

// RedsysSign handles POST /api/payments/redsys-sign
func RedsysSign(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Amount float64 `json:"amount"`
		URLOk  string  `json:"urlOk"`
		URLKo  string  `json:"urlKo"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		jsonBadRequest(w, "invalid JSON body")
		return
	}
	if body.Amount == 0 || body.URLOk == "" || body.URLKo == "" {
		jsonBadRequest(w, "amount, urlOk and urlKo are required")
		return
	}

	result, err := services.SignRedsys(body.Amount, body.URLOk, body.URLKo)
	if err != nil {
		jsonServerError(w, err)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result) //nolint:errcheck
}
