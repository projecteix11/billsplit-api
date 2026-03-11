package services

import (
	"fmt"
	"math"
	"time"

	"billsplit/api/internal/db"
	"billsplit/api/internal/types"
)

const taxRateES = 10.0 // Spain restaurant tax rate (%)

func round2(v float64) float64 {
	return math.Round(v*100) / 100
}

func calculateSubtotal(items []types.NewOrderItem) float64 {
	var sum float64
	for _, i := range items {
		sum += i.DishPrice * float64(i.Quantity)
	}
	return sum
}

func calculateSubtotalFromItems(items []types.OrderItem) float64 {
	var sum float64
	for _, i := range items {
		sum += i.DishPrice * float64(i.Quantity)
	}
	return sum
}

func calculateTax(subtotal float64) float64 {
	return round2(subtotal * taxRateES / 100)
}

// FetchOrders returns all orders with the given status
func FetchOrders(status string) ([]types.Order, error) {
	query := fmt.Sprintf(
		"select=*,items:order_items(*)&status=eq.%s",
		status,
	)
	if status == "closed" {
		query += "&order=updated_at.desc&limit=100"
	} else {
		query += "&order=created_at.asc&limit=1000"
	}

	var orders []types.Order
	if err := db.DB.Select("orders", query, &orders); err != nil {
		return nil, err
	}
	if orders == nil {
		orders = []types.Order{}
	}
	return orders, nil
}

// GetOrderByID returns a single order by its ID, or nil if not found
func GetOrderByID(orderID string) (*types.Order, error) {
	query := fmt.Sprintf("select=*,items:order_items(*)&id=eq.%s&limit=1", orderID)
	var orders []types.Order
	if err := db.DB.Select("orders", query, &orders); err != nil {
		return nil, err
	}
	if len(orders) == 0 {
		return nil, nil
	}
	return &orders[0], nil
}

// GetOpenOrderForTable returns the most recent open order for a table, or nil
func GetOpenOrderForTable(tableID string) (*types.Order, error) {
	query := fmt.Sprintf(
		"select=*,items:order_items(*)&table_id=eq.%s&status=eq.open&order=created_at.desc&limit=1",
		tableID,
	)
	var orders []types.Order
	if err := db.DB.Select("orders", query, &orders); err != nil {
		return nil, err
	}
	if len(orders) == 0 {
		return nil, nil
	}
	return &orders[0], nil
}

// CreateOrder inserts a new order with its items and returns the order
func CreateOrder(tableID string, tableNumber int, items []types.NewOrderItem) (*types.Order, error) {
	subtotal := calculateSubtotal(items)
	taxAmount := calculateTax(subtotal)
	total := round2(subtotal + taxAmount)

	orderRow := map[string]interface{}{
		"table_id":     tableID,
		"table_number": tableNumber,
		"status":       "open",
		"subtotal":     subtotal,
		"tax_amount":   taxAmount,
		"total":        total,
	}

	var inserted []types.Order
	if err := db.DB.Insert("orders", orderRow, &inserted); err != nil {
		return nil, err
	}
	if len(inserted) == 0 {
		return nil, fmt.Errorf("failed to create order")
	}
	order := inserted[0]

	itemRows := make([]map[string]interface{}, len(items))
	for i, item := range items {
		dinerName := "Cliente"
		if item.DinerName != nil && *item.DinerName != "" {
			dinerName = *item.DinerName
		}
		itemRows[i] = map[string]interface{}{
			"order_id":       order.ID,
			"dish_name":      item.DishName,
			"dish_price":     item.DishPrice,
			"quantity":       item.Quantity,
			"notes":          item.Notes,
			"diner_name":     dinerName,
			"kitchen_status": "pending",
			"payment_status": "unassigned",
		}
	}

	if err := db.DB.Insert("order_items", itemRows, nil); err != nil {
		return nil, err
	}

	order.Items = []types.OrderItem{}
	return &order, nil
}

// AddItemsToOrder appends items to an existing order and recalculates totals
func AddItemsToOrder(orderID string, items []types.NewOrderItem) error {
	itemRows := make([]map[string]interface{}, len(items))
	for i, item := range items {
		dinerName := "Cliente"
		if item.DinerName != nil && *item.DinerName != "" {
			dinerName = *item.DinerName
		}
		itemRows[i] = map[string]interface{}{
			"order_id":       orderID,
			"dish_name":      item.DishName,
			"dish_price":     item.DishPrice,
			"quantity":       item.Quantity,
			"notes":          item.Notes,
			"diner_name":     dinerName,
			"kitchen_status": "pending",
			"payment_status": "unassigned",
		}
	}

	if err := db.DB.Insert("order_items", itemRows, nil); err != nil {
		return err
	}

	// Recalculate totals from all items
	existing, err := GetOrderByID(orderID)
	if err != nil || existing == nil {
		return err
	}

	subtotal := calculateSubtotalFromItems(existing.Items)
	taxAmount := calculateTax(subtotal)
	total := round2(subtotal + taxAmount)

	return db.DB.Update("orders", "id=eq."+orderID, map[string]interface{}{
		"subtotal":   subtotal,
		"tax_amount": taxAmount,
		"total":      total,
		"updated_at": time.Now().UTC().Format(time.RFC3339),
	})
}

// CloseOrder marks an order as closed
func CloseOrder(orderID string) error {
	return db.DB.Update("orders", "id=eq."+orderID, map[string]interface{}{
		"status":     "closed",
		"updated_at": time.Now().UTC().Format(time.RFC3339),
	})
}

// UpdateItemKitchenStatus updates the kitchen_status of a single order item
func UpdateItemKitchenStatus(itemID, status string) error {
	return db.DB.Update("order_items", "id=eq."+itemID, map[string]interface{}{
		"kitchen_status": status,
	})
}

// UpdateItemsPaymentStatus updates the payment_status for multiple order items
func UpdateItemsPaymentStatus(itemIDs []string, status string) error {
	if len(itemIDs) == 0 {
		return nil
	}
	// PostgREST IN filter: id=in.(id1,id2,...)
	inList := "("
	for i, id := range itemIDs {
		if i > 0 {
			inList += ","
		}
		inList += id
	}
	inList += ")"
	return db.DB.Update("order_items", "id=in."+inList, map[string]interface{}{
		"payment_status": status,
	})
}
