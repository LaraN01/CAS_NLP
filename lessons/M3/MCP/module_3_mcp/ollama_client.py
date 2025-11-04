# ollama_client.py
import ollama
import json
import asyncio
import re
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

"""
Updated Ollama client script that connects to the MCP server to fetch tools and resources.
It allows the LLM to call tools and access resources defined in the mcp_server.py file.

Changes made:
- Added more tool definitions in mcp_server.py (here fetched in get_mcp_tools())
- Added resource in mcp_server.py (info about CAS NLP program from UniBE website)
-------------
Deprecated, because it didn't really work (changed resource to tool, then it worked):
- Added resource fetching from MCP server:
  - Added get_mcp_resources() function: Fetches resources from the MCP server using session.list_resources() and session.read_resource()
    - stores them in a dictionary with their URI, name, description, MIME type, and content.
  - Added build_system_message() function: Dynamically creates the system message that includes information about available resources, showing their URI, description, and a preview of their content.
  - Updated main() function: Fetches resources at startup
  - Builds the system message with resource info. The system message now informs the LLM about available resources.

"""

# MODEL = "qwen3:latest" # Using one of the models you have. You need to use a model that accept tools. check ollama models for more
MODEL = "qwen3:4b"


def build_system_message(resources: dict) -> dict:
    """Builds a system message that includes information about available resources."""
    resource_info = ""
    if resources:
        resource_info = "\n\nAvailable resources:\n"
        for uri, resource in resources.items():
            resource_info += f"- {uri}: {resource['description']}\n"
            # Include a preview of the content (first 200 chars)
            preview = resource['content'][:200] + "..." if len(resource['content']) > 200 else resource['content']
            resource_info += f"  Preview: {preview}\n"

    return {
        "role": "system",
        "content": (
            "You have access to tools and resources. When a tool result is provided, "
            "use it directly to answer the user's request. "
            "For numbers, state the number clearly. "
            "For text, summarize, explain, or analyze it as needed. "
            "Do not reveal chain-of-thought! Only provide the final answer."
            "/nothink\n"
            f"{resource_info}"
        )
    }


# This function connects to the MCP server to get the list of available tools
async def get_mcp_tools(session: ClientSession) -> list:
    """Fetches tools from the MCP server and formats them for Ollama."""
    print("--- Client: Fetching tools from MCP server... ---")
    tool_list_response = await session.list_tools()

    ollama_tools = []
    for tool in tool_list_response.tools:
        ollama_tools.append({
            'type': 'function',
            'function': {
                'name': tool.name,
                'description': tool.description,
                'parameters': tool.inputSchema,
            },
        })
    print(f"--- Client: Loaded {len(ollama_tools)} tools. ---")
    return ollama_tools


async def get_mcp_resources(session: ClientSession) -> dict:
    """Fetches resources from the MCP server and returns them as a dictionary."""
    print("--- Client: Fetching resources from MCP server... ---")
    resource_list_response = await session.list_resources()

    resources = {}
    for resource in resource_list_response.resources:
        # Read the resource content
        resource_content = await session.read_resource(resource.uri)

        # Extract text content
        content_text = ""
        if resource_content.contents:
            for content in resource_content.contents:
                if isinstance(content, types.TextContent):
                    content_text += content.text

        resources[resource.uri] = {
            'name': resource.name,
            'description': resource.description,
            'mimeType': resource.mimeType,
            'content': content_text
        }

    print(f"--- Client: Loaded {len(resources)} resources. ---")
    return resources


def strip_chain_of_thought(text: str) -> str:
    """
    Removes chain-of-thought reasoning (text between <think> and </think> tags) from the response.
    Otherwise reasoning models like Qwen cannot be stopped from not revealing their chain-of-thought with the system prompt alone.

    Parameters
    ----------
    text : str
        The text potentially containing <think>...</think> tags

    Returns
    -------
    str
        The text with chain-of-thought removed
    """
    # First, try to find and remove complete <think>...</think> blocks
    # re.DOTALL makes '.' match newlines as well, so it works across multiple lines
    # re.IGNORECASE handles both <think> and <THINK> variants
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Handle cases where reasoning appears after "A:" or "Assistant:" prefix
    # and ends with </think> (common in Qwen models)
    # This removes from "A:" or "Assistant:" up to and including </think>
    cleaned = re.sub(r'^(A:|Assistant:).*?</think>\s*', '', cleaned, flags=re.DOTALL | re.IGNORECASE | re.MULTILINE)


    # Clean up any extra whitespace left behind
    cleaned = re.sub(r'\n\s*\n+', '\n\n', cleaned)

    return cleaned.strip()


async def main():
    """Main loop to run the Ollama client and interact with the MCP server."""
    
    # Define how to start our MCP server as a subprocess
    server_params = StdioServerParameters(
        command="python",
        args=["mcp_server.py"],
    )

    # Use the stdio_client to manage the server subprocess
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection to the MCP server
            await session.initialize()

            # Get the tool definitions from our running server
            tools = await get_mcp_tools(session)

            # Get the resources from our running server
            resources = await get_mcp_resources(session)

            # Build system message with resource information
            system_msg = build_system_message(resources)

            print("\nOllama MCP Client Initialized. How can I help?")
            print("Model:", MODEL)
            print("Type 'exit' to quit.")

            messages = [system_msg]  # Initialize with system message

            while True:
                user_input = input("\n> ")
                if user_input.lower() in ['exit', 'exit()', 'quit', 'quit()']:
                    break

                messages.append({'role': 'user', 'content': user_input})

                # 1. First call to Ollama with tools
                response = ollama.chat(
                    model=MODEL,
                    messages=messages,
                    tools=tools
                )
                messages.append(response['message'])
                
                # 2. Check if the model decided to use a tool
                if response['message'].get('tool_calls'):
                    tool_calls = response['message']['tool_calls']
                    tool_call = tool_calls[0] # Handle one tool call for simplicity
                    tool_name = tool_call['function']['name']
                    tool_args = tool_call['function']['arguments']

                    print(f"--- Client: Model wants to call '{tool_name}' with args: {tool_args} ---")

                    # 3. Execute the tool by calling the MCP server
                    result = await session.call_tool(tool_name, arguments=tool_args)
                    
                    # Extract the text content from the MCP tool result
                    tool_output = ""
                    if result.content and isinstance(result.content[0], types.TextContent):
                        tool_output = result.content[0].text
                    
                    print(f"--- Client: Received tool output: '{tool_output[:100]}...' ---")

                    # 4. Send the tool output back to Ollama
                    messages.append({'role': 'tool', 'content': tool_output})
                    final_response = ollama.chat(model=MODEL, messages=messages)

                    # Strip chain-of-thought from the response for display only
                    cleaned_content = strip_chain_of_thought(f"Assistant: {final_response['message']['content']}")
                    print(f"\nAssistant:\n{cleaned_content}")

                    # Append the full message object to maintain conversation history
                    messages.append(final_response['message'])
                else:
                    # If no tool was called, just print the response
                    # Strip chain-of-thought from the response for display
                    cleaned_content = strip_chain_of_thought(response['message']['content'])
                    print(f"\nAssistant:\n{cleaned_content}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")