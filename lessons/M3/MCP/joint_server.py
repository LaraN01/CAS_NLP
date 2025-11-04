import json
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List

import asyncio
import random
import httpx
from mcp.server import Server
from mcp.types import Tool, TextContent
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
import uvicorn
import traceback

# ===== Timezone helper =====
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

# ===== Service config =====
SERVICE_NAME = "translator-and-osm"
PORT = 8001
DEFAULT_SEARCH_RADIUS_M = 1500
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]
USER_AGENT = "OPENWEBUI_TOOLS/1.0 (contact: you@example.com)"
ALLOWED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

# ===== Create MCP server =====
mcp_server = Server(SERVICE_NAME)

# ===== Translation model (lazy globals + startup loader) =====
import torch
from transformers import MBart50TokenizerFast, MBartForConditionalGeneration

MODEL_NAME = "facebook/mbart-large-50-many-to-many-mmt"
_tokenizer = None
_model = None
_model_ready = False
_model_error = None

async def load_model_on_startup():
    """
    Eager-load mBART ONCE at app startup. Never raise—just capture error.
    """
    global _tokenizer, _model, _model_ready, _model_error
    print("[startup] Beginning eager model load…")
    try:
        _tokenizer = MBart50TokenizerFast.from_pretrained(MODEL_NAME)
        _model = MBartForConditionalGeneration.from_pretrained(MODEL_NAME)
        _model.eval()
        _model_ready = True
        _model_error = None
        print("[startup] mBART loaded successfully.")
    except Exception as e:
        _model_ready = False
        _model_error = f"{type(e).__name__}: {e}"
        print("[startup] ERROR loading mBART!")
        traceback.print_exc()  # <-- full stacktrace to console for debugging

# ===== Schemas =====
def schema_get_current_time() -> Dict[str, Any]:
    return {"type":"object","properties":{
        "timezone":{"type":"string","description":"IANA timezone","default":"UTC"}
    },"required":[]}

def schema_search_osm_restaurants() -> Dict[str, Any]:
    return {"type":"object","properties":{
        "latitude":{"type":"number"},
        "longitude":{"type":"number"},
        "limit":{"type":"integer","default":10},
        "radius_m":{"type":"integer","default":DEFAULT_SEARCH_RADIUS_M}
    },"required":["latitude","longitude"]}

def schema_get_osm_place_details() -> Dict[str, Any]:
    return {"type":"object","properties":{
        "osm_type":{"type":"string","enum":["node","way","relation"]},
        "osm_id":{"type":"integer"}
    },"required":["osm_type","osm_id"]}

def schema_translate_ja_to_en() -> Dict[str, Any]:
    return {"type":"object","properties":{
        "text":{"type":"string","description":"Japanese text"},
        "max_length":{"type":"integer","default":512}
    },"required":["text"]}

def schema_ping() -> Dict[str, Any]:
    return {"type":"object","properties":{"msg":{"type":"string","default":"ok"}}, "required":[]}

# ===== Overpass helper with mirrors/retries =====
async def overpass_query(client: httpx.AsyncClient, query: str) -> dict:
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
        await asyncio.sleep(min(2 ** attempts, 6))
    raise RuntimeError(f"Overpass query failed across mirrors. Last error: {last_exc}")

# ===== Helpers =====
def format_hours(tags: dict) -> str:
    return tags.get("opening_hours", "N/A")
def format_osm_address(tags: dict) -> str:
    parts=[tags.get("addr:housenumber"),tags.get("addr:street"),tags.get("addr:postcode"),
           tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village"),
           tags.get("addr:country")]
    return ", ".join(p for p in parts if p) or "N/A"
def format_cuisine_tag(tags: dict) -> str:
    c = tags.get("cuisine")
    if not c: return "N/A"
    return ", ".join(part.strip() for part in str(c).split(";") if part.strip()) or "N/A"
def osm_url(osm_type: str, osm_id: int) -> str:
    return f"https://www.openstreetmap.org/{osm_type}/{osm_id}"

# ===== Tools =====
async def tool_get_current_time(arguments: Dict[str, Any]) -> str:
    tzname = (arguments.get("timezone") or "UTC").strip()
    now_utc = datetime.now(dt_timezone.utc)
    if tzname.upper()=="UTC" or ZoneInfo is None:
        return f"Current time in {tzname or 'UTC'}: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC"
    try:
        tz = ZoneInfo(tzname)
    except Exception:
        return f"Current time (UTC): {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC. Unknown timezone '{tzname}'."
    local_dt = now_utc.astimezone(tz)
    off = local_dt.strftime('%z')
    off_fmt = f"UTC{off[:3]}:{off[3:]}" if off else "UTC"
    return f"Current time in {tzname}: {local_dt.strftime('%Y-%m-%d %H:%M:%S')} ({off_fmt})"

