"""
LLM Provider utilities for Garage Booking Assistant
Supports multiple LLM providers: OpenRouter, Cohere
"""
import logging
import requests
import json
import cohere

logger = logging.getLogger(__name__)


def get_llm_response_openrouter(user_message, api_key):
    """Get response from OpenRouter API"""
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:5000",
                "X-Title": "Garage Booking Assistant",
            },
            data=json.dumps({
                "model": "qwen/qwen3-4b:free",
                "messages": [
                    {
                        "role": "user",
                        "content": f"You are a helpful garage booking assistant. Help users book garage appointments, check availability, and answer questions about garage services. Be concise and friendly.\n\nUser: {user_message}\nAssistant:"
                    }
                ],
                "max_tokens": 500
            }),
            timeout=30
        )

        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content']

    except requests.exceptions.HTTPError as e:
        logger.error(f"OpenRouter HTTP Error: {e}")
        try:
            error_detail = response.json()
            logger.error(f"API Error details: {error_detail}")
        except:
            logger.error(f"Response text: {response.text}")
        raise
    except Exception as e:
        logger.error(f"OpenRouter Error: {e}")
        raise


def get_llm_response_cohere(user_message, api_key, system_message=None):
    """Get response from Cohere API"""
    try:
        co = cohere.ClientV2(api_key)

        if system_message is None:
            system_message = "You are a helpful garage booking assistant. Help users book garage appointments, check availability, and answer questions about garage services. Be concise and friendly."

        response = co.chat(
            model="command-a-03-2025",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            max_tokens=500
        )

        return response.message.content[0].text

    except Exception as e:
        logger.error(f"Cohere Error: {e}")
        raise

def stream_llm_response_cohere(user_message, api_key, system_message=None):
    try:
        co = cohere.ClientV2(api_key)

        if system_message is None:
            system_message = "You are a helpful garage booking assistant. Help users book garage appointments, check availability, and answer questions about garage services. Be concise and friendly."

        stream = co.chat_stream(
            model="command-a-03-2025",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            max_tokens=500
        )

        for event in stream:
            if not hasattr(event, "type"):
                continue

            if event.type == "content-delta":
                delta = event.delta

                # ✅ Case 1: Cohere docs style → event.delta.message.content.text
                if hasattr(delta, "message"):
                    msg = delta.message
                    if hasattr(msg, "content") and hasattr(msg.content, "text"):
                        token = msg.content.text
                        if token:
                            yield token
                            continue

                # ✅ Case 2: Older structured format → event.delta.content[*].text
                if hasattr(delta, "content"):
                    for item in delta.content:
                        if getattr(item, "type", None) == "text":
                            token = item.text
                            if token:
                                yield token

    except Exception as e:
        logger.error(f"Cohere Streaming Error: {e}")
        raise



def build_booking_system_prompt(booking_state):
    """
    Build a conversation-aware system prompt
    Uses history instead of tracking individual fields - simpler and faster
    """
    conversation_history = booking_state.get_conversation_history()

    system_prompt = f"""You are a garage booking assistant. Your job is to collect booking information efficiently.

INFORMATION NEEDED (in order):
1. Full name
2. Car registration number
3. Car make and model
4. Current mileage
5. Service contract/warranty? (yes/no)
6. What service or issue brings them in

CONVERSATION SO FAR:
{conversation_history}

RULES:
- Be concise - max 2 short sentences
- Ask for ONE missing piece of information at a time
- Follow the order above
- Never repeat questions - check the conversation history
- Don't ask for date/time until all 6 pieces above are collected
- Once you have all 6, say you'll check available dates
- Don't be chatty - stay focused on the task"""

    return system_prompt


def get_llm_response(user_message, provider, openrouter_key=None, cohere_key=None, system_message=None):
    """Get response from configured LLM provider"""
    try:
        logger.info(f"Sending to {provider.upper()}: {user_message}")

        if provider == 'openrouter':
            llm_response = get_llm_response_openrouter(user_message, openrouter_key)
        elif provider == 'cohere':
            llm_response = get_llm_response_cohere(user_message, cohere_key, system_message=system_message)
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")

        logger.info(f"LLM response: {llm_response}")
        return llm_response

    except Exception as e:
        logger.error(f"Error getting LLM response: {e}")
        return "I'm sorry, I'm having trouble processing your request right now. Please try again."


def stream_llm_response(user_message, provider, openrouter_key=None, cohere_key=None, system_message=None):
    if provider == 'openrouter':
        raise NotImplementedError("Streaming not implemented for OpenRouter yet")
    elif provider == 'cohere':
        return stream_llm_response_cohere(user_message, cohere_key, system_message=system_message)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
