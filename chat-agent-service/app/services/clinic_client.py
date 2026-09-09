"""
clinic_client: fetches a clinic's public profile from the external Doctor
Laser CMS API (api.doctor-laser.ir) and formats it into plain text suitable
for injection into an agent's system prompt as ambient context — so the
model knows the clinic's name, services, location, and contact info without
this needing to be hardcoded into every agent's static system_prompt.
"""
from __future__ import annotations

import httpx

from app.core.config import settings


async def fetch_clinic_profile(clinic_id: str) -> dict | None:
    """Returns None on any failure (network error, 404, etc.) — the caller
    treats a missing clinic profile as a no-op, never as a fatal error."""
    url = f"{settings.CLINIC_API_BASE_URL}/public-clinics/{clinic_id}"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            return None


def format_clinic_context(data: dict) -> str:
    lines = [f"نام کلینیک: {data.get('name', '')}"]

    if data.get("description"):
        lines.append(f"توضیحات: {data['description']}")

    location = "، ".join(filter(None, [data.get("city"), data.get("province")]))
    if location:
        lines.append(f"موقعیت: {location}")

    if data.get("address"):
        lines.append(f"آدرس: {data['address']}")

    if data.get("phone"):
        lines.append(f"تلفن تماس: {data['phone']}")

    services = data.get("services") or []
    if services:
        service_names = "، ".join(s["name"].strip() for s in services if s.get("name"))
        lines.append(f"خدمات ارائه‌شده: {service_names}")

    social = data.get("social_media") or {}
    social_lines = [f"{k}: {v}" for k, v in social.items() if v]
    if social_lines:
        lines.append("شبکه‌های اجتماعی: " + "، ".join(social_lines))

    return "\n".join(lines)