from app.db import supabase


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

    # Create auth user via Supabase Admin API
    auth_user = supabase.create_auth_user(email, password, user_metadata)
    user_id = auth_user["id"]

    # Insert into user_roles
    supabase.insert(
        "user_roles",
        {"user_id": user_id, "tenant_id": tenant_id, "role": role},
        return_result=False,
    )

    return {
        "id": user_id,
        "email": email,
        "firstName": first_name,
        "lastName": last_name,
        "role": role,
        "enabled": True,
    }


def delete_staff_user(user_id: str, tenant_id: str) -> None:
    # Remove from user_roles first
    supabase.delete("user_roles", f"user_id=eq.{user_id}&tenant_id=eq.{tenant_id}")

    # Delete auth user from Supabase
    supabase.delete_auth_user(user_id)
