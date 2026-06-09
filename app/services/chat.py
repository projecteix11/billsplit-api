from __future__ import annotations

import json
import os
import time
import unicodedata
from typing import Any, Generator

import httpx as http

from app.db.supabase import get_client
from app.logging import log_event, LogFactory
from app.models import NewOrderItem
from app.services import dishes as dish_svc
from app.services import daily_menus as daily_menu_svc
from app.services import orders as order_svc


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    return "".join(c for c in text if c.isalnum())

# -- LLM config ---------------------------------------------------------------

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
DEFAULT_MODEL   = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

AVAILABLE_MODELS: list[dict[str, Any]] = [
    {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B (Groq - Recomendado)", "free": True, "tool_calling": "stable"},
    {"id": "llama-3.1-8b-instant",     "name": "Llama 3.1 8B (Groq - Rápido)",       "free": True, "tool_calling": "stable"},
    {"id": "gemini-2.5-flash",        "name": "Gemini 2.5 Flash (Cloud)",           "free": True, "tool_calling": "stable"},
    {"id": "gemini-2.5-pro",          "name": "Gemini 2.5 Pro (Cloud)",             "free": False, "tool_calling": "stable"},
]


def _api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return key


def _llm_request(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Send a chat completion request to Groq API or Gemini API."""
    selected_model = model or DEFAULT_MODEL

    # Sanitize model parameter to prevent local Ollama routing
    if selected_model.startswith("ollama/"):
        selected_model = DEFAULT_MODEL

    body: dict[str, Any] = {"model": selected_model, "messages": messages}
    if tools:
        body["tools"] = tools

    # Route based on model ID prefix
    if selected_model.startswith("gemini-"):
        primary_key = _api_key()
        fallback_key = os.getenv("GEMINI_API_KEY_FALLBACK", "")

        # Try primary key first, with up to 3 retries on transient errors (429, 502, 503, 504)
        for attempt in range(3):
            try:
                resp = http.post(
                    GEMINI_URL,
                    headers={
                        "Authorization": f"Bearer {primary_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=30,
                )
                resp.raise_for_status()
                return resp.json()
            except http.HTTPStatusError as e:
                if e.response.status_code in (429, 502, 503, 504):
                    if attempt < 2:
                        time.sleep(2.5)
                        continue
                    if fallback_key:
                        break
                raise e

        # Try fallback key, with up to 3 retries on transient errors (429, 502, 503, 504)
        for attempt in range(3):
            try:
                resp = http.post(
                    GEMINI_URL,
                    headers={
                        "Authorization": f"Bearer {fallback_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=30,
                )
                resp.raise_for_status()
                return resp.json()
            except http.HTTPStatusError as e:
                if e.response.status_code in (429, 502, 503, 504):
                    if attempt < 2:
                        time.sleep(2.5)
                        continue
                raise e
    else:
        # Route to Groq API
        groq_key = os.getenv("GROQ_API_KEY", "")
        if not groq_key:
            raise RuntimeError("GROQ_API_KEY not set in .env")

        # Try Groq API, with up to 3 retries on transient errors (e.g. rate limits)
        for attempt in range(3):
            try:
                resp = http.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=30,
                )
                resp.raise_for_status()
                return resp.json()
            except http.HTTPStatusError as e:
                if e.response.status_code in (429, 502, 503, 504):
                    if attempt < 2:
                        time.sleep(2.5)
                        continue
                raise e



# -- System prompt -------------------------------------------------------------

SYSTEM_PROMPT = (
    "Eres el asistente virtual del restaurante. Tu UNICO proposito es ayudar con:\n"
    "- Consultar el menu, platos, categorias y alergenos\n"
    "- Gestionar pedidos (crear, anadir items, modificar, consultar estado)\n"
    "- Informacion sobre mesas disponibles y ocupadas\n"
    "- Consultar niveles de stock/inventario de ingredientes o articulos\n"
    "- Obtener resumenes de facturacion y cierre de caja del dia\n"
    "\n"
    "PROCESO OBLIGATORIO PARA CADA PLATO (seguir en orden estricto):\n"
    "1. search_menu(query) → buscar coincidencias\n"
    "2. Si count>=2 → listar opciones y ESPERAR a que el usuario elija\n"
    "3. Si count=1 → get_dish_details para ver extras\n"
    "4. Si tiene extras → mostrar opciones y ESPERAR a que el usuario decida\n"
    "5. Solo cuando todo esta confirmado → add_items_to_order o create_order\n"
    "\n"
    "PEDIDOS MULTIPLES:\n"
    "Si el usuario pide VARIOS platos a la vez (ej: 'una nolita y una coca cola'), "
    "procesa cada plato UNO A UNO siguiendo el proceso de arriba. "
    "Primero resuelve completamente el primer plato (disambiguation + extras), "
    "luego el segundo, y asi sucesivamente. "
    "Cuando TODOS los platos esten resueltos, anadilos TODOS juntos en una sola llamada.\n"
    "\n"
    "REGLA DE CANTIDADES:\n"
    "Cuando el usuario dice 'un/una/1', la cantidad es 1. 'Dos/2' es 2, etc. "
    "NUNCA vuelvas a preguntar la cantidad si el usuario ya la indico.\n"
    "\n"
    "REGLA DE EXTRAS YA ESPECIFICADOS:\n"
    "Si el usuario ya indica el tamaño o extra en su peticion (ej: 'nolita mida M', "
    "'burger con extra queso'), NO vuelvas a preguntar por esos extras. "
    "Verifica con get_dish_details que el extra existe y anadelo directamente.\n"
    "Solo pregunta por extras si el usuario NO los ha especificado y el plato los tiene.\n"
    "Si get_dish_details muestra que un plato NO tiene extras ni ingredientes, "
    "NO inventes tamaños ni opciones. Anadelo directamente.\n"
    "Si el usuario pide un extra que NO coincide con ninguno de los disponibles en get_dish_details, "
    "NO lo ignores ni lo inventes. Dile que ese extra no esta disponible y muestrale los extras reales.\n"
    "\n"
    "Reglas:\n"
    "- Si el usuario pide algo fuera del contexto del restaurante, responde amablemente "
    "que solo puedes ayudar con el servicio del restaurante.\n"
    "- OBLIGATORIO: SIEMPRE llama a get_dish_details ANTES de llamar a create_order o add_items_to_order. "
    "Si el plato tiene ingredientes extra disponibles, muestralos al usuario con el precio y pregunta "
    "si quiere alguno. Si no tiene extras, anadelo directamente. "
    "NUNCA hagas create_order o add_items_to_order sin haber llamado a get_dish_details primero.\n"
    "- NUNCA ofrezcas cerrar el pedido ni la mesa. Tu unico rol es tomar pedidos y consultar el menu. "
    "El cierre lo gestiona el camarero desde el sistema.\n"
    "- Despues de anadir items, responde con lo que se ha anadido y pregunta '¿Algo mas?' de forma natural.\n"
    "- Cuando crees un pedido (create_order), el resultado incluye un menu_path. "
    "Incluye el link en tu respuesta asi: [QR:menu_path] para que el cliente pueda escanear el QR y ver el menu. "
    "Ejemplo: 'Pedido creado para la mesa 3. [QR:/menu/uuid-de-mesa] ¿Algo mas?'\n"
    "- Responde en el mismo idioma que el usuario.\n"
    "- Se conciso y directo.\n"
    "\n"
    "BOTONES INTERACTIVOS:\n"
    "Puedes añadir botones interactivos en tus respuestas utilizando el formato exacto: [BUTTON:Texto del Botón:Mensaje de chat a enviar]\n"
    "Utiliza esto para facilitar la experiencia del usuario:\n"
    "- Al listar platos (ej: hamburguesas): pon un botón al lado de cada una para añadirla. Si no sabes la mesa actual, el mensaje del botón debe ser 'Añadir [nombre_plato]'. Si conoces la mesa, por ejemplo mesa 4, el mensaje debe ser 'Añadir 1 [nombre_plato] a la mesa 4'.\n"
    "- Al confirmar que has añadido un plato: pon botones para quitarlo o modificar la cantidad. Ejemplo: '[BUTTON:Quitar 1:Quitar 1 [nombre_plato] de la mesa 4]' o '[BUTTON:Modificar:Cambiar cantidad de [nombre_plato] en la mesa 4 a 2]'.\n"
    "- Al listar mesas o dar información de una mesa: pon botones para consultarla o abrirla. Ejemplo: '[BUTTON:Ver Mesa 4:qué hay en la mesa 4]' o '[BUTTON:Abrir Mesa 4:abre la mesa 4]'.\n"
    "- Cuando el usuario no especifique la mesa para un pedido, además de preguntarle, lístale las mesas disponibles con botones para elegir. Ejemplo: 'Mesa 4: [BUTTON:Elegir:mesa 4]'.\n"
    "\n"
    "PROCESO PARA QUITAR O MODIFICAR PLATOS DE UNA MESA:\n"
    "Cuando el usuario pida quitar, eliminar o cambiar la cantidad de un plato de una mesa (por ejemplo, al hacer clic en los botones de Quitar o Modificar):\n"
    "1. Llama a get_tables() para obtener la lista de mesas y busca el table_id correspondiente al número de la mesa.\n"
    "2. Llama a get_table_order(table_id) para obtener la orden activa de esa mesa y su lista de order_items.\n"
    "3. Busca en la lista de items el que tenga el nombre del plato indicado (comparando de forma flexible o parcial) y obtén su 'id' (este es el item_id).\n"
    "4. Si el usuario quiere QUITAR por completo el plato (o restar todas las unidades de manera que queden 0):\n"
    "   Llama a delete_order_item(item_id).\n"
    "5. Si el usuario quiere MODIFICAR la cantidad a un nuevo valor mayor que 0:\n"
    "   Llama a update_item_quantity(item_id, nueva_cantidad).\n"
    "6. Informa de forma natural y clara que el cambio se ha completado y muestra botones de confirmación correspondientes.\n"
    "\n"
    "Resolucion de mesas:\n"
    "- Si el usuario quiere hacer un pedido y NO ha indicado mesa, preguntale: '¿Para que mesa?'\n"
    "- Cuando el usuario diga un NUMERO de mesa (ej: 'mesa 1', 'mesa 3'), usa get_tables "
    "para obtener la lista de mesas y busca la que tenga ese 'number'. "
    "Usa el campo 'id' (UUID) como table_id para todas las operaciones.\n"
    "- NUNCA pidas al usuario un ID de mesa ni un UUID. Tu resuelves el numero a ID internamente.\n"
    "- Cuando el usuario diga 'abre la mesa X' o 'abre mesa X', usa get_tables para resolver "
    "el table_id, luego llama a open_table. El resultado incluye menu_path — "
    "incluye el link en tu respuesta asi: [QR:menu_path]\n"
    "\n"
    "Resolucion de platos:\n"
    "- Cuando uses get_dish_details, el resultado incluye dish_id, category_id, precio, "
    "ingredientes y alergenos. Usa TODOS esos datos al crear el pedido.\n"
    "- NUNCA preguntes al usuario por la categoria. El category_id se obtiene del detalle del plato.\n"
    "- Al llamar create_order o add_items_to_order, incluye siempre: dish_id, dish_name, "
    "dish_price, quantity, y category_id del plato.\n"
    "- Al buscar platos, la regla de disambiguation de arriba es OBLIGATORIA."
)

# -- Tool definitions (OpenAI function calling format) -------------------------

TOOLS: list[dict[str, Any]] = [
    # Read tools
    {
        "type": "function",
        "function": {
            "name": "get_tables",
            "description": "Get all restaurant tables. Returns array of {id, number, status, active_order_id}. Use 'number' to match what the user says (e.g. 'mesa 1' = number:1) and 'id' as table_id for all other operations.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_table",
            "description": "Open a table for customers. Returns the menu_path for QR code generation. Use when the user says 'abre la mesa X' or 'abre mesa X'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {"type": "string", "description": "The table UUID"},
                    "table_number": {"type": "integer", "description": "The table number"},
                },
                "required": ["table_id", "table_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_menu",
            "description": "Get all available dishes. Use search_menu instead when looking for a specific dish by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category_id": {
                        "type": "string",
                        "description": "Filter dishes by category ID",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_menu",
            "description": "Search dishes by name (case-insensitive partial match). ALWAYS use this when the user asks for a specific dish. Returns all matches — if there are 2+ results, you MUST ask the user to choose.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term (e.g. 'coca cola', 'new york', 'nolita')",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dish_details",
            "description": "Get full dish details: dish_id, category_id, price, allergens, and ingredients (default + extras with prices). Use the returned dish_id and category_id when creating orders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dish_id": {"type": "string", "description": "The dish ID"},
                },
                "required": ["dish_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_categories",
            "description": "List all active dish categories.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_allergens",
            "description": "List all allergens.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_daily_menus",
            "description": "Get active daily menus with sections and items.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_table_order",
            "description": "Get the open order for a specific table.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {"type": "string", "description": "The table ID"},
                },
                "required": ["table_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "Get order details by order ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The order ID"},
                },
                "required": ["order_id"],
            },
        },
    },
    # Write tools
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": "Create a new order for a table. Returns order details including menu_path for the customer QR code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {"type": "string", "description": "The table ID"},
                    "table_number": {"type": "integer", "description": "The table number"},
                    "items": {
                        "type": "array",
                        "description": "List of items to order",
                        "items": {
                            "type": "object",
                            "properties": {
                                "dish_name": {"type": "string"},
                                "dish_price": {"type": "number"},
                                "quantity": {"type": "integer"},
                                "notes": {"type": "string"},
                                "diner_name": {"type": "string"},
                                "dish_id": {"type": "string"},
                                "category_id": {"type": "string"},
                            },
                            "required": ["dish_name", "dish_price", "quantity"],
                        },
                    },
                },
                "required": ["table_id", "table_number", "items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_items_to_order",
            "description": "Add items to an existing order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The order ID"},
                    "items": {
                        "type": "array",
                        "description": "List of items to add",
                        "items": {
                            "type": "object",
                            "properties": {
                                "dish_name": {"type": "string"},
                                "dish_price": {"type": "number"},
                                "quantity": {"type": "integer"},
                                "notes": {"type": "string"},
                                "diner_name": {"type": "string"},
                                "dish_id": {"type": "string"},
                                "category_id": {"type": "string"},
                            },
                            "required": ["dish_name", "dish_price", "quantity"],
                        },
                    },
                },
                "required": ["order_id", "items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_item_quantity",
            "description": "Update the quantity of an order item.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "The order item ID"},
                    "quantity": {"type": "integer", "description": "New quantity"},
                },
                "required": ["item_id", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_order_item",
            "description": "Delete an item from an order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "The order item ID"},
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_kitchen_status",
            "description": "Update the kitchen status of an order item (pending, cooking, ready, delivered).",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "The order item ID"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "cooking", "ready", "delivered"],
                        "description": "New kitchen status",
                    },
                },
                "required": ["item_id", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": "Check the current stock/inventory quantity for one or all items in the restaurant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Filter by item name (optional, case-insensitive partial match). If omitted, returns all stock items."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_billing_summary",
            "description": "Get today's total billing summary (cash closure / tancament de caixa) grouped by payment method.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    }
]


# -- Tool execution ------------------------------------------------------------


def _resolve_category_ids(items: list[Any]) -> list[dict[str, Any]]:
    """Resolve category_id from dish_id server-side to avoid FK errors from LLM hallucination."""
    normalized_items = []
    if not isinstance(items, list):
        return []
    for item in items:
        if isinstance(item, str):
            item = {"dish_name": item, "dish_price": 0.0, "quantity": 1}
        elif not isinstance(item, dict):
            continue

        # Ensure required fields for NewOrderItem are present
        if "dish_name" not in item or not item["dish_name"]:
            item["dish_name"] = "Artículo"
        if "dish_price" not in item or item["dish_price"] is None:
            item["dish_price"] = 0.0
        if "quantity" not in item or item["quantity"] is None:
            item["quantity"] = 1

        dish_id = item.get("dish_id")
        if dish_id:
            rows = get_client().table("dishes").select("category_id").eq("id", dish_id).execute().data or []
            if rows:
                item["category_id"] = rows[0].get("category_id")
            else:
                item.pop("category_id", None)
        else:
            item.pop("category_id", None)
        normalized_items.append(item)
    return normalized_items


def _execute_tool(name: str, args: dict[str, Any], tenant_id: str | None = None) -> str:
    """Execute a tool call and return the JSON-serialized result."""
    try:
        result = _dispatch_tool(name, args, tenant_id)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _dispatch_tool(name: str, args: dict[str, Any], tenant_id: str | None = None) -> Any:
    """Route tool name to the appropriate service call."""

    if name == "get_tables":
        q = get_client().table("restaurant_tables").select("id,number,status,active_order_id").order("number")
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        rows = q.execute().data or []
        return rows

    if name == "open_table":
        table_id = args["table_id"]
        table_number = args["table_number"]
        q = get_client().table("restaurant_tables").update({"status": "waiting_order"}).eq("id", table_id)
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        q.execute()
        return {"_refresh": True, "menu_path": f"/menu/{table_id}?num={table_number}", "message": f"Mesa {table_number} abierta"}

    if name == "get_menu":
        dishes = dish_svc.get_dishes(tenant_id) if tenant_id else []
        category_id = args.get("category_id")
        if category_id:
            dishes = [d for d in dishes if d.category_id == category_id]
        return [d.model_dump() for d in dishes]

    if name == "search_menu":
        query = args.get("query", "").strip()
        q = get_client().table("dishes").select("id,name,price,category_id").eq("is_available", True)
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        rows = q.execute().data or []
        
        if not rows:
            return {"matches": [], "count": 0, "message": f"No dishes found matching '{query}'"}

        stop_words = {"un", "una", "unos", "unas", "el", "la", "los", "las", "de", "del", "y", "o", "con", "para", "por", "tambien", "mes", "mesa", "taula", "mesas"}
        raw_words = query.lower().replace("-", " ").split()
        search_words = [normalize_text(w) for w in raw_words if normalize_text(w) and normalize_text(w) not in stop_words]
        
        if not search_words:
            search_words = [normalize_text(w) for w in raw_words if normalize_text(w)]

        normalized_query_full = normalize_text(query)
        matches = []
        for r in rows:
            dish_name = r["name"]
            norm_dish = normalize_text(dish_name)
            is_match = (
                (normalized_query_full and normalized_query_full in norm_dish) or
                (norm_dish and norm_dish in normalized_query_full) or
                any(w in norm_dish for w in search_words)
            )
            if is_match:
                matches.append({
                    "name": dish_name,
                    "id": r["id"],
                    "price": r["price"],
                    "category_id": r["category_id"]
                })

        if not matches:
            return {"matches": [], "count": 0, "message": f"No dishes found matching '{query}'"}
        return {"matches": matches, "count": len(matches)}

    if name == "get_dish_details":
        dish = dish_svc.get_dish_by_id(args["dish_id"])
        if dish is None:
            return {"error": "Dish not found"}
        return dish.model_dump()

    if name == "get_categories":
        cats = dish_svc.get_categories(tenant_id) if tenant_id else []
        return [c.model_dump() for c in cats]

    if name == "get_allergens":
        allergens = dish_svc.get_allergens()
        return [a.model_dump() for a in allergens]

    if name == "get_daily_menus":
        menus = daily_menu_svc.get_daily_menus(tenant_id) if tenant_id else []
        return [m.model_dump() for m in menus]

    if name == "get_table_order":
        order = order_svc.get_open_order_for_table(args["table_id"])
        if order is None:
            return {"message": "No open order for this table"}
        return order.model_dump()

    if name == "get_order":
        order = order_svc.get_order_by_id(args["order_id"])
        if order is None:
            return {"error": "Order not found"}
        return order.model_dump()

    if name == "create_order":
        items = [NewOrderItem(**item) for item in _resolve_category_ids(args["items"])]
        order = order_svc.create_order(args["table_id"], args["table_number"], items, tenant_id=tenant_id or "")
        return {"_refresh": True, "menu_path": f"/menu/{args['table_id']}?num={args['table_number']}", **order.model_dump()}

    if name == "add_items_to_order":
        items = [NewOrderItem(**item) for item in _resolve_category_ids(args["items"])]
        order_svc.add_items_to_order(args["order_id"], items)
        return {"_refresh": True, "message": "Items added successfully"}

    if name == "update_item_quantity":
        order_svc.update_order_item_quantity(args["item_id"], args["quantity"], tenant_id=tenant_id or "")
        return {"message": "Quantity updated"}

    if name == "delete_order_item":
        order_svc.delete_order_item(args["item_id"], tenant_id=tenant_id or "")
        return {"message": "Item deleted"}

    if name == "update_kitchen_status":
        order_svc.update_item_kitchen_status(args["item_id"], args["status"], tenant_id=tenant_id or "")
        return {"message": f"Kitchen status updated to {args['status']}"}

    if name == "check_stock":
        query = args.get("query", "").strip()
        q = get_client().table("stock_items").select("name,current_quantity,min_quantity,unit").eq("is_active", True)
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        if query:
            q = q.ilike("name", f"*{query}*")
        rows = q.execute().data or []
        return [
            {
                "name": r["name"],
                "current_quantity": float(r["current_quantity"]),
                "min_quantity": float(r["min_quantity"]),
                "unit": r["unit"],
                "status": "low_stock" if float(r["current_quantity"]) <= float(r["min_quantity"]) else "ok"
            }
            for r in rows
        ]

    if name == "get_billing_summary":
        from datetime import date
        today_iso = date.today().isoformat()
        
        q_orders = get_client().table("orders").select("id,total,status,amount_paid").gte("created_at", f"{today_iso}T00:00:00")
        if tenant_id:
            q_orders = q_orders.eq("tenant_id", tenant_id)
        orders_today = q_orders.execute().data or []
        
        order_ids = [o["id"] for o in orders_today]
        if order_ids:
            payments_today = get_client().table("payments").select("amount,payment_method,status").in_("order_id", order_ids).eq("status", "completed").execute().data or []
        else:
            payments_today = []
        
        total_sales = sum(float(o["total"]) for o in orders_today)
        total_paid = sum(float(o["amount_paid"]) for o in orders_today)
        
        by_method = {}
        for p in payments_today:
            method = p["payment_method"]
            amt = float(p["amount"])
            by_method[method] = by_method.get(method, 0.0) + amt
            
        return {
            "date": today_iso,
            "total_sales_created": total_sales,
            "total_paid": total_paid,
            "payments_by_method": by_method,
            "orders_count": len(orders_today)
        }

    return {"error": f"Unknown tool: {name}"}


# -- Streaming chat orchestration ----------------------------------------------

MAX_TOOL_ROUNDS = 5


WEB_FEATURES_PROMPT = """
Informació sobre l'aplicació Gobbly (pots explicar-la als usuaris si ho pregunten):
- MENÚ: gestió de plats per categories, amb preus, al·lèrgens i ingredients extra. Es pot activar/desactivar plats.
- COMANDES: des de la pàgina de comandes es veuen les comandes actives per mesa, amb l'estat de cada plat (pendent, cuinant, llest, servit).
- MESES: gestió de l'estat de les meses (lliure, ocupada). Es pot obrir una mesa i generar un QR perquè els clients facin la seva pròpia comanda.
- PAGAMENTS: des de la comanda es pot cobrar amb targeta (TPV), efectiu o altres mètodes configurats.
- STOCK: control d'inventari dels ingredients.
- PLANTILLA: menús del dia configurables per seccions i plats.
- CONFIGURACIÓ: idioma, aparença (tema clar/fosc), mòduls, impressores, personal i assistent IA.
- MARKETPLACE: portal per demanar productes als proveïdors directament des de l'app.
Quan l'usuari pregunti com funciona qualsevol d'aquestes seccions, explica-la de manera clara i concisa.
"""

KITCHEN_EXTRA_PROMPT = """
Mode cuina activat: pots ajudar el personal de cuina a consultar i actualitzar l'estat dels plats.
Quan et demanin actualitzar l'estat d'un plat, usa update_kitchen_status amb els valors: pending, cooking, ready, delivered.
"""


def stream_chat(
    message: str,
    conversation_history: list[dict[str, str]],
    table_id: str | None = None,
    order_id: str | None = None,
    model: str | None = None,
    features_kitchen: bool = False,
    features_web: bool = False,
    device_context: dict[str, Any] | None = None,
    tenant_id: str | None = None,
) -> Generator[str, None, None]:
    """Orchestrate the LLM chat with tool calling, yielding SSE events."""

    # Build messages
    system_content = SYSTEM_PROMPT
    if features_kitchen:
        system_content += KITCHEN_EXTRA_PROMPT
    if features_web:
        system_content += WEB_FEATURES_PROMPT
    if device_context:
        printer_name = device_context.get("printer_name")
        printer_online = device_context.get("printer_online")
        if printer_name:
            status_str = "CONECTADA" if printer_online else "DESCONECTADA"
            system_content += f"\n\n[Contexto Dispositivo]: La impresora térmica vinculada es '{printer_name}' (Estado: {status_str}). Si el usuario tiene problemas para imprimir, indícale este estado y que compruebe la conexión en Configuración > Impresoras."
        else:
            system_content += f"\n\n[Contexto Dispositivo]: No hay ninguna impresora vinculada actualmente en el panel."
    if table_id:
        system_content += f"\n\nContexto: el usuario esta en la mesa con ID {table_id}."
    if order_id:
        system_content += f"\nPedido activo: {order_id}."

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]

    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": message})

    # Tool-calling loop
    for _round in range(MAX_TOOL_ROUNDS):
        try:
            data = _llm_request(messages, tools=TOOLS, model=model)
        except Exception as e:
            yield _sse("error", {"message": f"LLM error: {str(e)}"})
            yield _sse("done", {})
            return

        choice = data.get("choices", [{}])[0]
        assistant_msg = choice.get("message", {})

        tool_calls = assistant_msg.get("tool_calls")
        if not tool_calls:
            content = assistant_msg.get("content", "")
            if content:
                yield _sse("message", {"content": content})
            yield _sse("done", {})
            return

        # Append assistant message with tool_calls to context
        messages.append(assistant_msg)

        for tc in tool_calls:
            fn = tc.get("function", {})
            fn_name = fn.get("name", "")
            try:
                fn_args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                fn_args = {}

            yield _sse("tool_call", {"tool": fn_name, "status": "executing"})

            log_event(LogFactory.order_lifecycle(
                "chat_tool_call", "",
                metadata={"tool": fn_name, "args": fn_args},
            ))

            result = _execute_tool(fn_name, fn_args, tenant_id)

            # Emit refresh event if a write tool modified order/table state
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and parsed.pop("_refresh", False):
                    result = json.dumps(parsed, ensure_ascii=False, default=str)
                    yield _sse("order_updated", {})
            except (json.JSONDecodeError, TypeError):
                pass

            yield _sse("tool_call", {"tool": fn_name, "status": "done"})

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result,
            })

    # Exhausted tool rounds — ask LLM for a final answer without tools
    try:
        data = _llm_request(messages, model=model)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if content:
            yield _sse("message", {"content": content})
    except Exception as e:
        yield _sse("error", {"message": f"LLM error: {str(e)}"})

    yield _sse("done", {})


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
