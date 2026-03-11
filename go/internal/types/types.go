package types

// Dish represents a menu item
type Dish struct {
	ID          string  `json:"id"`
	Name        string  `json:"name"`
	Description string  `json:"description"`
	Price       float64 `json:"price"`
	IsAvailable bool    `json:"is_available"`
	CategoryID  string  `json:"category_id"`
}

// DishCategory represents a menu category
type DishCategory struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	SortOrder int    `json:"sort_order"`
}

// OrderItem represents a single item in an order
type OrderItem struct {
	ID            string  `json:"id"`
	OrderID       string  `json:"order_id"`
	DishName      string  `json:"dish_name"`
	DishPrice     float64 `json:"dish_price"`
	Quantity      int     `json:"quantity"`
	Notes         *string `json:"notes"`
	DinerName     string  `json:"diner_name"`
	KitchenStatus string  `json:"kitchen_status"`
	PaymentStatus string  `json:"payment_status"`
}

// Order represents a table order
type Order struct {
	ID          string      `json:"id"`
	TableID     string      `json:"table_id"`
	TableNumber int         `json:"table_number"`
	Status      string      `json:"status"`
	Subtotal    float64     `json:"subtotal"`
	TaxAmount   float64     `json:"tax_amount"`
	Total       float64     `json:"total"`
	CreatedAt   string      `json:"created_at"`
	UpdatedAt   string      `json:"updated_at"`
	Items       []OrderItem `json:"items"`
}

// NewOrderItem is the payload for adding items to an order
type NewOrderItem struct {
	DishName  string  `json:"dish_name"`
	DishPrice float64 `json:"dish_price"`
	Quantity  int     `json:"quantity"`
	Notes     *string `json:"notes"`
	DinerName *string `json:"diner_name"`
}

// Payment represents a payment record
type Payment struct {
	ID            string  `json:"id"`
	OrderID       string  `json:"order_id"`
	Amount        float64 `json:"amount"`
	TipAmount     float64 `json:"tip_amount"`
	TotalCharged  float64 `json:"total_charged"`
	PaymentMethod string  `json:"payment_method"`
	Status        string  `json:"status"`
}

// APIResponse is the standard envelope for all responses
type APIResponse struct {
	Data  interface{} `json:"data"`
	Error *string     `json:"error"`
}
