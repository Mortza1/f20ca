from flask import Flask, render_template, send_from_directory, request
from flask_socketio import SocketIO, emit
import base64
import os
import logging
from dotenv import load_dotenv
from datetime import datetime
import shutil
import time
from elevenlabs.client import ElevenLabs
from io import BytesIO

# Import utilities
from utils.llm import get_llm_response, build_booking_system_prompt
from utils.audio import convert_webm_to_wav, convert_webm_to_wav_bytes
from utils.recording import save_recording_metadata
from utils.booking_state import get_or_create_session
from utils.calendar import initialize_calendar
from utils.vad import initialize_vad, validate_speech, validate_speech_bytes, trim_silence

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__,
            static_folder='.',
            template_folder='.')
app.config['SECRET_KEY'] = 'garage-booking-secret'

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ElevenLabs Client for STT
# TTS is handled by frontend using ElevenLabs via Puter.js
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
if not ELEVENLABS_API_KEY:
    logger.error("ELEVENLABS_API_KEY not found in environment variables!")
    raise ValueError("Please set ELEVENLABS_API_KEY in .env file")

elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# LLM Provider Configuration
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'cohere').lower()  # Default to cohere
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
COHERE_API_KEY = os.getenv('COHERE_API_KEY')

# Validate configuration
if LLM_PROVIDER == 'openrouter' and not OPENROUTER_API_KEY:
    logger.error("OPENROUTER_API_KEY not found in environment variables!")
    raise ValueError("Please set OPENROUTER_API_KEY in .env file")

if LLM_PROVIDER == 'cohere' and not COHERE_API_KEY:
    logger.error("COHERE_API_KEY not found in environment variables!")
    raise ValueError("Please set COHERE_API_KEY in .env file")

logger.info(f"LLM Provider: {LLM_PROVIDER.upper()}")
logger.info("STT Provider: ELEVENLABS")

# Recording directories
RECORDINGS_DIR = 'recordings'
COMBINED_AUDIO_DIR = os.path.join(RECORDINGS_DIR, 'combined_audio')
METADATA_DIR = os.path.join(RECORDINGS_DIR, 'metadata')

# Ensure recording directories exist
for directory in [COMBINED_AUDIO_DIR, METADATA_DIR]:
    os.makedirs(directory, exist_ok=True)

# Initialize calendar
initialize_calendar()

# Initialize VAD model
initialize_vad()

# Global latency tracking
latency_records = []

# LLM functions moved to utils/llm.py

# STT is now handled by ElevenLabs API - no model loading needed!
# TTS is handled by frontend using ElevenLabs via Puter.js
# No heavyweight models to load at startup!

# Audio and recording functions moved to utils/audio.py and utils/recording.py

