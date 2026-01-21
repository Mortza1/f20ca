from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO, emit
import base64
import os
import tempfile
from pydub import AudioSegment
import torch
import torchaudio
from speechbrain.inference import EncoderDecoderASR, Tacotron2, HIFIGAN
import logging
import requests
import json
from dotenv import load_dotenv

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

# Global ASR and TTS models (will be loaded on first use)
asr_model = None
tts_model = None
vocoder_model = None

# OpenRouter API configuration
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')

if not OPENROUTER_API_KEY:
    logger.error("OPENROUTER_API_KEY not found in environment variables!")
    raise ValueError("Please set OPENROUTER_API_KEY in .env file")

def get_llm_response(user_message):
    """Get response from LLM via OpenRouter API"""
    try:
        logger.info(f"Sending to LLM: {user_message}")

        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:5000",
                "X-Title": "Garage Booking Assistant",
            },
            data=json.dumps({
                "model": "google/gemma-3n-e2b-it:free",
                "messages": [
                    {
                        "role": "user",
                        "content": f"You are a helpful garage booking assistant. Help users book garage appointments, check availability, and answer questions about garage services. Be concise and friendly.\n\nUser: {user_message}\nAssistant:"
                    }
                ]
            }),
            timeout=30
        )

        response.raise_for_status()
        result = response.json()

        llm_response = result['choices'][0]['message']['content']
        logger.info(f"LLM response: {llm_response}")

        return llm_response

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error getting LLM response: {e}")
        try:
            error_detail = response.json()
            logger.error(f"API Error details: {error_detail}")
        except:
            logger.error(f"Response text: {response.text}")
        return "I'm sorry, I'm having trouble processing your request right now. Please try again."
    except Exception as e:
        logger.error(f"Error getting LLM response: {e}")
        return "I'm sorry, I'm having trouble processing your request right now. Please try again."

def load_asr_model():
    """Load SpeechBrain ASR model (lazy loading)"""
    global asr_model
    if asr_model is None:
        logger.info("Loading SpeechBrain ASR model...")
        try:
            # Using a pretrained ASR model from SpeechBrain
            # This will download the model on first run (~300MB)
            asr_model = EncoderDecoderASR.from_hparams(
                source="speechbrain/asr-crdnn-rnnlm-librispeech",
                savedir="pretrained_models/asr-crdnn-rnnlm-librispeech"
            )
            logger.info("ASR model loaded successfully!")
        except Exception as e:
            logger.error(f"Failed to load ASR model: {e}")
            raise
    return asr_model

def load_tts_models():
    """Load SpeechBrain TTS models (lazy loading)"""
    global tts_model, vocoder_model
    if tts_model is None or vocoder_model is None:
        logger.info("Loading SpeechBrain TTS models...")
        try:
            # Load Tacotron2 for text-to-mel spectrogram
            tts_model = Tacotron2.from_hparams(
                source="speechbrain/tts-tacotron2-ljspeech",
                savedir="pretrained_models/tts-tacotron2-ljspeech"
            )

            # Load HiFiGAN vocoder for mel-to-waveform
            vocoder_model = HIFIGAN.from_hparams(
                source="speechbrain/tts-hifigan-ljspeech",
                savedir="pretrained_models/tts-hifigan-ljspeech"
            )

            logger.info("TTS models loaded successfully!")
        except Exception as e:
            logger.error(f"Failed to load TTS models: {e}")
            raise
    return tts_model, vocoder_model

def text_to_speech(text):
    """Convert text to speech audio"""
    try:
        logger.info(f"Generating speech for: {text}")

        # Load TTS models
        tts, vocoder = load_tts_models()

        # Generate mel spectrogram from text
        mel_output, mel_length, alignment = tts.encode_text(text)

        # Generate waveform from mel spectrogram
        waveforms = vocoder.decode_batch(mel_output)

        # Save to temporary file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as wav_file:
            wav_path = wav_file.name
            torchaudio.save(
                wav_path,
                waveforms.squeeze(1).cpu(),
                22050  # Sample rate for TTS model
            )

        logger.info(f"Speech generated: {wav_path}")
        return wav_path

    except Exception as e:
        logger.error(f"Error generating speech: {e}")
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
        logger.info("Received audio data")

        # Decode base64 audio
        audio_format = data.get('format', 'webm')
        audio_base64 = data.get('audio')

        if not audio_base64:
            emit('error', {'message': 'No audio data received'})
            return

        audio_bytes = base64.b64decode(audio_base64)
        logger.info(f"Decoded audio: {len(audio_bytes)} bytes")

        # Convert WebM to WAV
        wav_path = convert_webm_to_wav(audio_bytes)
        logger.info(f"Converted to WAV: {wav_path}")

        # Load ASR model (lazy loading)
        model = load_asr_model()

        # Transcribe audio
        logger.info("Transcribing audio...")
        transcription = model.transcribe_file(wav_path)

        # Clean up WAV file
        os.remove(wav_path)

        logger.info(f"Transcription: {transcription}")

        # Get LLM response
        llm_response = get_llm_response(transcription)

        # Generate TTS audio from LLM response
        logger.info("Generating TTS audio...")
        audio_path = text_to_speech(llm_response)

        if audio_path:
            # Read audio file and encode to base64
            with open(audio_path, 'rb') as f:
                audio_data = base64.b64encode(f.read()).decode('utf-8')

            # Clean up temp file
            os.remove(audio_path)

            # Send LLM response with audio back to frontend
            emit('bot_response', {
                'user_text': transcription,
                'bot_text': llm_response,
                'audio': audio_data,
                'success': True
            })
        else:
            # Fallback if TTS fails
            emit('bot_response', {
                'user_text': transcription,
                'bot_text': llm_response,
                'success': True
            })

    except Exception as e:
        logger.error(f"Error processing audio: {e}")
        emit('error', {'message': f'Transcription failed: {str(e)}'})

if __name__ == '__main__':
    logger.info("Starting Garage Booking Assistant server...")
    logger.info("Server running on http://localhost:5000")
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
