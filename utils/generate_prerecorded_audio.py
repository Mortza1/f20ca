"""
Generate Pre-recorded TTS Audio Files
Run this once to create all the audio files you'll use for fast responses

Usage:
    python generate_prerecorded_audio.py --output-dir ./audio_files --voice-id YOUR_VOICE_ID
"""

import os
import argparse
from pathlib import Path
from elevenlabs.client import ElevenLabs
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# All the questions we need to pre-record
AUDIO_SCRIPTS = {
    "greeting.wav": "Hi! I'm here to help you book a garage appointment. What's your full name?",
    
    "name.wav": "What's your full name?",
    
    "car_reg.wav": "What's your car registration number?",
    
    "car_model.wav": "What's the make and model of your car?",
    
    "mileage.wav": "What's the current mileage on your vehicle?",
    
    "warranty.wav": "Is your car currently under warranty or a service contract?",
    
    "issue.wav": "What service or issue can we help you with today?",
    
    "completion.wav": "Perfect! I have all your details. Let me check our available dates for you.",
    
    # Optional: some common follow-ups
    "confirm_yes.wav": "Great, thank you!",
    
    "didnt_catch.wav": "Sorry, I didn't quite catch that. Could you repeat it?",
    
    "almost_done.wav": "Almost done! Just a couple more details.",
}


def generate_audio_file(client: ElevenLabs, text: str, voice_id: str, 
                       model: str, output_path: Path):
    """
    Generate a single audio file using ElevenLabs TTS
    """
    try:
        logger.info(f"Generating: {output_path.name}")
        logger.info(f"  Text: {text}")
        
        # Generate audio
        audio_generator = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=model,
            output_format="mp3_44100_128"  # High quality
        )
        
        # Save to file
        with open(output_path, 'wb') as f:
            for chunk in audio_generator:
                f.write(chunk)
        
        logger.info(f"✓ Saved: {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to generate {output_path.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Generate pre-recorded TTS audio files')
    parser.add_argument('--output-dir', type=str, default='./audio_files',
                       help='Directory to save audio files')
    parser.add_argument('--api-key', type=str, required=True,
                       help='ElevenLabs API key')
    parser.add_argument('--voice-id', type=str, default='21m00Tcm4TlvDq8ikWAM',
                       help='ElevenLabs voice ID (default: Rachel)')
    parser.add_argument('--model', type=str, default='eleven_flash_v2_5',
                       help='ElevenLabs model (default: eleven_flash_v2_5)')
    
    args = parser.parse_args()
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Output directory: {output_dir.absolute()}")
    logger.info(f"Voice ID: {args.voice_id}")
    logger.info(f"Model: {args.model}")
    logger.info(f"Total files to generate: {len(AUDIO_SCRIPTS)}")
    logger.info("-" * 60)
    
    # Initialize ElevenLabs client
    client = ElevenLabs(api_key=args.api_key)
    
    # Generate all files
    success_count = 0
    failed_count = 0
    
    for filename, text in AUDIO_SCRIPTS.items():
        output_path = output_dir / filename
        
        if generate_audio_file(client, text, args.voice_id, args.model, output_path):
            success_count += 1
        else:
            failed_count += 1
    
    # Summary
    logger.info("-" * 60)
    logger.info(f"✓ Successfully generated: {success_count}/{len(AUDIO_SCRIPTS)}")
    if failed_count > 0:
        logger.warning(f"✗ Failed: {failed_count}/{len(AUDIO_SCRIPTS)}")
    
    logger.info(f"\nAll files saved to: {output_dir.absolute()}")
    logger.info("\nYou can now use these pre-recorded files in your chatbot!")
    logger.info("Next steps:")
    logger.info("1. Copy audio files to your static assets folder")
    logger.info("2. Update frontend to handle 'use_prerecorded' flag")
    logger.info("3. Map filenames to audio URLs in frontend")


if __name__ == "__main__":
    main()
