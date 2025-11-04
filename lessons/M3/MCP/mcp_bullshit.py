import os
import json
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List

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

# --------- Configuration ----------
SERVICE_NAME = "time-and-tripadvisor"
DEFAULT_LANGUAGE = "en"
TRIPADVISOR_API_KEY = os.getenv("TRIPADVISOR_API_KEY")

# Create MCP server
mcp_server = Server(SERVICE_NAME)

# ------------- Tool Schemas -------------
def tool_schema_get_current_time() -> Dict[str, Any]:
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

def tool_schema_search_tripadvisor_restaurants() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "latitude": {"type": "number", "description": "Latitude of search center"},
            "longitude": {"type": "number", "description": "Longitude of search center"},
            "limit": {"type": "integer", "description": "Max results to return", "default": 10},
        },
        "required": ["latitude", "longitude"],
    }

def tool_schema_get_restaurant_details() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "location_id": {"type": "string", "description": "TripAdvisor location ID"},
        },
        "required": ["location_id"],
    }

def tool_schema_get_restaurant_reviews() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "location_id": {"type": "string", "description": "TripAdvisor location ID"},
            "limit": {"type": "integer", "description": "Max number of reviews", "default": 5},
        },
        "required": ["location_id"],
    }

@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="get_current_time",
            description="Get the current time in a specified timezone.",
            inputSchema=tool_schema_get_current_time(),
        ),
        Tool(
            name="search_tripadvisor_restaurants",
            description="Search nearby restaurants using TripAdvisor Content API.",
            inputSchema=tool_schema_search_tripadvisor_restaurants(),
        ),
        Tool(
            name="get_restaurant_details",
            description="Get detailed information for a TripAdvisor location_id.",
            inputSchema=tool_schema_get_restaurant_details(),
        ),
        Tool(
            name="get_restaurant_reviews",
            description="Get reviews for a TripAdvisor location_id.",
            inputSchema=tool_schema_get_restaurant_reviews(),
        ),
    ]

# ------------- Helpers -------------
def format_cuisine(cuisine_field: Any) -> str:
    """
    TripAdvisor 'cuisine' is usually a list of dicts with 'name'.
    We normalize to a comma-separated string.
    """
    if not cuisine_field:
        return "N/A"
    if isinstance(cuisine_field, list):
        names = []
        for item in cuisine_field:
            if isinstance(item, dict) and "name" in item:
                names.append(item["name"])
            elif isinstance(item, str):
                names.append(item)
        return ", ".join(names) if names else "N/A"
    if isinstance(cuisine_field, dict) and "name" in cuisine_field:
        return cuisine_field["name"]
    if isinstance(cuisine_field, str):
        return cuisine_field
    return "N/A"

def format_hours(hours: Any) -> str:
    try:
        return json.dumps(hours, ensure_ascii=False, indent=2)
    except Exception:
        return str(hours)

def env_key_required() -> str:
    return (
        "TripAdvisor API key missing. Set environment variable TRIPADVISOR_API_KEY.\n"
        "See: https://developer-tripadvisor.com/content-api/"
    )

