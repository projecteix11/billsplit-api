package handlers

import (
	"net/http"

	"billsplit/api/internal/services"
)

// GetDishes handles GET /api/dishes
func GetDishes(w http.ResponseWriter, r *http.Request) {
	dishes, err := services.GetDishes()
	if err != nil {
		jsonServerError(w, err)
		return
	}
	jsonOK(w, dishes)
}

// GetCategories handles GET /api/categories
func GetCategories(w http.ResponseWriter, r *http.Request) {
	categories, err := services.GetCategories()
	if err != nil {
		jsonServerError(w, err)
		return
	}
	jsonOK(w, categories)
}
