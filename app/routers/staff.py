from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.middleware.auth import require_auth
from app.middleware.rate_limit import limiter
from app.models import CreateStaffBody, DeleteStaffBody
from app.services import staff as svc
from app.logging.client import log_event
from app.logging.factory import LogFactory
from app.http_errors import internal_error

router = APIRouter()


@router.post("/staff", status_code=201)
@limiter.limit("10/minute")
def create_staff(request: Request, body: CreateStaffBody, user_id: str = Depends(require_auth)):
    try:
        result = svc.create_staff_user(
            email=body.email,
            password=body.password,
            first_name=body.firstName,
            last_name=body.lastName,
            role=body.role,
            tenant_id=body.tenantId,
        )

        log_event(LogFactory.auth_event(
            "staff_created",
            user_id=user_id,
            metadata={"new_user_email": body.email, "role": body.role},
        ))

        return JSONResponse(status_code=201, content={"data": result, "error": None})
    except RuntimeError as e:
        return JSONResponse(status_code=400, content={"data": None, "error": str(e)})
    except Exception as e:
        log_event(LogFactory.auth_event(
            "staff_create_failed",
            user_id=user_id,
            metadata={"email": body.email, "error": str(e)},
        ))
        return internal_error(e)


@router.delete("/staff/{staff_user_id}", status_code=200)
@limiter.limit("10/minute")
def delete_staff(request: Request, staff_user_id: str, body: DeleteStaffBody, user_id: str = Depends(require_auth)):
    try:
        svc.delete_staff_user(staff_user_id, body.tenantId)

        log_event(LogFactory.auth_event(
            "staff_deleted",
            user_id=user_id,
            metadata={"deleted_user_id": staff_user_id},
        ))

        return JSONResponse(status_code=200, content={"data": None, "error": None})
    except RuntimeError as e:
        return JSONResponse(status_code=400, content={"data": None, "error": str(e)})
    except Exception as e:
        log_event(LogFactory.auth_event(
            "staff_delete_failed",
            user_id=user_id,
            metadata={"deleted_user_id": staff_user_id, "error": str(e)},
        ))
        return internal_error(e)