async def tripadvisor_get(client: httpx.AsyncClient, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    headers = {"accept": "application/json"}
    resp = await client.get(url, params=params, headers=headers, timeout=httpx.Timeout(30.0))
    resp.raise_for_status()
    return resp.json()

# ------------- Tool Implementation -------------
async def tool_get_current_time(arguments: Dict[str, Any]) -> str:
    tzname = (arguments.get("timezone") or "UTC").strip()
    now_utc = datetime.now(dt_timezone.utc)

    if tzname.upper() == "UTC" or ZoneInfo is None:
        return f"Current time in {tzname or 'UTC'}: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC"

    try:
        tz = ZoneInfo(tzname)
    except Exception:
        # Unknown timezone; fall back to UTC with a note
        return (
            f"Current time (UTC): {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC. "
            f"Note: Unknown timezone '{tzname}', falling back to UTC."
        )

    local_dt = now_utc.astimezone(tz)
    offset = local_dt.strftime('%z')
    offset_fmt = f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC"
    return f"Current time in {tzname}: {local_dt.strftime('%Y-%m-%d %H:%M:%S')} ({offset_fmt})"

async def tool_search_tripadvisor_restaurants(arguments: Dict[str, Any]) -> str:
    if not TRIPADVISOR_API_KEY:
        return env_key_required()

    lat = float(arguments["latitude"])
    lon = float(arguments["longitude"])
    limit = int(arguments.get("limit", 10))

    url = "https://api.content.tripadvisor.com/api/v1/location/nearby_search"
    params = {
        "latLong": f"{lat},{lon}",
        "category": "restaurants",
        "limit": limit,
        "language": DEFAULT_LANGUAGE,
        "key": TRIPADVISOR_API_KEY,
    }

    lines: List[str] = [f"Found restaurants near {lat}, {lon}:\n"]

    async with httpx.AsyncClient() as client:
        try:
            data = await tripadvisor_get(client, url, params)
        except httpx.HTTPStatusError as e:
            return f"HTTP error {e.response.status_code}. Ensure your TripAdvisor API key is valid."
        except Exception as e:
            return f"Error searching restaurants: {e}"

        results = data.get("data") or []
        if not results:
            return f"No restaurants found near {lat}, {lon}"

        for idx, r in enumerate(results, 1):
            location_id = r.get("location_id", "N/A")
            name = r.get("name", "N/A")
            address = (r.get("address_obj") or {}).get("address_string", "N/A")
            rating = r.get("rating", "N/A")
            cuisine = format_cuisine(r.get("cuisine"))
            price = r.get("price_level", "N/A")
            url_link = r.get("web_url", "N/A")

            lines.append(f"{idx}. {name}")
            lines.append(f"   Location ID: {location_id}")
            lines.append(f"   Address: {address}")
            lines.append(f"   Rating: {rating}")
            lines.append(f"   Cuisine: {cuisine}")
            lines.append(f"   Price: {price}")
            lines.append(f"   URL: {url_link}")

            # Fetch details for each location to enrich
            if location_id and location_id != "N/A":
                detail_url = f"https://api.content.tripadvisor.com/api/v1/location/{location_id}/details"
                detail_params = {"language": DEFAULT_LANGUAGE, "key": TRIPADVISOR_API_KEY}
                try:
                    detail_data = await tripadvisor_get(client, detail_url, detail_params)
                    phone = detail_data.get("phone", "N/A")
                    website = detail_data.get("website", "N/A")
                    email = detail_data.get("email", "N/A")
                    hours = detail_data.get("hours", {})

                    lines.append(f"   Phone: {phone}")
                    lines.append(f"   Website: {website}")
                    if email and email != "N/A":
                        lines.append(f"   Email: {email}")
                    if hours:
                        lines.append(f"   Hours: {format_hours(hours)}")
                except httpx.HTTPStatusError:
                    # Skip detail enrichment failures silently per item
                    pass
                except Exception:
                    pass

            lines.append("")  # blank line between items

    return "\n".join(lines).strip()

async def tool_get_restaurant_details(arguments: Dict[str, Any]) -> str:
    if not TRIPADVISOR_API_KEY:
        return env_key_required()

    location_id = arguments["location_id"]
    url = f"https://api.content.tripadvisor.com/api/v1/location/{location_id}/details"
    params = {"language": DEFAULT_LANGUAGE, "key": TRIPADVISOR_API_KEY}

    async with httpx.AsyncClient() as client:
        try:
            data = await tripadvisor_get(client, url, params)
        except httpx.HTTPStatusError as e:
            body = e.response.text
            return f"HTTP error {e.response.status_code}: {body[:300]}{'…' if len(body) > 300 else ''}"
        except Exception as e:
            return f"Error getting restaurant details: {e}"

    lines: List[str] = []
    lines.append(f"Details for {data.get('name', 'Unknown')}:")
    lines.append("")
    lines.append(f"Location ID: {location_id}")
    lines.append(f"Description: {data.get('description', 'N/A')}")
    lines.append(f"Phone: {data.get('phone', 'N/A')}")
    lines.append(f"Website: {data.get('website', 'N/A')}")
    lines.append(f"Email: {data.get('email', 'N/A')}")
    lines.append(f"Address: {(data.get('address_obj') or {}).get('address_string', 'N/A')}")
    lines.append(f"Rating: {data.get('rating', 'N/A')}")
    lines.append(f"Price Level: {data.get('price_level', 'N/A')}")
    lines.append(f"Cuisine: {format_cuisine(data.get('cuisine'))}")
    lines.append(f"Web URL: {data.get('web_url', 'N/A')}")

    hours = data.get("hours", {})
    if hours:
        lines.append("")
        lines.append("Hours of Operation:")
        lines.append(format_hours(hours))

    return "\n".join(lines)

async def tool_get_restaurant_reviews(arguments: Dict[str, Any]) -> str:
    if not TRIPADVISOR_API_KEY:
        return env_key_required()

    location_id = arguments["location_id"]
    limit = int(arguments.get("limit", 5))

    url = f"https://api.content.tripadvisor.com/api/v1/location/{location_id}/reviews"
    params = {"language": DEFAULT_LANGUAGE, "limit": limit, "key": TRIPADVISOR_API_KEY}

    async with httpx.AsyncClient() as client:
        try:
            data = await tripadvisor_get(client, url, params)
        except httpx.HTTPStatusError as e:
            body = e.response.text
            return f"HTTP error {e.response.status_code}: {body[:300]}{'…' if len(body) > 300 else ''}"
        except Exception as e:
            return f"Error getting reviews: {e}"

    reviews = data.get("data") or []
    if not reviews:
        return f"No reviews found for location {location_id}"

    lines: List[str] = [f"Reviews for Location ID {location_id}:", ""]
    for i, review in enumerate(reviews, 1):
        title = review.get("title", "No title")
        text = review.get("text", "No text")
        rating = review.get("rating", "N/A")
        published_date = review.get("published_date", "N/A")
        author = ((review.get("user") or {}).get("username")) or "Anonymous"

        lines.append(f"{i}. {title}")
        lines.append(f"   Author: {author}")
        lines.append(f"   Rating: {rating}/5")
        lines.append(f"   Date: {published_date}")
        lines.append(f"   Review: {text}")
        lines.append("")

    return "\n".join(lines).strip()

# ------------- MCP dispatcher -------------
@mcp_server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    try:
        if name == "get_current_time":
            out = await tool_get_current_time(arguments)
        elif name == "search_tripadvisor_restaurants":
            out = await tool_search_tripadvisor_restaurants(arguments)
        elif name == "get_restaurant_details":
            out = await tool_get_restaurant_details(arguments)
        elif name == "get_restaurant_reviews":
            out = await tool_get_restaurant_reviews(arguments)
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
    # Minimal OpenAPI stub that documents the SSE endpoint
    return JSONResponse({
        "openapi": "3.0.0",
        "info": {
            "title": "Time & TripAdvisor MCP Server",
            "version": "1.0.0",
            "description": "MCP server offering time and TripAdvisor tools",
        },
        "servers": [{"url": "http://localhost:8765"}],
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
    print("Starting Time & TripAdvisor MCP Server on http://localhost:8765")
    print("Endpoints:")
    print("  - Root:     http://localhost:8765")
    print("  - SSE:      http://localhost:8765/sse")
    print("  - Message:  http://localhost:8765/message (POST)")
    print("  - Health:   http://localhost:8765/health")
    print("  - OpenAPI:  http://localhost:8765/openapi.json")
    if not TRIPADVISOR_API_KEY:
        print("WARNING: TRIPADVISOR_API_KEY is not set. TripAdvisor tools will return an informative error.")
    uvicorn.run(app, host="0.0.0.0", port=8765)
