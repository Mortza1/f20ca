from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO, emit
import base64
import os
import tempfile
from pydub import AudioSegment
import torch
from speechbrain.inference import EncoderDecoderASR
import logging

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

# Global ASR model (will be loaded on first use)
asr_model = None

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

        # Send transcription back to frontend
        emit('transcription', {
            'text': transcription,
            'success': True
        })

    except Exception as e:
        logger.error(f"Error processing audio: {e}")
        emit('error', {'message': f'Transcription failed: {str(e)}'})

if __name__ == '__main__':
    logger.info("Starting Garage Booking Assistant server...")
    logger.info("Server running on http://localhost:5000")
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
