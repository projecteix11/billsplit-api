from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.logging import log_event, LogFactory
from app.middleware.auth import require_auth
from app.middleware.tenant import require_feature, get_current_tenant
from app.middleware.rate_limit import limiter
from app.models import UpdateQuantityBody, UpdatePriceBody
from app.services import activity as activity_svc
from app.services import orders as svc

router = APIRouter()

VALID_KITCHEN_STATUSES = {"pending", "cooking", "ready", "delivered", "cancelled"}
VALID_PAYMENT_STATUSES = {"unassigned", "assigned", "paid"}


class KitchenStatusBody(BaseModel):
    status: str


class PaymentStatusBody(BaseModel):
    itemIds: list[str]
    status: str


class PaymentPortionAllocation(BaseModel):
    itemId: str
    splitPortions: int = 1
    portions: int = 1


class PaymentPortionsBody(BaseModel):
    allocations: list[PaymentPortionAllocation]


@router.patch("/order-items/{item_id}/kitchen-status")
@limiter.limit("20/minute")
def update_kitchen_status(request: Request, item_id: str, body: KitchenStatusBody, _user_id: str = Depends(require_auth), tenant_id: str = Depends(require_feature("kitchen"))):
    if body.status not in VALID_KITCHEN_STATUSES:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "status must be one of: pending, cooking, ready, delivered, cancelled"},
        )
    try:
        item_ctx = activity_svc.get_order_item_context(item_id)
        svc.update_item_kitchen_status(item_id, body.status, tenant_id)
        log_event(LogFactory.order_lifecycle(
            "kitchen_status_changed", "",
            metadata={"item_id": item_id, "new_status": body.status},
        ))
        activity_svc.record_kitchen_status_changed(
            request=request,
            tenant_id=tenant_id,
            item=item_ctx,
            status=body.status,
        )
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Order item not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.patch("/order-items/payment-status")
@limiter.limit("20/minute")
def update_payment_status(request: Request, body: PaymentStatusBody, tenant_id: str = Depends(require_feature("payments"))):
    if not body.itemIds:
        return JSONResponse(status_code=400, content={"data": None, "error": "itemIds[] is required"})
    if body.status not in VALID_PAYMENT_STATUSES:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "status must be one of: unassigned, assigned, paid"},
        )
    try:
        items_ctx = activity_svc.get_order_items_context(body.itemIds)
        svc.update_items_payment_status(body.itemIds, body.status, tenant_id)
        if body.status == "paid":
            svc.auto_close_orders_for_items(body.itemIds)
        log_event(LogFactory.order_lifecycle(
            "payment_status_changed", "",
            metadata={"item_ids": body.itemIds, "new_status": body.status},
        ))
        if body.status == "paid" and items_ctx:
            first_order = (items_ctx[0].get("order") or {})
            actor_type, actor_id, actor_name = activity_svc.actor_from_request(request)
            table_number = first_order.get("table_number")
            activity_svc.record_event(
                tenant_id=tenant_id,
                actor_type=actor_type,
                actor_id=actor_id,
                actor_name=actor_name,
                source="management" if actor_type != "customer" else "client",
                action="items_marked_paid",
                category="payments",
                title="Articulos marcados como pagados",
                description=f"{actor_name or 'Sistema'} ha marcado {len(body.itemIds)} articulo(s) como pagados en la mesa {table_number}.",
                table_id=first_order.get("table_id"),
                table_number=table_number,
                order_id=first_order.get("id"),
                quantity=len(body.itemIds),
                tags=["payments", "items", actor_type, *( [f"table-{table_number}"] if table_number is not None else [] )],
                metadata={"item_ids": body.itemIds},
            )
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Order item not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.patch("/order-items/payment-portions")
@limiter.limit("20/minute")
def update_payment_portions(request: Request, body: PaymentPortionsBody, tenant_id: str = Depends(require_feature("payments"))):
    if not body.allocations:
        return JSONResponse(status_code=400, content={"data": None, "error": "allocations[] is required"})
    for allocation in body.allocations:
        if allocation.splitPortions < 1 or allocation.portions < 1:
            return JSONResponse(status_code=400, content={"data": None, "error": "splitPortions and portions must be >= 1"})

    try:
        item_ids = [allocation.itemId for allocation in body.allocations]
        items_ctx = activity_svc.get_order_items_context(item_ids)
        updated_ids = svc.update_items_payment_portions(
            [
                {
                    "item_id": allocation.itemId,
                    "split_portions": allocation.splitPortions,
                    "portions": allocation.portions,
                }
                for allocation in body.allocations
            ],
            tenant_id,
        )
        if updated_ids:
            svc.auto_close_orders_for_items(updated_ids)
        log_event(LogFactory.order_lifecycle(
            "payment_portions_changed", "",
            metadata={"allocations": [allocation.model_dump() for allocation in body.allocations]},
        ))
        if updated_ids and items_ctx:
            first_order = (items_ctx[0].get("order") or {})
            actor_type, actor_id, actor_name = activity_svc.actor_from_request(request)
            table_number = first_order.get("table_number")
            activity_svc.record_event(
                tenant_id=tenant_id,
                actor_type=actor_type,
                actor_id=actor_id,
                actor_name=actor_name,
                source="management" if actor_type != "customer" else "client",
                action="item_portions_paid",
                category="payments",
                title="Porciones de articulos pagadas",
                description=f"{actor_name or 'Sistema'} ha pagado porciones de {len(updated_ids)} articulo(s) en la mesa {table_number}.",
                table_id=first_order.get("table_id"),
                table_number=table_number,
                order_id=first_order.get("id"),
                quantity=len(updated_ids),
                tags=["payments", "split", actor_type, *( [f"table-{table_number}"] if table_number is not None else [] )],
                metadata={"allocations": [allocation.model_dump() for allocation in body.allocations]},
            )
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Order item not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.delete("/order-items/{item_id}")
@limiter.limit("20/minute")
def delete_order_item(request: Request, item_id: str, _user_id: str = Depends(require_auth), tenant_id: str = Depends(get_current_tenant)):
    try:
        item_ctx = activity_svc.get_order_item_context(item_id)
        svc.delete_order_item(item_id, tenant_id)
        log_event(LogFactory.order_lifecycle(
            "order_item_deleted", "",
            metadata={"item_id": item_id},
        ))
        if item_ctx:
            order_ctx = item_ctx.get("order") or {}
            actor_type, actor_id, actor_name = activity_svc.actor_from_request(request)
            table_number = order_ctx.get("table_number")
            dish_name = item_ctx.get("dish_name") or "Articulo"
            activity_svc.record_event(
                tenant_id=tenant_id,
                actor_type=actor_type,
                actor_id=actor_id,
                actor_name=actor_name,
                source="management",
                action="item_deleted",
                category="items",
                title=f"{dish_name} eliminado",
                description=f"{actor_name or 'Sistema'} ha eliminado {dish_name} de la mesa {table_number}.",
                table_id=order_ctx.get("table_id"),
                table_number=table_number,
                order_id=item_ctx.get("order_id"),
                order_item_id=item_ctx.get("id"),
                dish_id=item_ctx.get("dish_id"),
                dish_name=dish_name,
                quantity=item_ctx.get("quantity"),
                tags=["items", "deleted", actor_type, *( [f"table-{table_number}"] if table_number is not None else [] )],
            )
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Order item not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.patch("/order-items/{item_id}/quantity")
@limiter.limit("20/minute")
def update_item_quantity(request: Request, item_id: str, body: UpdateQuantityBody, _user_id: str = Depends(require_auth), tenant_id: str = Depends(get_current_tenant)):
    try:
        item_ctx = activity_svc.get_order_item_context(item_id)
        svc.update_order_item_quantity(item_id, body.quantity, tenant_id)
        log_event(LogFactory.order_lifecycle(
            "order_item_quantity_updated", "",
            metadata={"item_id": item_id, "new_quantity": body.quantity},
        ))
        if item_ctx:
            order_ctx = item_ctx.get("order") or {}
            actor_type, actor_id, actor_name = activity_svc.actor_from_request(request)
            table_number = order_ctx.get("table_number")
            dish_name = item_ctx.get("dish_name") or "Articulo"
            activity_svc.record_event(
                tenant_id=tenant_id,
                actor_type=actor_type,
                actor_id=actor_id,
                actor_name=actor_name,
                source="management",
                action="item_quantity_updated",
                category="items",
                title=f"{dish_name}: cantidad actualizada",
                description=f"{actor_name or 'Sistema'} ha cambiado {dish_name} de {item_ctx.get('quantity')} a {body.quantity} unidades en la mesa {table_number}.",
                table_id=order_ctx.get("table_id"),
                table_number=table_number,
                order_id=item_ctx.get("order_id"),
                order_item_id=item_ctx.get("id"),
                dish_id=item_ctx.get("dish_id"),
                dish_name=dish_name,
                quantity=body.quantity,
                tags=["items", "edited", actor_type, *( [f"table-{table_number}"] if table_number is not None else [] )],
                metadata={"previous_quantity": item_ctx.get("quantity"), "new_quantity": body.quantity},
            )
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Order item not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.patch("/order-items/{item_id}/price")
@limiter.limit("20/minute")
def update_item_price(request: Request, item_id: str, body: UpdatePriceBody, _user_id: str = Depends(require_auth), tenant_id: str = Depends(get_current_tenant)):
    try:
        item_ctx = activity_svc.get_order_item_context(item_id)
        svc.update_order_item_price(item_id, body.price, tenant_id, reason=body.reason)
        log_event(LogFactory.order_lifecycle(
            "order_item_price_updated", "",
            metadata={"item_id": item_id, "new_price": body.price, "reason": body.reason},
        ))
        if item_ctx:
            order_ctx = item_ctx.get("order") or {}
            actor_type, actor_id, actor_name = activity_svc.actor_from_request(request)
            table_number = order_ctx.get("table_number")
            dish_name = item_ctx.get("dish_name") or "Articulo"
            activity_svc.record_event(
                tenant_id=tenant_id,
                actor_type=actor_type,
                actor_id=actor_id,
                actor_name=actor_name,
                source="management",
                action="item_price_updated",
                category="items",
                title=f"{dish_name}: precio actualizado",
                description=f"{actor_name or 'Sistema'} ha cambiado el precio de {dish_name} en la mesa {table_number}.",
                table_id=order_ctx.get("table_id"),
                table_number=table_number,
                order_id=item_ctx.get("order_id"),
                order_item_id=item_ctx.get("id"),
                dish_id=item_ctx.get("dish_id"),
                dish_name=dish_name,
                amount=body.price,
                tags=["items", "edited", "pricing", actor_type, *( [f"table-{table_number}"] if table_number is not None else [] )],
                metadata={"previous_price": item_ctx.get("dish_price"), "new_price": body.price, "reason": body.reason},
            )
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Order item not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})
