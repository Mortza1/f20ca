"""
LLM Parser - Fast, Structured Extraction
Minimal tokens, deterministic output
"""
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def build_parser_prompt(current_state_dict: Dict[str, Any],
                        last_bot_message: Optional[str] = None) -> str:
    """
    Build minimal parsing prompt. Kept short to reduce token count and latency.
    """

    context = ""
    if last_bot_message:
        context = f'Bot asked: "{last_bot_message}"\n'

    prompt = f"""{context}State: {json.dumps(current_state_dict)}
Extract NEW info only. Return JSON: {{"name","car_reg","car_model","mileage"(int),"warranty"(bool),"issue"}} null if absent."""

    return prompt


def build_fallback_prompt(user_message: str, current_state_dict: Dict[str, Any], 
                          missing_fields: list) -> str:
    """
    Build conversational LLM prompt for ambiguous cases
    Only used when parser fails or user is chatting
    """
    
    missing_fields_str = ", ".join([f.value for f in missing_fields])
    
    prompt = f"""You are a helpful garage booking assistant.

Current booking state:
{json.dumps(current_state_dict, indent=2)}

Missing information: {missing_fields_str}

User said: "{user_message}"

Respond naturally and helpfully. If they're chatting or asking questions, answer briefly. 
Then guide them back to providing the next missing piece of information.

Keep response under 2 sentences. Be warm but efficient."""
    
    return prompt


def parse_llm_json_response(llm_output: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON from LLM response
    Handles markdown fences, extra text, etc.
    """
    try:
        # Try direct parse first
        return json.loads(llm_output.strip())
    except json.JSONDecodeError:
        # Try to extract JSON from markdown fences
        if "```json" in llm_output:
            start = llm_output.find("```json") + 7
            end = llm_output.find("```", start)
            json_str = llm_output[start:end].strip()
            return json.loads(json_str)
        
        if "```" in llm_output:
            start = llm_output.find("```") + 3
            end = llm_output.find("```", start)
            json_str = llm_output[start:end].strip()
            return json.loads(json_str)
        
        # Try to find JSON-like structure
        start = llm_output.find("{")
        end = llm_output.rfind("}") + 1
        if start != -1 and end > start:
            json_str = llm_output[start:end]
            return json.loads(json_str)
        
        return None


def validate_parsed_data(parsed: Dict[str, Any]) -> bool:
    """
    Basic validation of parsed JSON
    Returns True if parsing extracted something meaningful
    """
    if not isinstance(parsed, dict):
        return False
    
    # Check if any field has a non-null value
    non_null_values = [v for v in parsed.values() if v is not None]
    
    return len(non_null_values) > 0


def is_greeting(user_message: str) -> bool:
    """Check if message is a pure greeting (no booking info)."""
    msg = user_message.lower().strip()
    greetings = ["hello", "hi", "hey", "good morning", "good afternoon",
                 "good evening", "howdy", "what's up", "how are you"]
    if any(msg.startswith(g) for g in greetings) and len(msg.split()) < 8:
        # Check it doesn't also contain booking info
        info_indicators = ["i'm ", "my name", "name is", "registration",
                           "miles", "warranty", "oil", "brake", "service"]
        if not any(ind in msg for ind in info_indicators):
            return True
    return False


def should_use_parser(user_message: str) -> bool:
    """
    Heuristic: should we try parser or go straight to conversational LLM?

    Parser works well for:
    - Short factual statements
    - Direct answers (even with questioning tone like "It's Murtaza?")

    Skip parser for:
    - Real questions (starting with question words)
    - Greetings (handled separately as fast path)
    - Very long messages
    """
    msg = user_message.lower().strip()

    # Greetings are handled by a separate fast path, skip parser
    if is_greeting(msg):
        return False

    # Only skip for real questions that START with question words
    # "It's Murtaza?" should NOT be skipped — it's an answer with questioning tone
    question_starters = ["what ", "when ", "where ", "how ", "why ",
                         "can you ", "could you ", "will you "]
    if any(msg.startswith(q) for q in question_starters):
        return False

    # Very long messages might need conversational handling
    if len(msg.split()) > 30:
        return False

    return True


# Example usage logging
def log_parsing_attempt(user_message: str, parsed: Optional[Dict], 
                       success: bool, latency_ms: float):
    """Log parsing metrics for debugging"""
    logger.info(f"""
    📊 PARSE ATTEMPT:
    Input: {user_message}
    Success: {success}
    Parsed: {parsed}
    Latency: {latency_ms:.2f}ms
    """)