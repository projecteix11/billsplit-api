from __future__ import annotations

import json
import os
from typing import Any, Generator

import httpx as http

from app.db.supabase import get_client
from app.logging import log_event, LogFactory
from app.models import NewOrderItem
from app.services import dishes as dish_svc
from app.services import daily_menus as daily_menu_svc
from app.services import orders as order_svc

# -- LLM config ---------------------------------------------------------------

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL   = os.getenv("LLM_MODEL", "google/gemma-4-31b-it:free")

AVAILABLE_MODELS: list[dict[str, Any]] = [
    {"id": "google/gemma-4-31b-it:free",                              "name": "Gemma 4 31B",                "free": True, "tool_calling": "stable"},
    {"id": "google/gemma-4-26b-a4b-it:free",                         "name": "Gemma 4 26B A4B",            "free": True, "tool_calling": "stable"},
    {"id": "meta-llama/llama-3.3-70b-instruct:free",                  "name": "Llama 3.3 70B",              "free": True, "tool_calling": "stable"},
    {"id": "meta-llama/llama-3.2-3b-instruct:free",                   "name": "Llama 3.2 3B",               "free": True, "tool_calling": "experimental"},
    {"id": "deepseek/deepseek-v4-flash:free",                         "name": "DeepSeek V4 Flash",          "free": True, "tool_calling": "stable"},
    {"id": "openai/gpt-oss-120b:free",                                "name": "OpenAI OSS 120B",            "free": True, "tool_calling": "stable"},
    {"id": "openai/gpt-oss-20b:free",                                 "name": "OpenAI OSS 20B",             "free": True, "tool_calling": "stable"},
    {"id": "nvidia/nemotron-3-super-120b-a12b:free",                  "name": "NVIDIA Nemotron 3 Super 120B","free": True, "tool_calling": "stable"},
    {"id": "nvidia/nemotron-3-nano-30b-a3b:free",                     "name": "NVIDIA Nemotron Nano 30B",   "free": True, "tool_calling": "stable"},
    {"id": "nvidia/nemotron-nano-12b-v2-vl:free",                     "name": "NVIDIA Nemotron Nano 12B",   "free": True, "tool_calling": "stable"},
    {"id": "nvidia/nemotron-nano-9b-v2:free",                         "name": "NVIDIA Nemotron Nano 9B",    "free": True, "tool_calling": "stable"},
    {"id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",      "name": "NVIDIA Nemotron Omni 30B",   "free": True, "tool_calling": "experimental"},
    {"id": "qwen/qwen3-next-80b-a3b-instruct:free",                   "name": "Qwen3 Next 80B",             "free": True, "tool_calling": "stable"},
    {"id": "qwen/qwen3-coder:free",                                   "name": "Qwen3 Coder 480B",           "free": True, "tool_calling": "stable"},
    {"id": "minimax/minimax-m2.5:free",                               "name": "MiniMax M2.5",               "free": True, "tool_calling": "stable"},
    {"id": "nousresearch/hermes-3-llama-3.1-405b:free",               "name": "Hermes 3 Llama 405B",        "free": True, "tool_calling": "stable"},
    {"id": "arcee-ai/trinity-large-thinking:free",                    "name": "Arcee Trinity Large",        "free": True, "tool_calling": "experimental"},
    {"id": "poolside/laguna-m.1:free",                                "name": "Poolside Laguna M.1",        "free": True, "tool_calling": "stable"},
    {"id": "poolside/laguna-xs.2:free",                               "name": "Poolside Laguna XS.2",       "free": True, "tool_calling": "stable"},
    {"id": "z-ai/glm-4.5-air:free",                                   "name": "GLM 4.5 Air",                "free": True, "tool_calling": "stable"},
    {"id": "inclusionai/ring-2.6-1t:free",                            "name": "Ring 2.6 1T",                "free": True, "tool_calling": "experimental"},
    {"id": "baidu/cobuddy:free",                                      "name": "Baidu CoBuddy",              "free": True, "tool_calling": "experimental"},
    {"id": "liquid/lfm-2.5-1.2b-instruct:free",                      "name": "LFM2.5 1.2B Instruct",       "free": True, "tool_calling": "experimental"},
    {"id": "liquid/lfm-2.5-1.2b-thinking:free",                      "name": "LFM2.5 1.2B Thinking",       "free": True, "tool_calling": "experimental"},
    {"id": "cognitivecomputations/dolphin-mistral-24b-venice-edition:free", "name": "Dolphin Mistral 24B", "free": True, "tool_calling": "experimental"},
]


def _api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    return key


