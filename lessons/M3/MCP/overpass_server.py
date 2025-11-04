import json
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List

import asyncio
import random
import httpx
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
import uvicorn

# --------- Optional: proper timezone conversion ----------
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # Fallback later

# --------- Service configuration ----------
SERVICE_NAME = "time-and-osm"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]
DEFAULT_SEARCH_RADIUS_M = 1500
USER_AGENT = "TIME_AND_OSM/1.0 (contact: lara.nonis@outlook.it)"  # put your contact

# Create MCP server
mcp_server = Server(SERVICE_NAME)

# ---------------- Schemas ----------------
def schema_get_current_time() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "IANA timezone (e.g., 'UTC', 'Europe/Rome', 'America/New_York')",
                "default": "UTC",
            }
        },
        "required": [],
    }

def schema_search_osm_restaurants() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "latitude": {"type": "number", "description": "Latitude of search center"},
            "longitude": {"type": "number", "description": "Longitude of search center"},
            "limit": {"type": "integer", "description": "Max results to return", "default": 10},
            "radius_m": {"type": "integer", "description": "Search radius in meters", "default": DEFAULT_SEARCH_RADIUS_M},
        },
        "required": ["latitude", "longitude"],
    }

def schema_get_osm_place_details() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "osm_type": {"type": "string", "enum": ["node", "way", "relation"], "description": "OSM element type"},
            "osm_id": {"type": "integer", "description": "OSM element ID"},
        },
        "required": ["osm_type", "osm_id"],
    }

# ---------------- Overpass helper with mirrors/retries ----------------
async def overpass_query(client: httpx.AsyncClient, query: str) -> dict:
    """
    Query Overpass with retries, mirror rotation, and a polite User-Agent.
    """
    endpoints = OVERPASS_ENDPOINTS[:]
    random.shuffle(endpoints)

    attempts = 0
    last_exc = None
    while attempts < 4:
        for base in endpoints:
            try:
                resp = await client.post(
                    base,
                    data={"data": query},
                    headers={
                        "content-type": "application/x-www-form-urlencoded",
                        "user-agent": USER_AGENT,
                    },
                    timeout=httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0),
                )
                resp.raise_for_status()
                return resp.json()
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.TransportError) as e:
                last_exc = e
                continue
        attempts += 1
        await asyncio.sleep(min(2 ** attempts, 6))  # 2s, 4s, 6s, 6s
    raise RuntimeError(f"Overpass query failed across mirrors. Last error: {last_exc}")

# ---------------- Helpers ----------------
def format_hours(tags: dict) -> str:
    return tags.get("opening_hours", "N/A")

def format_osm_address(tags: dict) -> str:
    parts = [
        tags.get("addr:housenumber"),
        tags.get("addr:street"),
        tags.get("addr:postcode"),
        tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village"),
        tags.get("addr:country"),
    ]
    return ", ".join(p for p in parts if p) or "N/A"

def format_cuisine_tag(tags: dict) -> str:
    c = tags.get("cuisine")
    if not c:
        return "N/A"
    return ", ".join(part.strip() for part in str(c).split(";") if part.strip()) or "N/A"

def osm_url(osm_type: str, osm_id: int) -> str:
    return f"https://www.openstreetmap.org/{osm_type}/{osm_id}"

# ---------------- Tools ----------------
async def tool_get_current_time(arguments: Dict[str, Any]) -> str:
    tzname = (arguments.get("timezone") or "UTC").strip()
    now_utc = datetime.now(dt_timezone.utc)

    if tzname.upper() == "UTC" or ZoneInfo is None:
        return f"Current time in {tzname or 'UTC'}: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC"

    try:
        tz = ZoneInfo(tzname)
    except Exception:
        return (
            f"Current time (UTC): {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC. "
            f"Note: Unknown timezone '{tzname}', falling back to UTC."
        )

    local_dt = now_utc.astimezone(tz)
    offset = local_dt.strftime('%z')
    offset_fmt = f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC"
    return f"Current time in {tzname}: {local_dt.strftime('%Y-%m-%d %H:%M:%S')} ({offset_fmt})"

