import asyncio
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from transformers import MBart50TokenizerFast, MBartForConditionalGeneration
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
import uvicorn

# Initialize model
model_name = "facebook/mbart-large-50-many-to-many-mmt"
print("Loading model... This may take a minute...")
tokenizer = MBart50TokenizerFast.from_pretrained(model_name)
model = MBartForConditionalGeneration.from_pretrained(model_name)
print("Model loaded successfully!")

# Create MCP server
mcp_server = Server("japanese-translator")

@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="translate_ja_to_en",
            description="Translate Japanese text to English using mBART model",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string", 
                        "description": "Japanese text to translate"
                    },
                    "max_length": {
                        "type": "integer", 
                        "description": "Maximum length of translation", 
                        "default": 512
                    }
                },
                "required": ["text"]
            }
        )
    ]

@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "translate_ja_to_en":
        text = arguments["text"]
        max_length = arguments.get("max_length", 512)
        
        print(f"Translating: {text}")
        
        # Set Japanese as source
        tokenizer.src_lang = "ja_XX"
        
        # Encode
        encoded = tokenizer(text, return_tensors="pt", padding=True, truncation=True)
        
        # Generate English translation
        generated_tokens = model.generate(
            **encoded,
            forced_bos_token_id=tokenizer.lang_code_to_id["en_XX"],
            max_length=max_length
        )
        
        # Decode
        translation = tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0]
        
        print(f"Translation: {translation}")
        
        return [TextContent(type="text", text=translation)]

# SSE endpoints
async def handle_sse(request):
    transport = SseServerTransport("/message")
    await transport.handle_sse(request, mcp_server)

async def handle_messages(request):
    transport = SseServerTransport("/message")
    await transport.handle_post_message(request, mcp_server)

# OpenAPI endpoint - handle multiple paths
async def openapi(request):
    return JSONResponse({
        "openapi": "3.0.0",
        "info": {
            "title": "Japanese Translator MCP Server",
            "version": "1.0.0",
            "description": "MCP server for translating Japanese text to English"
        },
        "servers": [
            {"url": "http://localhost:8765"}
        ],
        "paths": {
            "/sse": {
                "get": {
                    "summary": "SSE endpoint for MCP communication",
                    "responses": {
                        "200": {"description": "SSE stream"}
                    }
                }
            }
        }
    })

# Health check endpoint
async def health(request):
    return JSONResponse({"status": "healthy", "service": "japanese-translator"})

# Root endpoint
async def root(request):
    return JSONResponse({
        "service": "Japanese Translator MCP Server",
        "version": "1.0.0",
        "endpoints": {
            "sse": "/sse",
            "health": "/health",
            "openapi": "/openapi.json"
        }
    })

# Create Starlette app with catch-all for openapi.json
app = Starlette(
    routes=[
        Route("/", endpoint=root),
        Route("/sse", endpoint=handle_sse),
        Route("/message", endpoint=handle_messages, methods=["POST"]),
        Route("/openapi.json", endpoint=openapi),
        Route("/sse/openapi.json", endpoint=openapi),  # Handle /sse/openapi.json
        Route("/openapi.json/openapi.json", endpoint=openapi),  # Handle duplicate
        Route("/health", endpoint=health),
    ]
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    print("Starting Japanese Translator MCP Server on http://localhost:8765")
    print("Endpoints:")
    print("  - Root: http://localhost:8765")
    print("  - SSE: http://localhost:8765/sse")
    print("  - Health: http://localhost:8765/health")
    print("  - OpenAPI: http://localhost:8765/openapi.json")
    uvicorn.run(app, host="0.0.0.0", port=8765)