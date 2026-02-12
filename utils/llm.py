"""
LLM Provider utilities for Garage Booking Assistant
Supports multiple LLM providers: OpenRouter, Cohere
"""
import logging
import requests
import json
import cohere
from groq import Groq

logger = logging.getLogger(__name__)

'''
def extract_booking_info(user_text, current_data, api_key):
    """
    提取信息并返回更新后的 JSON 字典 
    """
    try:
        client = Groq(api_key=api_key)

        # 确保 current_data 是字典而不是 None
        if current_data is None:
            current_data = {}

        prompt = f"""
        You are a data extraction engine.

        ### CURRENT STATE:
        {json.dumps(current_data)}

        ### USER INPUT:
        "{user_text}"

        ### INSTRUCTION:
        1. Update the JSON based on USER INPUT.
        2. Merge new info into CURRENT STATE.
        3. Valid keys: "name", "reg", "model", "mileage", "warranty", "issue".
        4. If user confirms warranty, set "warranty": true.
        5. Return ONLY the valid JSON object. Do not add markdown formatting.
        """

        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You output JSON only."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.1-8b-instant",
            # 开启 JSON 模式 (如果模型支持，Groq 上 Llama 3.1 支持)
            response_format={"type": "json_object"},
        )

        # 解析并返回
        return json.loads(completion.choices[0].message.content)

    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        # 失败时返回旧数据，避免清空记忆
        return current_data
'''
def get_llm_response_groq(user_message, api_key, system_message=None):
    """Get response from Cohere API"""
    try:
        client = Groq(api_key=api_key)

        if system_message is None:
            system_message = "You are a helpful garage booking assistant. Help users book garage appointments, check availability, and answer questions about garage services. Be concise and friendly."

        stream = client.chat.completions.create(
            messages=[
                # Set an optional system message. This sets the behavior of the
                # assistant and can be used to provide specific instructions for
                # how it should behave throughout the conversation.
                {
                    "role": "system",
                    "content": system_message
                },
                # Set a user message for the assistant to respond to.
                {
                    "role": "user",
                    "content": user_message,
                }
            ],

            # The language model which will generate the completion.
            #model="llama-3.1-8b-instant",
            model="openai/gpt-oss-20b",
            #model="groq/compound",
            #max_completion_tokens=200,
            stream=False,
        )
        """
        full_response = ""

        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                full_response += content

        return full_response
        """
        return stream.choices[0].message.content
    except Exception as e:
        logger.error(f"Groq Error: {e}")
        raise

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

Once you have all 6, always say you'll check available dates

CONVERSATION SO FAR:
{conversation_history}

RULES:
- Be concise - max 2 short sentences
- Ask for ONE missing piece of information at a time
- Follow the order above
- Never repeat questions - check the conversation history
- Don't ask for date/time until all 6 pieces above are collected
- Once you have all 6, always say you'll check available dates
- Don't be chatty - stay focused on the task"""

    return system_prompt
'''

def build_booking_system_prompt(booking_state):
    # 1. 获取提取出的结构化 JSON 数据
    booking_data = booking_state.get_booking_data() or "Not available yet"

    # 2. 获取最近对话 (保持不变)
    recent_turns = booking_state.get_history_list()[-2:]
    recent_chat = ""
    for turn in recent_turns:
        recent_chat += f"User: {turn['user']}\nAssistant: {turn['bot']}\n"

    # 3. 构造增强版提示词
    # 关键改动：
    # - 使用 <data> 标签包裹数据
    # - 增加 "INTERNAL STATE - DO NOT SHOW TO USER" 警告
    # - 强调自然语言回复
    system_prompt = f"""You are a helpful garage booking assistant.

<instruction>
Your goal is to collect the following 6 pieces of information naturally.
Once you have all 6, always say you'll check available dates
MISSING INFO NEEDED (in order):
1. Full name
2. Car registration number
3. Car make and model
4. Current mileage
5. Service contract/warranty? (yes/no)
6. What service or issue brings them in
Follow the order above
Once you have all 6, always say you'll check available dates
</instruction>

<internal_state>
Current Extracted Info: {booking_data}
WARNING: This data is for your reference only. DO NOT output this JSON or the raw data structure to the user.
</internal_state>

<rules>
- Be concise - max 2 short sentences
- Ask for ONE missing piece of information at a time
- Follow the order above
- Never repeat questions - check the conversation history
- Don't ask for date/time until all 6 pieces above are collected
- Once you have all 6, always say you'll check available dates
- Don't be chatty - stay focused on the task
</rules>

<conversation_context>
{recent_chat}
</conversation_context>
"""
    return system_prompt
'''
def get_llm_response(user_message, provider, openrouter_key=None, cohere_key=None,groq_key=None, system_message=None):
    """Get response from configured LLM provider"""
    try:
        logger.info(f"Sending to {provider.upper()}: {user_message}")

        if provider == 'openrouter':
            llm_response = get_llm_response_openrouter(user_message, openrouter_key)
        elif provider == 'cohere':
            llm_response = get_llm_response_cohere(user_message, cohere_key, system_message=system_message)
        elif provider == 'groq':
            llm_response = get_llm_response_groq(user_message, groq_key, system_message=system_message)
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")

        logger.info(f"LLM response: {llm_response}")
        return llm_response

    except Exception as e:
        logger.error(f"Error getting LLM response: {e}")
        return "I'm sorry, I'm having trouble processing your request right now. Please try again."
