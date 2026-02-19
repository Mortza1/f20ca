"""
Deterministic Booking State Machine
Handles all dialogue flow without LLM hallucinations
"""
import json
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum


class BookingField(Enum):
    """Ordered fields we need to collect"""
    NAME = "name"
    CAR_REG = "car_reg"
    CAR_MODEL = "car_model"
    MILEAGE = "mileage"
    WARRANTY = "warranty"
    ISSUE = "issue"


@dataclass
class BookingState:
    """Clean state representation"""
    name: Optional[str] = None
    car_reg: Optional[str] = None
    car_model: Optional[str] = None
    mileage: Optional[int] = None
    warranty: Optional[bool] = None
    issue: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def is_complete(self) -> bool:
        """Check if all fields are filled"""
        return all([
            self.name,
            self.car_reg,
            self.car_model,
            self.mileage is not None,
            self.warranty is not None,
            self.issue
        ])
    
    def get_missing_fields(self) -> list[BookingField]:
        """Return list of missing fields in order"""
        missing = []
        field_map = {
            BookingField.NAME: self.name,
            BookingField.CAR_REG: self.car_reg,
            BookingField.CAR_MODEL: self.car_model,
            BookingField.MILEAGE: self.mileage,
            BookingField.WARRANTY: self.warranty,
            BookingField.ISSUE: self.issue
        }
        
        for field in BookingField:
            if field_map[field] is None:
                missing.append(field)
        
        return missing


# Pre-written questions (to be pre-recorded via TTS)
QUESTIONS = {
    BookingField.NAME: "What's your full name?",
    BookingField.CAR_REG: "What's your car registration number?",
    BookingField.CAR_MODEL: "What's the make and model of your car?",
    BookingField.MILEAGE: "What's the current mileage on your vehicle?",
    BookingField.WARRANTY: "Is your car currently under warranty or a service contract?",
    BookingField.ISSUE: "What service or issue can we help you with today?"
}

# Confirmation messages
COMPLETION_MESSAGE = "Perfect! I have all your details. Let me check our available dates for you."
GREETING_MESSAGE = "Hi! I'm here to help you book a garage appointment. What's your full name?"


class DialogueEngine:
    """Deterministic dialogue flow - no LLM guessing"""
    
    def __init__(self):
        self.state = BookingState()
    
    def update_state(self, parsed_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update state from parsed LLM output
        Returns metadata about what changed
        """
        updates = {}
        
        # Update each field if provided
        if parsed_data.get("name"):
            self.state.name = parsed_data["name"]
            updates["name"] = True
        
        if parsed_data.get("car_reg"):
            self.state.car_reg = self._normalize_car_reg(parsed_data["car_reg"])
            updates["car_reg"] = True
        
        if parsed_data.get("car_model"):
            self.state.car_model = parsed_data["car_model"]
            updates["car_model"] = True
        
        if parsed_data.get("mileage") is not None:
            self.state.mileage = self._normalize_mileage(parsed_data["mileage"])
            updates["mileage"] = True
        
        if parsed_data.get("warranty") is not None:
            self.state.warranty = self._normalize_warranty(parsed_data["warranty"])
            updates["warranty"] = True
        
        if parsed_data.get("issue"):
            self.state.issue = parsed_data["issue"]
            updates["issue"] = True
        
        return {
            "updated_fields": list(updates.keys()),
            "num_updates": len(updates),
            "is_complete": self.state.is_complete()
        }
    
    def get_next_question(self) -> Optional[str]:
        """
        Get the next question to ask
        Returns None if booking is complete
        """
        if self.state.is_complete():
            return None
        
        missing = self.state.get_missing_fields()
        if missing:
            next_field = missing[0]
            return QUESTIONS[next_field]
        
        return None
    
    def get_next_response(self, parse_success: bool) -> Dict[str, Any]:
        """
        Main dialogue logic
        Returns response metadata for the handler
        """
        if self.state.is_complete():
            return {
                "type": "completion",
                "text": COMPLETION_MESSAGE,
                "use_prerecorded": True,
                "filename": "completion.wav"
            }
        
        if parse_success:
            # We successfully parsed something, ask next question
            next_q = self.get_next_question()
            if next_q:
                # Map question to filename
                missing_field = self.state.get_missing_fields()[0]
                return {
                    "type": "question",
                    "text": next_q,
                    "use_prerecorded": True,
                    "filename": f"{missing_field.value}.wav"
                }
        
        # Parse failed or ambiguous - use LLM fallback
        return {
            "type": "fallback_llm",
            "text": None,  # Will be generated by LLM
            "use_prerecorded": False,
            "filename": None
        }
    
    # Normalization helpers
    @staticmethod
    def _normalize_car_reg(reg: str) -> str:
        """Normalize car registration (remove spaces, uppercase)"""
        return reg.replace(" ", "").upper()
    
    @staticmethod
    def _normalize_mileage(mileage: Any) -> int:
        """Convert mileage to integer"""
        if isinstance(mileage, int):
            return mileage
        
        if isinstance(mileage, str):
            # Handle cases like "120k", "45000 miles", etc.
            mileage = mileage.lower().replace("miles", "").replace(",", "").strip()
            
            if "k" in mileage:
                # "120k" -> 120000
                num = float(mileage.replace("k", ""))
                return int(num * 1000)
            
            return int(float(mileage))
        
        return int(mileage)
    
    @staticmethod
    def _normalize_warranty(warranty: Any) -> bool:
        """Convert warranty to boolean"""
        if isinstance(warranty, bool):
            return warranty
        
        if isinstance(warranty, str):
            warranty_lower = warranty.lower()
            if warranty_lower in ["yes", "y", "true", "under warranty", "active"]:
                return True
            if warranty_lower in ["no", "n", "false", "not under warranty", "expired"]:
                return False
        
        return bool(warranty)
    
    def get_state_summary(self) -> str:
        """Get human-readable state summary"""
        lines = ["Current booking details:"]
        for field in BookingField:
            value = getattr(self.state, field.value)
            status = "✓" if value is not None else "✗"
            display_value = value if value is not None else "missing"
            lines.append(f"{status} {field.value}: {display_value}")
        
        return "\n".join(lines)