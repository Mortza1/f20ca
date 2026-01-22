"""
LLM Provider utilities for Garage Booking Assistant
Supports multiple LLM providers: OpenRouter, Cohere
"""
import os
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


def get_llm_response_cohere(user_message, api_key):
    """Get response from Cohere API"""
    try:
        co = cohere.ClientV2(api_key)

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


def get_llm_response(user_message, provider, openrouter_key=None, cohere_key=None):
    """Get response from configured LLM provider"""
    try:
        logger.info(f"Sending to {provider.upper()}: {user_message}")

        if provider == 'openrouter':
            llm_response = get_llm_response_openrouter(user_message, openrouter_key)
        elif provider == 'cohere':
            llm_response = get_llm_response_cohere(user_message, cohere_key)
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")

        logger.info(f"LLM response: {llm_response}")
        return llm_response

    except Exception as e:
        logger.error(f"Error getting LLM response: {e}")
        return "I'm sorry, I'm having trouble processing your request right now. Please try again."
