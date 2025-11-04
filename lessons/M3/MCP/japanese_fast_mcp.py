import httpx
from fastmcp import FastMCP
from transformers import MBart50TokenizerFast, MBartForConditionalGeneration

# Initialize FastMCP server
mcp = FastMCP("Japanese Translator")

# Initialize model
model_name = "facebook/mbart-large-50-many-to-many-mmt"
print("Loading model... This may take a minute...")
tokenizer = MBart50TokenizerFast.from_pretrained(model_name)
model = MBartForConditionalGeneration.from_pretrained(model_name)
print("Model loaded successfully!")


@mcp.tool()
def translate_ja_to_en(text: str, max_length: int = 512) -> str:
    """
    Translate Japanese text to English using mBART model.

    Args:
        text: Japanese text to translate
        max_length: Maximum length of translation (default: 512)

    Returns:
        English translation as a string
    """
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
    
    return translation


if __name__ == "__main__":
    # Run with HTTP transport on port 8765
    print("Starting Japanese Translator FastMCP server on http://0.0.0.0:8765")
    mcp.run(transport="http", host="0.0.0.0", port=8765)