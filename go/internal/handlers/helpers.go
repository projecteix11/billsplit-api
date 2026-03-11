package handlers

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

func jsonOK(w http.ResponseWriter, data interface{}) {
	jsonResponse(w, http.StatusOK, map[string]interface{}{"data": data, "error": nil})
}

func jsonCreated(w http.ResponseWriter, data interface{}) {
	jsonResponse(w, http.StatusCreated, map[string]interface{}{"data": data, "error": nil})
}

func jsonBadRequest(w http.ResponseWriter, msg string) {
	jsonResponse(w, http.StatusBadRequest, map[string]interface{}{"data": nil, "error": msg})
}

func jsonNotFound(w http.ResponseWriter, msg string) {
	jsonResponse(w, http.StatusNotFound, map[string]interface{}{"data": nil, "error": msg})
}

func jsonServerError(w http.ResponseWriter, err error) {
	log.Printf("[api] error: %v", err)
	msg := fmt.Sprintf("%v", err)
	jsonResponse(w, http.StatusInternalServerError, map[string]interface{}{"data": nil, "error": msg})
}

func jsonResponse(w http.ResponseWriter, status int, body interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(body) //nolint:errcheck
}