def _llm_request(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Send a chat completion request to OpenRouter and return the JSON response."""
    body: dict[str, Any] = {"model": model or DEFAULT_MODEL, "messages": messages}
    if tools:
        body["tools"] = tools

    resp = http.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# -- System prompt -------------------------------------------------------------

SYSTEM_PROMPT = (
    "Eres el asistente virtual del restaurante. Tu UNICO proposito es ayudar con:\n"
    "- Consultar el menu, platos, categorias y alergenos\n"
    "- Gestionar pedidos (crear, anadir items, modificar, consultar estado)\n"
    "- Informacion sobre mesas disponibles y ocupadas\n"
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
]


# -- Tool execution ------------------------------------------------------------


def _resolve_category_ids(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve category_id from dish_id server-side to avoid FK errors from LLM hallucination."""
    for item in items:
        dish_id = item.get("dish_id")
        if dish_id:
            rows = get_client().table("dishes").select("category_id").eq("id", dish_id).execute().data or []
            if rows:
                item["category_id"] = rows[0].get("category_id")
            else:
                item.pop("category_id", None)
        else:
            item.pop("category_id", None)
    return items


def _execute_tool(name: str, args: dict[str, Any]) -> str:
    """Execute a tool call and return the JSON-serialized result."""
    try:
        result = _dispatch_tool(name, args)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _dispatch_tool(name: str, args: dict[str, Any]) -> Any:
    """Route tool name to the appropriate service call."""

    if name == "get_tables":
        rows = get_client().table("restaurant_tables").select("id,number,status,active_order_id").order("number").execute().data or []
        return rows

    if name == "open_table":
        table_id = args["table_id"]
        table_number = args["table_number"]
        get_client().table("restaurant_tables").update({"status": "waiting_order"}).eq("id", table_id).execute()
        return {"_refresh": True, "menu_path": f"/menu/{table_id}?num={table_number}", "message": f"Mesa {table_number} abierta"}

    if name == "get_menu":
        dishes = dish_svc.get_dishes()
        category_id = args.get("category_id")
        if category_id:
            dishes = [d for d in dishes if d.category_id == category_id]
        return [d.model_dump() for d in dishes]

    if name == "search_menu":
        query = args.get("query", "").strip()
        # Search each word with ilike at DB level — handles hyphens, accents, spacing
        words = query.split()
        q = get_client().table("dishes").select("id,name,price,category_id").eq("is_available", True)
        for w in words:
            q = q.ilike("name", f"*{w}*")
        rows = q.execute().data or []
        if not rows:
            return {"matches": [], "count": 0, "message": f"No dishes found matching '{query}'"}
        return {"matches": [{"name": r["name"], "id": r["id"], "price": r["price"], "category_id": r["category_id"]} for r in rows], "count": len(rows)}

    if name == "get_dish_details":
        dish = dish_svc.get_dish_by_id(args["dish_id"])
        if dish is None:
            return {"error": "Dish not found"}
        return dish.model_dump()

    if name == "get_categories":
        cats = dish_svc.get_categories()
        return [c.model_dump() for c in cats]

    if name == "get_allergens":
        allergens = dish_svc.get_allergens()
        return [a.model_dump() for a in allergens]

    if name == "get_daily_menus":
        menus = daily_menu_svc.get_daily_menus()
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
        order = order_svc.create_order(args["table_id"], args["table_number"], items)
        return {"_refresh": True, "menu_path": f"/menu/{args['table_id']}?num={args['table_number']}", **order.model_dump()}

    if name == "add_items_to_order":
        items = [NewOrderItem(**item) for item in _resolve_category_ids(args["items"])]
        order_svc.add_items_to_order(args["order_id"], items)
        return {"_refresh": True, "message": "Items added successfully"}

    if name == "update_item_quantity":
        order_svc.update_order_item_quantity(args["item_id"], args["quantity"])
        return {"message": "Quantity updated"}

    if name == "delete_order_item":
        order_svc.delete_order_item(args["item_id"])
        return {"message": "Item deleted"}

    if name == "update_kitchen_status":
        order_svc.update_item_kitchen_status(args["item_id"], args["status"])
        return {"message": f"Kitchen status updated to {args['status']}"}

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
) -> Generator[str, None, None]:
    """Orchestrate the LLM chat with tool calling, yielding SSE events."""

    # Build messages
    system_content = SYSTEM_PROMPT
    if features_kitchen:
        system_content += KITCHEN_EXTRA_PROMPT
    if features_web:
        system_content += WEB_FEATURES_PROMPT
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

            result = _execute_tool(fn_name, fn_args)

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
