from app.db.supabase import get_client, create_auth_user, delete_auth_user


def create_staff_user(
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    role: str,
    tenant_id: str,
) -> dict:
    full_name = f"{first_name} {last_name}".strip()

    user_metadata = {
        "full_name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "role": role,
        "tenant_id": tenant_id,
    }

    auth_user = create_auth_user(email, password, user_metadata)
    user_id = auth_user["id"]

    get_client().table("user_roles").insert(
        {"user_id": user_id, "tenant_id": tenant_id, "role": role}
    ).execute()

    return {
        "id": user_id,
        "email": email,
        "firstName": first_name,
        "lastName": last_name,
        "role": role,
        "enabled": True,
    }


def delete_staff_user(user_id: str, tenant_id: str) -> None:
    get_client().table("user_roles").delete().eq("user_id", user_id).eq("tenant_id", tenant_id).execute()
    delete_auth_user(user_id)
