from flask import Flask, render_template, send_from_directory, request
from flask_socketio import SocketIO, emit
import base64
import os
import logging
from dotenv import load_dotenv
from datetime import datetime
import time
from elevenlabs.client import ElevenLabs
from io import BytesIO

# Import utilities
from utils.llm import get_llm_response, build_booking_system_prompt, stream_llm_response
from utils.audio import convert_webm_to_wav_bytes
from utils.recording import (
    start_recording_session, 
    add_user_audio_to_session,
    add_bot_audio_to_session,
    add_metadata_to_session,
    finalize_recording_session
)
from utils.booking_state import get_or_create_session
from utils.my_calendar import initialize_calendar
from utils.vad import initialize_vad, validate_speech_bytes

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
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
if not ELEVENLABS_API_KEY:
    logger.error("ELEVENLABS_API_KEY not found in environment variables!")
    raise ValueError("Please set ELEVENLABS_API_KEY in .env file")

elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# LLM Provider Configuration
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'cohere').lower()
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

# Track active recording sessions per socket
# Format: {socket_id: recording_session_id}
socket_recording_map = {}


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
    # Clean up any active recording sessions for this socket
    if request.sid in socket_recording_map:
        del socket_recording_map[request.sid]


@socketio.on('start_recording')
def handle_start_recording():
    """Handle recording start event"""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        session_id = f"session_{timestamp}"
        
        # Initialize recording session
        start_recording_session(session_id, timestamp)
        
        # Map this socket to the recording session
        socket_recording_map[request.sid] = session_id
        
        logger.info(f"🔴 Recording started: {session_id} for socket {request.sid}")
        emit('recording_started', {'session_id': session_id})
        
    except Exception as e:
        logger.error(f"Error starting recording: {e}")
        emit('error', {'message': f'Failed to start recording: {str(e)}'})


@socketio.on('stop_recording')
def handle_stop_recording():
    """Handle recording stop event"""
    try:
        if request.sid not in socket_recording_map:
            logger.warning("No active recording session for this socket")
            emit('error', {'message': 'No active recording session'})
            return
        
        session_id = socket_recording_map[request.sid]
        
        # Finalize the recording session
        avg_latency, filename = finalize_recording_session(
            session_id,
            COMBINED_AUDIO_DIR,
            METADATA_DIR,
            latency_records
        )
        
        # Clean up socket mapping
        del socket_recording_map[request.sid]
        
        logger.info(f"⏹️ Recording stopped and saved: {filename}")
        emit('recording_stopped', {
            'session_id': session_id,
            'filename': filename,
            'average_latency_ms': round(avg_latency, 2) if avg_latency else None
        })
        
    except Exception as e:
        logger.error(f"Error stopping recording: {e}")
        import traceback
        traceback.print_exc()
        emit('error', {'message': f'Failed to stop recording: {str(e)}'})


@socketio.on('bot_audio')
def handle_bot_audio(data):
    """Handle bot TTS audio from frontend"""
    try:
        # Check if this socket has an active recording
        if request.sid not in socket_recording_map:
            return  # Not recording, ignore
        
        session_id = socket_recording_map[request.sid]
        
        # Decode base64 audio
        audio_base64 = data.get('audio')
        if not audio_base64:
            logger.warning("No audio data in bot_audio event")
            return
        
        audio_bytes = base64.b64decode(audio_base64)
        
        # Add to recording session
        add_bot_audio_to_session(session_id, audio_bytes)
        
        logger.info(f"📢 Bot audio added to recording {session_id} ({len(audio_bytes)} bytes)")
        
    except Exception as e:
        logger.error(f"Error handling bot audio: {e}")


