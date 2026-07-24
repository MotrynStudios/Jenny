import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

groq = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)

openrouter = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

GROQ_TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL")

MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", 500))
VISION_MAX_TOKENS = 300  # Lower limit for vision to avoid long reasoning
DISCORD_MAX_LENGTH = 2000


async def generate(messages):
    try:
        response = groq.chat.completions.create(
            model=GROQ_TEXT_MODEL,
            messages=messages,
            max_tokens=MAX_TOKENS,
        )
        content = response.choices[0].message.content
        # Truncate if too long for Discord
        if len(content) > DISCORD_MAX_LENGTH:
            content = content[:DISCORD_MAX_LENGTH - 3] + "..."
        return content

    except Exception as e:
        print(f"Groq failed, falling back to OpenRouter: {e}")

        response = openrouter.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=messages,
            max_tokens=MAX_TOKENS,
        )

        content = response.choices[0].message.content
        # Truncate if too long for Discord
        if len(content) > DISCORD_MAX_LENGTH:
            content = content[:DISCORD_MAX_LENGTH - 3] + "..."
        return content


async def generate_vision(messages, image_url):
    # Extract the user's actual text input from the last message
    user_text = messages[-1]["content"]
    
    # First, get image analysis from vision model with user's context
    vision_messages = [
        {
            "role": "system",
            "content": "You are an image analyzer. Describe what you see in the image objectively and concisely. Focus on the main elements, actions, and context that are relevant to the user's message. Do not add personality or conversational elements."
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"The user says: '{user_text}'. Describe this image in detail, focusing on aspects relevant to what the user said."
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image_url
                    }
                }
            ]
        }
    ]

    try:
        response = groq.chat.completions.create(
            model=GROQ_VISION_MODEL,
            messages=vision_messages,
            max_tokens=VISION_MAX_TOKENS,
        )
        image_analysis = response.choices[0].message.content
    except Exception as e:
        print(f"Groq vision failed: {e}")
        return await generate(messages)

    # Now forward the analysis to the text model with context
    text_messages = messages.copy()
    
    # Insert image analysis as system context before the user's message
    text_messages.insert(-1, {
        "role": "system",
        "content": f"The user sent an image. This is what's in it: {image_analysis}. React naturally to this content - do NOT describe or explain what you see, just respond to it as if you saw it yourself with your own eyes."
    })

    # Generate response using the text model
    return await generate(text_messages)