@app.route('/')
def index():
    """Serve the main HTML page"""
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    """Serve static files (CSS, JS, JSON)"""
    return send_from_directory('.', path)

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info("Client connected")
    emit('status', {'message': 'Connected to server'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info("Client disconnected")

@socketio.on('audio_data')
def handle_audio_data(data):
    """Handle incoming audio data from frontend"""
    try:
        # Start total timing
        start_time = time.time()
        latency_info = {}

        logger.info("Received audio data")

        # Check if recording mode is enabled
        recording_mode = data.get('recording_mode', False)
        session_id = None
        timestamp = None

        if recording_mode:
            # Generate unique session ID with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            session_id = f"session_{timestamp}"
            logger.info(f"Recording mode enabled - Session ID: {session_id}")

        # Decode base64 audio
        audio_base64 = data.get('audio')

        if not audio_base64:
            emit('error', {'message': 'No audio data received'})
            return

        audio_bytes = base64.b64decode(audio_base64)
        logger.info(f"Decoded audio: {len(audio_bytes)} bytes")

        # # Convert WebM to WAV (with timing)
        # conversion_start = time.time()
        # wav_path = convert_webm_to_wav(audio_bytes)
        # latency_info['audio_conversion'] = (time.time() - conversion_start) * 1000
        # logger.info(f"Converted to WAV: {wav_path} ({latency_info['audio_conversion']:.2f}ms)")

        # # Validate speech with VAD (with timing)
        # vad_start = time.time()
        # has_speech, speech_duration = validate_speech(wav_path, min_speech_duration_ms=200)
        # latency_info['vad_validation'] = (time.time() - vad_start) * 1000
        # logger.info(f"VAD validation: {has_speech} ({latency_info['vad_validation']:.2f}ms)")

        # if not has_speech:
        #     logger.warning("No speech detected by VAD, rejecting audio")
        #     os.remove(wav_path)
        #     emit('error', {'message': 'No speech detected. Please try again.'})
        #     return

        # # Trim silence to reduce STT latency (with timing)
        # trim_start = time.time()
        # trim_success, trimmed_path, duration_saved = trim_silence(wav_path)
        # latency_info['silence_trimming'] = (time.time() - trim_start) * 1000

        # if trim_success:
        #     logger.info(f"Trimmed silence: saved {duration_saved}ms ({latency_info['silence_trimming']:.2f}ms processing)")
        #     # Replace wav_path with trimmed version
        #     os.remove(wav_path)
        #     wav_path = trimmed_path

        conversion_start = time.time()
        wav_bytes = convert_webm_to_wav_bytes(audio_bytes)
        latency_info['audio_conversion'] = (time.time() - conversion_start) * 1000
        logger.info(f"Converted to WAV in-memory: {len(wav_bytes)} bytes ({latency_info['audio_conversion']:.2f}ms)")

        vad_start = time.time()
        has_speech, speech_duration = validate_speech_bytes(wav_bytes, min_speech_duration_ms=250)
        latency_info['vad_validation'] = (time.time() - vad_start) * 1000
        logger.info(f"VAD validation: {has_speech} ({latency_info['vad_validation']:.2f}ms)")

        if not has_speech:
            logger.warning("No speech detected by VAD, rejecting audio")
            emit('error', {'message': 'No speech detected. Please try again.'})
            return
        
        latency_info['silence_trimming'] = 0  # No trimming in in-memory path

        # # Keep a copy of user audio path for later combination
        # user_wav_path = None
        # if recording_mode and session_id:
        #     # Save temporary copy for later combination
        #     user_wav_path = wav_path.replace('.wav', '_user.wav')
        #     shutil.copy2(wav_path, user_wav_path)

        # # Transcribe audio using ElevenLabs STT (with timing)
        # logger.info("Transcribing audio with ElevenLabs...")
        # asr_start = time.time()

        # # Read WAV file as BytesIO for ElevenLabs API
        # with open(wav_path, 'rb') as audio_file:
        #     audio_data = BytesIO(audio_file.read())

        # # Call ElevenLabs STT API
        # transcription_result = elevenlabs_client.speech_to_text.convert(
        #     file=audio_data,
        #     model_id="scribe_v2",
        #     language_code="eng"  # English
        # )

        # transcription = transcription_result.text
        # latency_info['asr_transcription'] = (time.time() - asr_start) * 1000
        # logger.info(f"Transcription: {transcription} ({latency_info['asr_transcription']:.2f}ms)")

        # # Clean up original WAV file
        # os.remove(wav_path)

        logger.info("Transcribing audio with ElevenLabs...")
        asr_start = time.time()

        audio_data = BytesIO(wav_bytes)

        transcription_result = elevenlabs_client.speech_to_text.convert(
            file=audio_data,
            model_id="scribe_v2",
            language_code="eng"
        )

        transcription = transcription_result.text
        latency_info['asr_transcription'] = (time.time() - asr_start) * 1000
        logger.info(f"Transcription: {transcription} ({latency_info['asr_transcription']:.2f}ms)")

        # Handle empty transcription
        if not transcription or transcription.strip() == "":
            logger.warning("Empty transcription received, skipping LLM call")
            emit('error', {'message': 'Could not understand audio. Please try again.'})
            return

        # Get or create booking session for this socket connection
        session_id_booking = request.sid  # Use Flask-SocketIO's session ID
        booking_session = get_or_create_session(session_id_booking)

        # Build system prompt based on current booking state
        system_prompt = build_booking_system_prompt(booking_session)

        # Get LLM response (with timing)
        llm_start = time.time()
        llm_response = get_llm_response(
            transcription,
            LLM_PROVIDER,
            openrouter_key=OPENROUTER_API_KEY,
            cohere_key=COHERE_API_KEY,
            system_message=system_prompt
        )
        latency_info['llm_response'] = (time.time() - llm_start) * 1000
        logger.info(f"LLM response received ({latency_info['llm_response']:.2f}ms)")

        # Add this conversation turn to history
        booking_session.add_to_history(transcription, llm_response)

        # TTS is now handled by frontend using ElevenLabs via Puter.js
        # No backend TTS generation needed!
        latency_info['tts_generation'] = 0  # Frontend handles this

        # Calculate backend latency (excludes frontend TTS)
        backend_latency = (time.time() - start_time) * 1000
        logger.info(f"Total backend latency: {backend_latency:.2f}ms (conversion: {latency_info['audio_conversion']:.2f}ms + VAD: {latency_info['vad_validation']:.2f}ms + trim: {latency_info['silence_trimming']:.2f}ms + ASR: {latency_info['asr_transcription']:.2f}ms + LLM: {latency_info['llm_response']:.2f}ms + overhead: {backend_latency - sum(latency_info.values()):.2f}ms)")

        # # Save metadata if recording mode is enabled
        # avg_latency = None
        # if recording_mode and session_id and user_wav_path:
        #     # Note: We only save user audio now, bot audio is generated on frontend
        #     # Save metadata with latency info
        #     avg_latency = save_recording_metadata(
        #         session_id,
        #         transcription,
        #         llm_response,
        #         timestamp,
        #         latency_info,
        #         METADATA_DIR,
        #         latency_records
        #     )
        #     # Clean up temporary user audio file
        #     os.remove(user_wav_path)

        avg_latency = None
        if recording_mode and session_id:
            # Write WAV file off the critical path
            user_wav_path = os.path.join(COMBINED_AUDIO_DIR, f"{session_id}_user.wav")
            with open(user_wav_path, "wb") as f:
                f.write(wav_bytes)
            logger.info(f"Saved recording (off critical path): {user_wav_path}")

         # Save metadata
        avg_latency = save_recording_metadata(
            session_id,
            transcription,
            llm_response,
            timestamp,
            latency_info,
            METADATA_DIR,
            latency_records
        )

        # Send LLM response (text only, no audio) back to frontend
        # Frontend will generate speech using ElevenLabs via Puter.js
        emit('bot_response', {
            'user_text': transcription,
            'bot_text': llm_response,
            'success': True,
            'recorded': recording_mode,
            'latency_ms': {
                'backend': round(backend_latency, 2),
                'average': round(avg_latency, 2) if avg_latency else None
            }
        })

    except Exception as e:
        logger.error(f"Error processing audio: {e}")
        emit('error', {'message': f'Transcription failed: {str(e)}'})

if __name__ == '__main__':
    logger.info("Starting Garage Booking Assistant server...")
    logger.info("=" * 60)
    logger.info("Loading models...")
    logger.info("VAD: Silero VAD (local)")
    logger.info("STT: ElevenLabs API")
    logger.info("TTS: ElevenLabs (frontend)")
    logger.info(f"LLM: {LLM_PROVIDER.upper()}")
    logger.info("=" * 60)
    logger.info("Server running on http://localhost:5001")
    logger.info("Ready for requests!")
    socketio.run(app, debug=True, host='0.0.0.0', port=5001, allow_unsafe_werkzeug=True)
