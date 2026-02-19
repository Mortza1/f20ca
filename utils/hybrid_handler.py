"""
Hybrid Handler - Orchestrates Parser + State Machine + Fallback LLM
This replaces your current LLM-only flow
"""
import time
import logging
from typing import Dict, Any, Tuple, Optional

from utils.booking_state_machine import DialogueEngine, BookingField
from utils.llm_parser import (
    build_parser_prompt,
    build_fallback_prompt,
    parse_llm_json_response,
    validate_parsed_data,
    should_use_parser,
    is_greeting,
    log_parsing_attempt
)

logger = logging.getLogger(__name__)


class HybridBookingHandler:
    """
    Main handler that decides:
    1. Use parser LLM (fast)
    2. Use state machine (instant)
    3. Use fallback LLM (slow but natural)
    """
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.dialogue_engine = DialogueEngine()
        self.conversation_history = []  # For fallback LLM context
    
    def process_user_message(self, user_message: str, 
                            llm_call_function,
                            stream_llm_function=None) -> Dict[str, Any]:
        """
        Main entry point
        
        Args:
            user_message: What user said
            llm_call_function: Your existing LLM function (non-streaming)
            stream_llm_function: Your existing streaming LLM function (optional)
        
        Returns:
            {
                'bot_response': str,
                'use_prerecorded': bool,
                'audio_filename': str or None,
                'is_complete': bool,
                'state': dict,
                'latency_breakdown': dict
            }
        """
        start_time = time.time()
        latency = {}

        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # Fast path: greetings — instant deterministic response, no LLM
        if is_greeting(user_message):
            logger.info("👋 GREETING: Using instant response")
            greeting = self.get_greeting()

            self.conversation_history.append({
                "role": "assistant",
                "content": greeting['bot_response']
            })

            latency['greeting'] = (time.time() - start_time) * 1000
            greeting['latency_breakdown'] = latency
            greeting['state'] = self.dialogue_engine.state.to_dict()
            greeting['updated_fields'] = []
            return greeting

        # Skip parser if booking is already complete
        if self.dialogue_engine.state.is_complete():
            logger.info("📋 Booking complete — skipping parser, using fallback LLM")
            use_parser = False
        else:
            use_parser = should_use_parser(user_message)

        if use_parser:
            # Try parser first
            parser_result = self._try_parser(user_message, llm_call_function)
            latency['parser'] = parser_result['latency_ms']
            
            if parser_result['success']:
                # Parser succeeded - use state machine
                logger.info("✅ Parser succeeded - using deterministic response")
                
                # Update state
                update_meta = self.dialogue_engine.update_state(parser_result['parsed_data'])
                
                # Get next response from state machine
                response_meta = self.dialogue_engine.get_next_response(parse_success=True)
                
                # Add to history
                self.conversation_history.append({
                    "role": "assistant",
                    "content": response_meta['text']
                })
                
                latency['total'] = (time.time() - start_time) * 1000
                
                return {
                    'bot_response': response_meta['text'],
                    'use_prerecorded': response_meta['use_prerecorded'],
                    'audio_filename': response_meta.get('filename'),
                    'is_complete': self.dialogue_engine.state.is_complete(),
                    'state': self.dialogue_engine.state.to_dict(),
                    'updated_fields': update_meta['updated_fields'],
                    'latency_breakdown': latency,
                    'mode': 'parser'
                }
        
        # Parser failed or skipped - use fallback conversational LLM
        logger.info("🔄 Using fallback conversational LLM")
        fallback_result = self._use_fallback_llm(
            user_message, 
            llm_call_function,
            stream_llm_function
        )
        latency['fallback_llm'] = fallback_result['latency_ms']
        
        # Try to extract info from fallback response (opportunistic parsing)
        # This helps if LLM naturally collected info in its response
        self._opportunistic_parse_from_history(user_message)
        
        # Add to history
        self.conversation_history.append({
            "role": "assistant",
            "content": fallback_result['response']
        })
        
        latency['total'] = (time.time() - start_time) * 1000
        
        return {
            'bot_response': fallback_result['response'],
            'use_prerecorded': False,
            'audio_filename': None,
            'is_complete': self.dialogue_engine.state.is_complete(),
            'state': self.dialogue_engine.state.to_dict(),
            'updated_fields': [],
            'latency_breakdown': latency,
            'mode': 'fallback_llm',
            'streaming': fallback_result.get('streaming', False)
        }
    
    def _get_last_bot_message(self) -> Optional[str]:
        """Get the last assistant message from conversation history."""
        for msg in reversed(self.conversation_history):
            if msg["role"] == "assistant":
                return msg["content"]
        return None

    def _try_parser(self, user_message: str, llm_call_function) -> Dict[str, Any]:
        """
        Attempt to parse user message into structured data
        """
        start = time.time()

        # Build parser prompt with last bot message for context
        current_state = self.dialogue_engine.state.to_dict()
        last_bot_msg = self._get_last_bot_message()
        parser_prompt = build_parser_prompt(current_state, last_bot_message=last_bot_msg)

        # Call LLM with parser prompt
        try:
            llm_response = llm_call_function(
                user_message=f"{parser_prompt}\n\nUser's message: {user_message}",
                system_message="You are a JSON extractor. Return only valid JSON, no explanation.",
                max_tokens=200  # Parser needs very few tokens
            )
            
            # Parse JSON response
            parsed_data = parse_llm_json_response(llm_response)
            
            # Validate
            if parsed_data and validate_parsed_data(parsed_data):
                latency_ms = (time.time() - start) * 1000
                log_parsing_attempt(user_message, parsed_data, True, latency_ms)
                
                return {
                    'success': True,
                    'parsed_data': parsed_data,
                    'latency_ms': latency_ms
                }
        
        except Exception as e:
            logger.error(f"Parser LLM failed: {e}")
        
        latency_ms = (time.time() - start) * 1000
        log_parsing_attempt(user_message, None, False, latency_ms)
        
        return {
            'success': False,
            'parsed_data': None,
            'latency_ms': latency_ms
        }
    
    def _use_fallback_llm(self, user_message: str, llm_call_function,
                         stream_llm_function=None) -> Dict[str, Any]:
        """
        Use conversational LLM for ambiguous/chatty cases
        """
        start = time.time()
        
        # Build conversational prompt
        current_state = self.dialogue_engine.state.to_dict()
        missing_fields = self.dialogue_engine.state.get_missing_fields()
        
        fallback_prompt = build_fallback_prompt(
            user_message, 
            current_state, 
            missing_fields
        )
        
        # Use streaming if available
        if stream_llm_function:
            # Note: Caller will handle streaming
            # We just return the generator setup
            return {
                'response': None,  # Will be streamed
                'latency_ms': 0,  # Measured externally
                'streaming': True,
                'system_prompt': fallback_prompt
            }
        else:
            # Non-streaming
            response = llm_call_function(
                user_message=user_message,
                system_message=fallback_prompt,
                max_tokens=150
            )
            
            latency_ms = (time.time() - start) * 1000
            
            return {
                'response': response,
                'latency_ms': latency_ms,
                'streaming': False
            }
    
    def _opportunistic_parse_from_history(self, user_message: str):
        """
        Try to extract any info from user message even after fallback
        This helps maintain state even in conversational mode
        """
        # Simple keyword extraction as backup
        msg_lower = user_message.lower()
        
        # Try to catch name mentions
        if not self.dialogue_engine.state.name:
            name_indicators = ["i'm ", "my name is ", "this is ", "name's "]
            for indicator in name_indicators:
                if indicator in msg_lower:
                    # Extract potential name (very basic)
                    idx = msg_lower.find(indicator) + len(indicator)
                    potential_name = user_message[idx:].split()[0].strip(".,")
                    if len(potential_name) > 1:
                        self.dialogue_engine.state.name = potential_name.title()
        
        # Try to catch yes/no for warranty
        if self.dialogue_engine.state.warranty is None:
            if "warranty" in msg_lower or "service contract" in msg_lower:
                if any(word in msg_lower for word in ["yes", "yeah", "yep", "under"]):
                    self.dialogue_engine.state.warranty = True
                elif any(word in msg_lower for word in ["no", "nope", "not", "expired"]):
                    self.dialogue_engine.state.warranty = False
    
    def get_greeting(self) -> Dict[str, Any]:
        """
        Get initial greeting
        """
        return {
            'bot_response': "Hi! I'm here to help you book a garage appointment. What's your full name?",
            'use_prerecorded': True,
            'audio_filename': 'greeting.wav',
            'is_complete': False,
            'state': self.dialogue_engine.state.to_dict(),
            'mode': 'greeting'
        }
    
    def reset(self):
        """Reset the handler for a new session"""
        self.dialogue_engine = DialogueEngine()
        self.conversation_history = []