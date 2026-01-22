from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO, emit
import base64
import os
import tempfile
from pydub import AudioSegment
import logging
import requests
import json
from dotenv import load_dotenv
from datetime import datetime
import shutil
import time
import cohere
from elevenlabs.client import ElevenLabs
from io import BytesIO

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

# Global latency tracking
latency_records = []

def get_llm_response_openrouter(user_message):
    """Get response from OpenRouter API"""
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
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

def get_llm_response_cohere(user_message):
    """Get response from Cohere API"""
    try:
        co = cohere.ClientV2(COHERE_API_KEY)

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

def get_llm_response(user_message):
    """Get response from configured LLM provider"""
    try:
        logger.info(f"Sending to {LLM_PROVIDER.upper()}: {user_message}")

        if LLM_PROVIDER == 'openrouter':
            llm_response = get_llm_response_openrouter(user_message)
        elif LLM_PROVIDER == 'cohere':
            llm_response = get_llm_response_cohere(user_message)
        else:
            raise ValueError(f"Unknown LLM provider: {LLM_PROVIDER}")

        logger.info(f"LLM response: {llm_response}")
        return llm_response

    except Exception as e:
        logger.error(f"Error getting LLM response: {e}")
        return "I'm sorry, I'm having trouble processing your request right now. Please try again."

# STT is now handled by ElevenLabs API - no model loading needed!
# TTS is handled by frontend using ElevenLabs via Puter.js
# No heavyweight models to load at startup!

def combine_audio_files(user_wav_path, bot_wav_path, session_id, add_silence=True):
    """Combine user and bot audio into a single WAV file with optional silence between them"""
    try:
        # Load both audio files
        user_audio = AudioSegment.from_wav(user_wav_path)
        bot_audio = AudioSegment.from_wav(bot_wav_path)

        # Add 500ms of silence between user and bot audio
        if add_silence:
            silence = AudioSegment.silent(duration=500)  # 500ms
            combined_audio = user_audio + silence + bot_audio
        else:
            combined_audio = user_audio + bot_audio

        # Save combined audio
        dest_path = os.path.join(COMBINED_AUDIO_DIR, f'{session_id}_combined.wav')
        combined_audio.export(dest_path, format='wav')

        logger.info(f"Saved combined audio: {dest_path}")
        return dest_path
    except Exception as e:
        logger.error(f"Error combining audio files: {e}")
        return None

def save_recording_metadata(session_id, user_text, bot_text, timestamp, latency_info):
    """Save metadata for a recording session with latency information"""
    try:
        metadata_path = os.path.join(METADATA_DIR, f'{session_id}.json')

        # Calculate total latency
        total_latency = sum(latency_info.values())

        # Add to global latency tracking
        latency_records.append(total_latency)

        # Calculate average latency
        avg_latency = sum(latency_records) / len(latency_records)

        metadata = {
            'session_id': session_id,
            'timestamp': timestamp,
            'user_text': user_text,
            'bot_text': bot_text,
            'audio_file': f'{session_id}_combined.wav',
            'latency_ms': {
                'audio_conversion': round(latency_info.get('audio_conversion', 0), 2),
                'asr_transcription': round(latency_info.get('asr_transcription', 0), 2),
                'llm_response': round(latency_info.get('llm_response', 0), 2),
                'tts_generation': round(latency_info.get('tts_generation', 0), 2),
                'total': round(total_latency, 2)
            },
            'average_latency_ms': round(avg_latency, 2),
            'session_count': len(latency_records)
        }

        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Saved metadata: {metadata_path}")
        logger.info(f"Total latency: {total_latency:.2f}ms | Average: {avg_latency:.2f}ms")
        return avg_latency
    except Exception as e:
        logger.error(f"Error saving metadata: {e}")
        return None

def convert_webm_to_wav(webm_data):
    """Convert WebM audio to WAV format for SpeechBrain"""
    try:
        # Create temporary files
        with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as webm_file:
            webm_file.write(webm_data)
            webm_path = webm_file.name

        wav_path = webm_path.replace('.webm', '.wav')

        # Convert using pydub
        audio = AudioSegment.from_file(webm_path, format="webm")

        # Convert to mono, 16kHz (required by most ASR models)
        audio = audio.set_channels(1)
        audio = audio.set_frame_rate(16000)

        # Export as WAV
        audio.export(wav_path, format="wav")

        # Clean up webm file
        os.remove(webm_path)

        return wav_path

    except Exception as e:
        logger.error(f"Error converting audio: {e}")
        raise

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

        # Convert WebM to WAV (with timing)
        conversion_start = time.time()
        wav_path = convert_webm_to_wav(audio_bytes)
        latency_info['audio_conversion'] = (time.time() - conversion_start) * 1000
        logger.info(f"Converted to WAV: {wav_path} ({latency_info['audio_conversion']:.2f}ms)")

        # Keep a copy of user audio path for later combination
        user_wav_path = None
        if recording_mode and session_id:
            # Save temporary copy for later combination
            user_wav_path = wav_path.replace('.wav', '_user.wav')
            shutil.copy2(wav_path, user_wav_path)

        # Transcribe audio using ElevenLabs STT (with timing)
        logger.info("Transcribing audio with ElevenLabs...")
        asr_start = time.time()

        # Read WAV file as BytesIO for ElevenLabs API
        with open(wav_path, 'rb') as audio_file:
            audio_data = BytesIO(audio_file.read())

        # Call ElevenLabs STT API
        transcription_result = elevenlabs_client.speech_to_text.convert(
            file=audio_data,
            model_id="scribe_v2",
            language_code="eng"  # English
        )

        transcription = transcription_result.text
        latency_info['asr_transcription'] = (time.time() - asr_start) * 1000
        logger.info(f"Transcription: {transcription} ({latency_info['asr_transcription']:.2f}ms)")

        # Clean up original WAV file
        os.remove(wav_path)

        # Get LLM response (with timing)
        llm_start = time.time()
        llm_response = get_llm_response(transcription)
        latency_info['llm_response'] = (time.time() - llm_start) * 1000
        logger.info(f"LLM response received ({latency_info['llm_response']:.2f}ms)")

        # TTS is now handled by frontend using ElevenLabs via Puter.js
        # No backend TTS generation needed!
        latency_info['tts_generation'] = 0  # Frontend handles this

        # Calculate backend latency (excludes frontend TTS)
        backend_latency = (time.time() - start_time) * 1000

        # Save metadata if recording mode is enabled
        avg_latency = None
        if recording_mode and session_id and user_wav_path:
            # Note: We only save user audio now, bot audio is generated on frontend
            # Save metadata with latency info
            avg_latency = save_recording_metadata(session_id, transcription, llm_response, timestamp, latency_info)
            # Clean up temporary user audio file
            os.remove(user_wav_path)

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
    logger.info("No heavyweight models to load - using API-based services!")
    logger.info("STT: ElevenLabs API | TTS: ElevenLabs (frontend)")
    logger.info(f"LLM: {LLM_PROVIDER.upper()}")
    logger.info("=" * 60)
    logger.info("Server running on http://localhost:5001")
    logger.info("Ready for requests!")
    socketio.run(app, debug=True, host='0.0.0.0', port=5001, allow_unsafe_werkzeug=True)
