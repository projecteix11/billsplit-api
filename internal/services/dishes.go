package services

import (
	"billsplit/api/internal/db"
	"billsplit/api/internal/types"
)

// GetDishes returns all available dishes ordered by name
func GetDishes() ([]types.Dish, error) {
	var dishes []types.Dish
	err := db.DB.Select("dishes", "is_available=eq.true&order=name", &dishes)
	if err != nil {
		return nil, err
	}
	if dishes == nil {
		dishes = []types.Dish{}
	}
	return dishes, nil
}

// GetCategories returns all dish categories ordered by sort_order
func GetCategories() ([]types.DishCategory, error) {
	var categories []types.DishCategory
	err := db.DB.Select("dish_categories", "order=sort_order", &categories)
	if err != nil {
		return nil, err
	}
	if categories == nil {
		categories = []types.DishCategory{}
	}
	return categories, nil
}
