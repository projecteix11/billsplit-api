import pytest
from unittest.mock import patch, MagicMock
from app.models import NewOrderItem
from app.services.stock import deduct_stock_for_items, restore_stock_for_items
from tests.conftest import make_mock_client, VALID_TENANT_ID

def test_deduct_stock_for_items_no_customization():
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
        if table_name not in table_builders:
            table_builders[table_name] = make_mock_client()
            
        builder = table_builders[table_name]
        
        def mock_execute():
            if table_name == "dish_ingredients":
                return MagicMock(data=dish_ing_data)
            elif table_name == "stock_items":
                name_queries = [c[0][1] for c in builder.eq.call_args_list if len(c[0]) > 1 and c[0][0] == "name"]
                if name_queries:
                    last_name = name_queries[-1]
                    if last_name == "Dough":
                        return MagicMock(data=stock_rows_dough)
                    elif last_name == "Cheese":
                        return MagicMock(data=stock_rows_cheese)
            return MagicMock(data=[])
            
        builder.execute.side_effect = mock_execute
        return builder

    mock_client.table.side_effect = mock_table
    
    with patch("app.services.stock.get_client", return_value=mock_client):
        deduct_stock_for_items(items, VALID_TENANT_ID)
        
    stock_builder = table_builders.get("stock_items")
    assert stock_builder is not None
    update_calls = stock_builder.update.call_args_list
    assert len(update_calls) == 2
    # Quantities: 10 - 2 = 8, 5 - 2 = 3
    assert {"current_quantity": 8.0} in [c[0][0] for c in update_calls]
    assert {"current_quantity": 3.0} in [c[0][0] for c in update_calls]

def test_deduct_stock_skips_removed_ingredients():
    items = [
        NewOrderItem(
            dish_name="Pizza",
            dish_price=10.0,
            quantity=2.0,
            dish_id="dish-pizza",
            customization={
                "removed_ingredients": ["ing-cheese"]
            }
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
        if table_name not in table_builders:
            table_builders[table_name] = make_mock_client()
            
        builder = table_builders[table_name]
        
        def mock_execute():
            if table_name == "dish_ingredients":
                return MagicMock(data=dish_ing_data)
            elif table_name == "stock_items":
                name_queries = [c[0][1] for c in builder.eq.call_args_list if len(c[0]) > 1 and c[0][0] == "name"]
                if name_queries:
                    last_name = name_queries[-1]
                    if last_name == "Dough":
                        return MagicMock(data=stock_rows_dough)
                    elif last_name == "Cheese":
                        return MagicMock(data=stock_rows_cheese)
            return MagicMock(data=[])
            
        builder.execute.side_effect = mock_execute
        return builder

    mock_client.table.side_effect = mock_table
    
    with patch("app.services.stock.get_client", return_value=mock_client):
        deduct_stock_for_items(items, VALID_TENANT_ID)
        
    stock_builder = table_builders.get("stock_items")
    assert stock_builder is not None
    update_calls = stock_builder.update.call_args_list
    assert len(update_calls) == 1
    # Only dough should be updated: 10 - 2 = 8
    assert update_calls[0][0][0] == {"current_quantity": 8.0}
    # Cheese should NOT be updated in stock_items name queries
    name_queries = [c[0][1] for c in stock_builder.eq.call_args_list if len(c[0]) > 1 and c[0][0] == "name"]
    assert "Cheese" not in name_queries

def test_restore_stock_for_items_no_customization():
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
    
    stock_rows_dough = [{"id": "stock-dough", "current_quantity": 8.0}]
    stock_rows_cheese = [{"id": "stock-cheese", "current_quantity": 3.0}]
    
    table_builders = {}
    
    def mock_table(table_name):
        if table_name not in table_builders:
            table_builders[table_name] = make_mock_client()
            
        builder = table_builders[table_name]
        
        def mock_execute():
            if table_name == "dish_ingredients":
                return MagicMock(data=dish_ing_data)
            elif table_name == "stock_items":
                name_queries = [c[0][1] for c in builder.eq.call_args_list if len(c[0]) > 1 and c[0][0] == "name"]
                if name_queries:
                    last_name = name_queries[-1]
                    if last_name == "Dough":
                        return MagicMock(data=stock_rows_dough)
                    elif last_name == "Cheese":
                        return MagicMock(data=stock_rows_cheese)
            return MagicMock(data=[])
            
        builder.execute.side_effect = mock_execute
        return builder

    mock_client.table.side_effect = mock_table
    
    with patch("app.services.stock.get_client", return_value=mock_client):
        restore_stock_for_items(items, VALID_TENANT_ID)
        
    stock_builder = table_builders.get("stock_items")
    assert stock_builder is not None
    update_calls = stock_builder.update.call_args_list
    assert len(update_calls) == 2
    # Quantities: 8 + 2 = 10, 3 + 2 = 5
    assert {"current_quantity": 10.0} in [c[0][0] for c in update_calls]
    assert {"current_quantity": 5.0} in [c[0][0] for c in update_calls]

def test_restore_stock_skips_removed_ingredients():
    items = [
        NewOrderItem(
            dish_name="Pizza",
            dish_price=10.0,
            quantity=2.0,
            dish_id="dish-pizza",
            customization={
                "removed_ingredients": ["ing-cheese"]
            }
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
    
    stock_rows_dough = [{"id": "stock-dough", "current_quantity": 8.0}]
    stock_rows_cheese = [{"id": "stock-cheese", "current_quantity": 3.0}]
    
    table_builders = {}
    
    def mock_table(table_name):
        if table_name not in table_builders:
            table_builders[table_name] = make_mock_client()
            
        builder = table_builders[table_name]
        
        def mock_execute():
            if table_name == "dish_ingredients":
                return MagicMock(data=dish_ing_data)
            elif table_name == "stock_items":
                name_queries = [c[0][1] for c in builder.eq.call_args_list if len(c[0]) > 1 and c[0][0] == "name"]
                if name_queries:
                    last_name = name_queries[-1]
                    if last_name == "Dough":
                        return MagicMock(data=stock_rows_dough)
                    elif last_name == "Cheese":
                        return MagicMock(data=stock_rows_cheese)
            return MagicMock(data=[])
            
        builder.execute.side_effect = mock_execute
        return builder

    mock_client.table.side_effect = mock_table
    
    with patch("app.services.stock.get_client", return_value=mock_client):
        restore_stock_for_items(items, VALID_TENANT_ID)
        
    stock_builder = table_builders.get("stock_items")
    assert stock_builder is not None
    update_calls = stock_builder.update.call_args_list
    assert len(update_calls) == 1
    # Only dough should be updated: 8 + 2 = 10
    assert update_calls[0][0][0] == {"current_quantity": 10.0}
    # Cheese should NOT be updated in name queries
    name_queries = [c[0][1] for c in stock_builder.eq.call_args_list if len(c[0]) > 1 and c[0][0] == "name"]
    assert "Cheese" not in name_queries