@socketio.on('audio_data')
def handle_audio_data(data):
    """
    Handle incoming audio data from frontend.
    
    OPTIMIZED PIPELINE with session-based recording:
    1. Convert WebM → WAV in memory (~60-120ms)
    2. Run VAD on tensor directly (~50-120ms)
    3. Send to ElevenLabs STT API
    4. Get LLM response
    5. If recording: save user audio + metadata
    6. Return text (frontend handles TTS and sends audio back)
    """
    try:
        # Start total timing
        start_time = time.time()
        latency_info = {}

        logger.info("Received audio data")

        # Check if this socket has an active recording session
        is_recording = request.sid in socket_recording_map
        session_id = socket_recording_map.get(request.sid) if is_recording else None

        # Decode base64 audio
        audio_base64 = data.get('audio')

        if not audio_base64:
            emit('error', {'message': 'No audio data received'})
            return

        audio_bytes = base64.b64decode(audio_base64)
        logger.info(f"Decoded audio: {len(audio_bytes)} bytes")

    #    conversion from webm to wav in memory
        conversion_start = time.time()
        wav_bytes = convert_webm_to_wav_bytes(audio_bytes)
        latency_info['audio_conversion'] = (time.time() - conversion_start) * 1000
        logger.info(f"Converted to WAV in-memory: {len(wav_bytes)} bytes ({latency_info['audio_conversion']:.2f}ms)")

        # running vad on the wav bytes directly
        vad_start = time.time()
        has_speech, speech_duration = validate_speech_bytes(wav_bytes, min_speech_duration_ms=250)
        latency_info['vad_validation'] = (time.time() - vad_start) * 1000
        logger.info(f"VAD validation: {has_speech} ({latency_info['vad_validation']:.2f}ms)")

        if not has_speech:
            logger.warning("No speech detected by VAD, rejecting audio")
            emit('error', {'message': 'No speech detected. Please try again.'})
            return

        latency_info['silence_trimming'] = 0  # No trimming in in-memory path

        # Transcribe with ElevenLabs
        logger.info("Transcribing audio with ElevenLabs...")
        asr_start = time.time()

        audio_data_stt = BytesIO(wav_bytes)

        transcription_result = elevenlabs_client.speech_to_text.convert(
            file=audio_data_stt,
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

        # Get or create booking session
        session_id_booking = request.sid
        booking_session = get_or_create_session(session_id_booking)

        # Build system prompt
        system_prompt = build_booking_system_prompt(booking_session)

        # Get LLM response
        # llm_start = time.time()
        # llm_response = get_llm_response(
        #     transcription,
        #     LLM_PROVIDER,
        #     openrouter_key=OPENROUTER_API_KEY,
        #     cohere_key=COHERE_API_KEY,
        #     system_message=system_prompt
        # )
        # latency_info['llm_response'] = (time.time() - llm_start) * 1000
        # logger.info(f"LLM response received ({latency_info['llm_response']:.2f}ms)")

        logger.info("🧠 Streaming LLM response...")

        llm_start = time.time()
        full_response = ""

        # notify frontend that streaming starts
        emit('bot_stream_start', {})

        for token in stream_llm_response(
            transcription,
            LLM_PROVIDER,
            openrouter_key=OPENROUTER_API_KEY,
            cohere_key=COHERE_API_KEY,
            system_message=system_prompt
        ):
            full_response += token

            # send token to frontend in real-time
            emit('bot_token', {'token': token})

        latency_info['llm_response'] = (time.time() - llm_start) * 1000
        llm_response = full_response

        logger.info(f"LLM streaming completed ({latency_info['llm_response']:.2f}ms)")

        # notify frontend that streaming ends
        emit('bot_stream_end', {})


        # Add to history
        booking_session.add_to_history(transcription, llm_response)

        # TTS handled by frontend
        latency_info['tts_generation'] = 0

        # Calculate backend latency
        backend_latency = (time.time() - start_time) * 1000
        overhead = backend_latency - sum(latency_info.values())
        
        logger.info(f"✨ Total backend latency: {backend_latency:.2f}ms")
        logger.info(f"   → Conversion: {latency_info['audio_conversion']:.2f}ms")
        logger.info(f"   → VAD: {latency_info['vad_validation']:.2f}ms")
        logger.info(f"   → ASR: {latency_info['asr_transcription']:.2f}ms")
        logger.info(f"   → LLM: {latency_info['llm_response']:.2f}ms")
        logger.info(f"   → Overhead: {overhead:.2f}ms")

        # If recording, save user audio and metadata
        if is_recording and session_id:
            # Add user audio to recording
            add_user_audio_to_session(session_id, wav_bytes)
            
            # Add metadata to recording
            add_metadata_to_session(session_id, transcription, llm_response, latency_info)
            
            logger.info(f"🎙️ Added turn to recording {session_id}")

        # Calculate average latency for response
        latency_records.append(backend_latency)
        avg_latency = sum(latency_records) / len(latency_records)

        # Send response to frontend
        emit('bot_response', {
            'user_text': transcription,
            'bot_text': llm_response,
            'success': True,
            'is_recording': is_recording,
            'session_id': session_id if is_recording else None,
            'latency_ms': {
                'backend': round(backend_latency, 2),
                'average': round(avg_latency, 2)
            }
        })

    except Exception as e:
        logger.error(f"Error processing audio: {e}")
        import traceback
        traceback.print_exc()
        emit('error', {'message': f'Processing failed: {str(e)}'})


if __name__ == '__main__':
    logger.info("Starting Garage Booking Assistant server...")
    logger.info("=" * 60)
    logger.info("⚡ OPTIMIZED PIPELINE ENABLED ⚡")
    logger.info("In-memory audio processing: ✓")
    logger.info("Tensor-based VAD: ✓")
    logger.info("Session-based recording: ✓")
    logger.info("Expected latency reduction: ~700ms")
    logger.info("=" * 60)
    logger.info("Loading models...")
    logger.info("VAD: Silero VAD (local, tensor-optimized)")
    logger.info("STT: ElevenLabs API")
    logger.info("TTS: ElevenLabs (frontend)")
    logger.info(f"LLM: {LLM_PROVIDER.upper()}")
    logger.info("=" * 60)
    logger.info("Server running on http://localhost:5001")
    logger.info("Ready for requests!")
    socketio.run(app, debug=True, host='0.0.0.0', port=5001, allow_unsafe_werkzeug=True)