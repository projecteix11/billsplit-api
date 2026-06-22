import sys
sys.path.append("/Users/roger/Documents/app/gobbly/billsplit-api")

from unittest.mock import patch, MagicMock
from app.models import NewOrderItem
from app.services.stock import deduct_stock_for_items
from tests.conftest import make_mock_client, VALID_TENANT_ID

items = [
    NewOrderItem(
        dish_name="Pizza",
        dish_price=10.0,
        quantity=2.0,
        dish_id="dish-pizza",
    )
]

mock_client = make_mock_client()

dish_ing_data = [
    {
        "ingredient_id": "ing-dough",
        "ingredient": {"id": "ing-dough", "name": "Dough"}
    },
    {
        "ingredient_id": "ing-cheese",
        "ingredient": {"id": "ing-cheese", "name": "Cheese"}
    }
]

stock_rows_dough = [{"id": "stock-dough", "current_quantity": 10.0}]
stock_rows_cheese = [{"id": "stock-cheese", "current_quantity": 5.0}]

table_builders = {}

def mock_table(table_name):
    print(f"DEBUG: table called with: {table_name}")
    if table_name not in table_builders:
        table_builders[table_name] = make_mock_client()
        
    builder = table_builders[table_name]
    
    def mock_execute():
        print(f"DEBUG: execute called on table: {table_name}")
        if table_name == "dish_ingredients":
            print(f"DEBUG: returning dish_ingredients: {dish_ing_data}")
            return MagicMock(data=dish_ing_data)
        elif table_name == "stock_items":
            name_queries = [c[0][1] for c in builder.eq.call_args_list if len(c[0]) > 1 and c[0][0] == "name"]
            print(f"DEBUG: stock_items name queries: {name_queries}")
            if name_queries:
                last_name = name_queries[-1]
                if last_name == "Dough":
                    print(f"DEBUG: returning stock_rows_dough: {stock_rows_dough}")
                    return MagicMock(data=stock_rows_dough)
                elif last_name == "Cheese":
                    print(f"DEBUG: returning stock_rows_cheese: {stock_rows_cheese}")
                    return MagicMock(data=stock_rows_cheese)
        print("DEBUG: returning default empty list")
        return MagicMock(data=[])
        
    builder.execute.side_effect = mock_execute
    return builder

mock_client.table.side_effect = mock_table

with patch("app.services.stock.get_client", return_value=mock_client):
    deduct_stock_for_items(items, VALID_TENANT_ID)

print(f"DEBUG: table_builders: {list(table_builders.keys())}")
if "stock_items" in table_builders:
    stock_builder = table_builders["stock_items"]
    print(f"DEBUG: stock_items update call_args_list: {stock_builder.update.call_args_list}")