async def tool_search_osm_restaurants(arguments: Dict[str, Any]) -> str:
    lat = float(arguments["latitude"])
    lon = float(arguments["longitude"])
    limit = int(arguments.get("limit", 10))
    radius_m = int(arguments.get("radius_m", DEFAULT_SEARCH_RADIUS_M))

    overpass = f"""
    [out:json][timeout:25];
    (
      node["amenity"="restaurant"](around:{radius_m},{lat},{lon});
      way["amenity"="restaurant"](around:{radius_m},{lat},{lon});
      relation["amenity"="restaurant"](around:{radius_m},{lat},{lon});
    );
    out tags center {limit};
    """

    async with httpx.AsyncClient() as client:
        try:
            data = await overpass_query(client, overpass)
        except httpx.HTTPStatusError as e:
            return f"Overpass error {e.response.status_code}. Try again later or reduce radius."
        except Exception as e:
            return f"Error querying Overpass: {e}"

    elements = data.get("elements", [])
    if not elements:
        return f"No OSM restaurants found near {lat}, {lon} within {radius_m} m."

    lines: List[str] = [f"OSM restaurants near {lat}, {lon} (radius {radius_m} m):", ""]
    for idx, el in enumerate(elements[:limit], 1):
        tags = el.get("tags", {}) or {}
        name = tags.get("name", "Unnamed")
        cuisine = format_cuisine_tag(tags)
        phone = tags.get("phone") or tags.get("contact:phone") or "N/A"
        website = tags.get("website") or tags.get("contact:website") or "N/A"
        opening = format_hours(tags)
        addr = format_osm_address(tags)

        osm_type = el.get("type", "node")
        osm_id = el.get("id")
        url = osm_url(osm_type, osm_id) if osm_id else "N/A"

        if "lat" in el and "lon" in el:
            el_lat, el_lon = el["lat"], el["lon"]
        else:
            center = el.get("center") or {}
            el_lat, el_lon = center.get("lat", "N/A"), center.get("lon", "N/A")

        lines.append(f"{idx}. {name}")
        lines.append(f"   OSM: {url}")
        lines.append(f"   Coords: {el_lat}, {el_lon}")
        lines.append(f"   Address: {addr}")
        lines.append(f"   Cuisine: {cuisine}")
        lines.append(f"   Phone: {phone}")
        lines.append(f"   Website: {website}")
        lines.append(f"   Opening hours: {opening}")
        lines.append("")

    return "\n".join(lines).strip()

async def tool_get_osm_place_details(arguments: Dict[str, Any]) -> str:
    osm_type = str(arguments["osm_type"]).lower().strip()
    osm_id = int(arguments["osm_id"])

    if osm_type not in {"node", "way", "relation"}:
        return "osm_type must be one of: node, way, relation."

    query = f"""
    [out:json][timeout:25];
    {osm_type}({osm_id});
    out tags center;
    """

    async with httpx.AsyncClient() as client:
        try:
            data = await overpass_query(client, query)
        except httpx.HTTPStatusError as e:
            return f"Overpass error {e.response.status_code}."
        except Exception as e:
            return f"Error querying Overpass: {e}"

    elements = data.get("elements", [])
    if not elements:
        return f"No element found for {osm_type} {osm_id}."

    el = elements[0]
    tags = el.get("tags", {}) or {}
    name = tags.get("name", "Unnamed")
    addr = format_osm_address(tags)
    cuisine = format_cuisine_tag(tags)
    phone = tags.get("phone") or tags.get("contact:phone") or "N/A"
    website = tags.get("website") or tags.get("contact:website") or "N/A"
    opening = format_hours(tags)
    url = osm_url(osm_type, osm_id)

    if "lat" in el and "lon" in el:
        el_lat, el_lon = el["lat"], el["lon"]
    else:
        center = el.get("center") or {}
        el_lat, el_lon = center.get("lat", "N/A"), center.get("lon", "N/A")

    lines = [
        f"Details for {name}",
        "",
        f"OSM: {url}",
        f"Type/ID: {osm_type} {osm_id}",
        f"Coords: {el_lat}, {el_lon}",
        f"Address: {addr}",
        f"Cuisine: {cuisine}",
        f"Phone: {phone}",
        f"Website: {website}",
        f"Opening hours: {opening}",
        "",
        "All tags:",
        json.dumps(tags, ensure_ascii=False, indent=2),
    ]
    return "\n".join(lines).strip()