async def tool_search_osm_restaurants(arguments: Dict[str, Any]) -> str:
    lat = float(arguments["latitude"]); lon = float(arguments["longitude"])
    limit = int(arguments.get("limit", 10)); radius_m = int(arguments.get("radius_m", DEFAULT_SEARCH_RADIUS_M))
    query = f"""
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
            data = await overpass_query(client, query)
        except httpx.HTTPStatusError as e:
            return f"Overpass error {e.response.status_code}. Reduce radius/limit and try again."
        except Exception as e:
            return f"Error querying Overpass: {e}"
    els = data.get("elements", [])
    if not els:
        return f"No OSM restaurants found near {lat}, {lon} within {radius_m} m."
    lines=[f"OSM restaurants near {lat}, {lon} (radius {radius_m} m):",""]
    for i, el in enumerate(els[:limit], 1):
        tags = el.get("tags") or {}
        name = tags.get("name","Unnamed")
        cuisine = format_cuisine_tag(tags)
        phone = tags.get("phone") or tags.get("contact:phone") or "N/A"
        website = tags.get("website") or tags.get("contact:website") or "N/A"
        opening = format_hours(tags); addr = format_osm_address(tags)
        osm_type = el.get("type","node"); osm_id = el.get("id"); url = osm_url(osm_type, osm_id) if osm_id else "N/A"
        if "lat" in el and "lon" in el: el_lat, el_lon = el["lat"], el["lon"]
        else:
            center = el.get("center") or {}; el_lat, el_lon = center.get("lat","N/A"), center.get("lon","N/A")
        lines += [f"{i}. {name}",
                  f"   OSM: {url}",
                  f"   Coords: {el_lat}, {el_lon}",
                  f"   Address: {addr}",
                  f"   Cuisine: {cuisine}",
                  f"   Phone: {phone}",
                  f"   Website: {website}",
                  f"   Opening hours: {opening}",
                  ""]
    return "\n".join(lines).strip()

async def tool_get_osm_place_details(arguments: Dict[str, Any]) -> str:
    osm_type = str(arguments["osm_type"]).lower().strip(); osm_id = int(arguments["osm_id"])
    if osm_type not in {"node","way","relation"}:
        return "osm_type must be one of: node, way, relation."
    query = f"""[out:json][timeout:25]; {osm_type}({osm_id}); out tags center;"""
    async with httpx.AsyncClient() as client:
        try:
            data = await overpass_query(client, query)
        except httpx.HTTPStatusError as e:
            return f"Overpass error {e.response.status_code}."
        except Exception as e:
            return f"Error querying Overpass: {e}"
    els = data.get("elements", [])
    if not els:
        return f"No element found for {osm_type} {osm_id}."
    el = els[0]; tags = el.get("tags") or {}
    name = tags.get("name","Unnamed"); addr = format_osm_address(tags)
    cuisine = format_cuisine_tag(tags)
    phone = tags.get("phone") or tags.get("contact:phone") or "N/A"
    website = tags.get("website") or tags.get("contact:website") or "N/A"
    opening = format_hours(tags); url = osm_url(osm_type, osm_id)
    if "lat" in el and "lon" in el: el_lat, el_lon = el["lat"], el["lon"]
    else:
        center = el.get("center") or {}; el_lat, el_lon = center.get("lat","N/A"), center.get("lon","N/A")
    lines=[f"Details for {name}","",f"OSM: {url}",f"Type/ID: {osm_type} {osm_id}",
           f"Coords: {el_lat}, {el_lon}",f"Address: {addr}",f"Cuisine: {cuisine}",
           f"Phone: {phone}",f"Website: {website}",f"Opening hours: {opening}","",
           "All tags:",json.dumps(tags, ensure_ascii=False, indent=2)]
    return "\n".join(lines).strip()

async def tool_translate_ja_to_en(arguments: Dict[str, Any]) -> str:
    if not _model_ready or _tokenizer is None:
        return f"[translation-error] mBART not ready: {_model_error or 'unknown error'}"
    text = arguments["text"]; max_length = int(arguments.get("max_length", 512))
    _tokenizer.src_lang = "ja_XX"
    encoded = _tokenizer(text, return_tensors="pt", truncation=True)
    with torch.no_grad():
        generated = _model.generate(
            **encoded,
            forced_bos_token_id=_tokenizer.lang_code_to_id["en_XX"],
            max_length=max_length,
        )
    translation = _tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
    return translation

async def tool_ping(arguments: Dict[str, Any]) -> str:
    return f"pong: {arguments.get('msg','ok')}"

# ===== Register tools =====
@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(name="get_current_time", description="Get the current time.", inputSchema=schema_get_current_time()),
        Tool(name="search_osm_restaurants", description="Find nearby restaurants from OSM (no key).", inputSchema=schema_search_osm_restaurants()),
        Tool(name="get_osm_place_details", description="Get detailed tags for an OSM element.", inputSchema=schema_get_osm_place_details()),
        Tool(name="translate_ja_to_en", description="Translate Japanese to English.", inputSchema=schema_translate_ja_to_en()),
        Tool(name="ping", description="Quick connectivity check.", inputSchema=schema_ping()),
    ]

async def _with_timeout(coro, seconds: float, msg: str):
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        return msg

@mcp_server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    try:
        if name == "get_current_time":
            out = await _with_timeout(tool_get_current_time(arguments), 5.0, "Timed out getting current time.")
        elif name == "search_osm_restaurants":
            out = await _with_timeout(tool_search_osm_restaurants(arguments), 25.0, "Timed out searching OSM restaurants.")
        elif name == "get_osm_place_details":
            out = await _with_timeout(tool_get_osm_place_details(arguments), 20.0, "Timed out getting OSM place details.")
        elif name == "translate_ja_to_en":
            out = await _with_timeout(tool_translate_ja_to_en(arguments), 60.0, "Timed out translating text.")
        elif name == "ping":
            out = await _with_timeout(tool_ping(arguments), 3.0, "Timed out pinging.")
        else:
            out = f"Unknown tool: {name}"
    except Exception as e:
        out = f"Unhandled error in tool '{name}': {e}"
    return [TextContent(type="text", text=out)]

# ===== JSON-RPC endpoint at "/" =====
class JSONRPCRequest(BaseModel):
    jsonrpc: str | None = None
    id: int | str | None = None
    method: str
    params: dict | None = None

def _tool_to_dict(t: Tool) -> dict:
    return {
        "name": t.name,
        "description": t.description or "",
        "inputSchema": t.inputSchema or {"type": "object", "properties": {}},
    }

async def handle_streamable_http(request: Request):
    if request.method != "POST":
        return PlainTextResponse("Method Not Allowed", status_code=405)
    try:
        body = await request.json()
        req = JSONRPCRequest(**body)
    except Exception:
        return JSONResponse({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Parse error"}}, status_code=200)

    rid = req.id
    if req.method == "initialize":
        return JSONResponse({"jsonrpc":"2.0","id":rid,"result":{
            "protocolVersion":"2025-06-18","capabilities":{},"serverInfo":{"name":SERVICE_NAME,"version":"1.0.0"}}})
    if req.method == "tools/list":
        tools = [_tool_to_dict(t) for t in await list_tools()]
        return JSONResponse({"jsonrpc":"2.0","id":rid,"result":{"tools":tools}})
    if req.method == "tools/call":
        params = req.params or {}
        name = params.get("name"); arguments = params.get("arguments") or {}
        content = await call_tool(name, arguments)
        result_content = [{"type": "text", "text": c.text} for c in content]
        return JSONResponse({"jsonrpc":"2.0","id":rid,"result":{"content":result_content}})
    return JSONResponse({"jsonrpc":"2.0","id":rid,"error":{"code":-32601,"message":f"Method not found: {req.method}"}}, status_code=200)

# ===== Info & health =====
async def info(_request: Request):
    return JSONResponse({
        "service": SERVICE_NAME,
        "version": "1.0.0",
        "endpoints": {"rpc": "/", "health": "/health", "openapi": "/openapi.json", "info": "/info"},
        "tools": [t.name for t in await list_tools()],
        "model": {"name": MODEL_NAME, "ready": _model_ready, "error": _model_error},
    })

async def health(_request: Request):
    return JSONResponse({"status": "healthy" if _model_ready else "degraded",
                         "service": SERVICE_NAME,
                         "model_ready": _model_ready,
                         "model_error": _model_error})

async def openapi(_request: Request):
    return JSONResponse({
        "openapi":"3.0.0",
        "info":{"title":"Translator + OSM MCP Server","version":"1.0.0","description":"Combined tool server"},
        "servers":[{"url":f"http://localhost:{PORT}"}],
        "paths":{"/":{"post":{"summary":"Streamable HTTP JSON-RPC"}}},
    })

# ===== Lifespan (do model load here; DO NOT crash on failure) =====
async def lifespan(app):
    await load_model_on_startup()
    yield

# ===== Starlette app =====
app = Starlette(
    routes=[
        Route("/", endpoint=handle_streamable_http, methods=["POST"]),
        Route("/health", endpoint=health),
        Route("/openapi.json", endpoint=openapi),
        Route("/info", endpoint=info),
    ],
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    print(f"Starting combined MCP server on http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="debug")