# ------------- MCP dispatcher -------------
async def _with_overall_timeout(coro, seconds: float, on_timeout: str):
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        return on_timeout

@mcp_server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    try:
        if name == "get_current_time":
            out = await _with_overall_timeout(
                tool_get_current_time(arguments), 5.0,
                "Timed out getting current time."
            )
        elif name == "search_osm_restaurants":
            out = await _with_overall_timeout(
                tool_search_osm_restaurants(arguments), 25.0,
                "Timed out searching OSM restaurants. Try a smaller radius/limit."
            )
        elif name == "get_osm_place_details":
            out = await _with_overall_timeout(
                tool_get_osm_place_details(arguments), 20.0,
                "Timed out getting OSM place details."
            )
        else:
            out = f"Unknown tool: {name}"
    except Exception as e:
        out = f"Unhandled error in tool '{name}': {e}"
    return [TextContent(type="text", text=out)]

# ------------- SSE endpoints -------------
async def handle_sse(request: Request):
    transport = SseServerTransport("/message")
    await transport.handle_sse(request, mcp_server)

async def handle_messages(request: Request):
    transport = SseServerTransport("/message")
    await transport.handle_post_message(request, mcp_server)

# ------------- Service endpoints -------------
async def health(_request: Request):
    return JSONResponse({"status": "healthy", "service": SERVICE_NAME})

async def root(_request: Request):
    return JSONResponse({
        "service": SERVICE_NAME,
        "version": "1.0.0",
        "endpoints": {
            "sse": "/sse",
            "message": "/message",
            "health": "/health",
            "openapi": "/openapi.json",
        },
        "tools": [t.name for t in await list_tools()],
    })

async def openapi(_request: Request):
    return JSONResponse({
        "openapi": "3.0.0",
        "info": {
            "title": "Time & OSM MCP Server",
            "version": "1.0.0",
            "description": "MCP server with time and OpenStreetMap (Overpass) tools",
        },
        "servers": [{"url": "http://localhost:8001"}],
        "paths": {
            "/sse": {"get": {"summary": "SSE endpoint for MCP communication", "responses": {"200": {"description": "SSE stream"}}}},
            "/message": {"post": {"summary": "POST messages endpoint for MCP", "responses": {"200": {"description": "OK"}}}},
            "/health": {"get": {"summary": "Health check", "responses": {"200": {"description": "Healthy"}}}},
        },
    })

# ------------- Starlette app -------------
app = Starlette(
    routes=[
        Route("/", endpoint=root),
        Route("/sse", endpoint=handle_sse),
        Route("/message", endpoint=handle_messages, methods=["POST"]),
        Route("/health", endpoint=health),
        Route("/openapi.json", endpoint=openapi),
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------- Entrypoint -------------
if __name__ == "__main__":
    print("Starting Time & OSM MCP Server on http://localhost:8001")
    print("Endpoints:")
    print("  - Root:     http://localhost:8001")
    print("  - SSE:      http://localhost:8001/sse")
    print("  - Message:  http://localhost:8001/message (POST)")
    print("  - Health:   http://localhost:8001/health")
    print("  - OpenAPI:  http://localhost:8001/openapi.json")
    uvicorn.run(app, host="0.0.0.0", port=8001)

