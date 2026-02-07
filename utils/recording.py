"""
Recording and metadata utilities for Garage Booking Assistant
Handles saving recordings and metadata to disk
"""
import os
import json
import logging
from pydub import AudioSegment
from io import BytesIO

logger = logging.getLogger(__name__)

active_recording_sessions = {}

def start_recording_session(session_id, timestamp):
    """Initialize a new recording session"""
    active_recording_sessions[session_id] = {
        'user_chunks': [],
        'bot_chunks': [],
        'metadata': [],
        'timestamp': timestamp
    }
    logger.info(f"Started recording session: {session_id}")
    return session_id

def add_user_audio_to_session(session_id, wav_bytes):
    """Add user audio chunk to the recording session"""
    if session_id in active_recording_sessions:
        active_recording_sessions[session_id]['user_chunks'].append(wav_bytes)
        logger.info(f"Added user audio to session {session_id} ({len(wav_bytes)} bytes)")
    else:
        logger.warning(f"Session {session_id} not found in active recordings")

def add_bot_audio_to_session(session_id, audio_bytes):
    """Add bot TTS audio chunk to the recording session"""
    if session_id in active_recording_sessions:
        active_recording_sessions[session_id]['bot_chunks'].append(audio_bytes)
        logger.info(f"Added bot audio to session {session_id} ({len(audio_bytes)} bytes)")
    else:
        logger.warning(f"Session {session_id} not found in active recordings")

def add_metadata_to_session(session_id, user_text, bot_text, latency_info):
    """Add conversation metadata to the recording session"""
    if session_id in active_recording_sessions:
        active_recording_sessions[session_id]['metadata'].append({
            'user_text': user_text,
            'bot_text': bot_text,
            'latency_ms': latency_info
        })
        logger.info(f"Added metadata to session {session_id}")
    else:
        logger.warning(f"Session {session_id} not found in active recordings")

def finalize_recording_session(session_id, combined_audio_dir, metadata_dir, latency_records):
    """
    Finalize and save the complete recording session.
    Combines all user and bot audio chunks into a single file.
    
    Filename format: garage_booking_2025-02-04_14-30-52.wav
    """
    if session_id not in active_recording_sessions:
        logger.error(f"Session {session_id} not found in active recordings")
        return None

    try:
        session_data = active_recording_sessions[session_id]
        
        # Combine all audio chunks
        combined_audio = AudioSegment.empty()
        silence_between = AudioSegment.silent(duration=300)  # 300ms pause between turns
        
        num_turns = max(len(session_data['user_chunks']), len(session_data['bot_chunks']))
        
        for i in range(num_turns):
            # Add user audio if available
            if i < len(session_data['user_chunks']):
                user_wav_bytes = session_data['user_chunks'][i]
                user_audio = AudioSegment.from_wav(BytesIO(user_wav_bytes))
                combined_audio += user_audio
                combined_audio += silence_between
            
            # Add bot audio if available
            if i < len(session_data['bot_chunks']):
                bot_audio_bytes = session_data['bot_chunks'][i]
                # Bot audio might be in different format (MP3 from ElevenLabs)
                # Try multiple formats
                try:
                    bot_audio = AudioSegment.from_mp3(BytesIO(bot_audio_bytes))
                except:
                    try:
                        bot_audio = AudioSegment.from_wav(BytesIO(bot_audio_bytes))
                    except:
                        logger.warning(f"Could not load bot audio for turn {i}")
                        continue
                
                combined_audio += bot_audio
                combined_audio += silence_between
        
        # Create human-readable filename with timestamp
        # Format: garage_booking_2025-02-04_14-30-52.wav
        from datetime import datetime
        timestamp_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = f'garage_booking_{timestamp_str}.wav'
        
        # Save combined audio
        os.makedirs(combined_audio_dir, exist_ok=True)
        combined_path = os.path.join(combined_audio_dir, filename)
        combined_audio.export(combined_path, format='wav')
        logger.info(f"Saved combined audio: {combined_path}")
        
        # Calculate total latency from all turns
        total_latency = sum(
            sum(turn['latency_ms'].values()) 
            for turn in session_data['metadata']
        )
        avg_turn_latency = total_latency / len(session_data['metadata']) if session_data['metadata'] else 0
        
        # Add to global latency tracking
        for turn in session_data['metadata']:
            latency_records.append(sum(turn['latency_ms'].values()))
        
        avg_latency = sum(latency_records) / len(latency_records) if latency_records else 0
        
        # Save metadata with same timestamp format
        os.makedirs(metadata_dir, exist_ok=True)
        metadata_filename = f'garage_booking_{timestamp_str}.json'
        metadata_path = os.path.join(metadata_dir, metadata_filename)
        
        metadata = {
            'session_id': session_id,
            'timestamp': session_data['timestamp'],
            'recording_time': timestamp_str,
            'audio_file': filename,
            'turns': session_data['metadata'],
            'summary': {
                'total_turns': len(session_data['metadata']),
                'total_latency_ms': round(total_latency, 2),
                'avg_turn_latency_ms': round(avg_turn_latency, 2),
                'overall_avg_latency_ms': round(avg_latency, 2),
                'session_count': len(latency_records)
            }
        }
        
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Saved metadata: {metadata_path}")
        logger.info(f"Session summary: {len(session_data['metadata'])} turns, avg latency: {avg_turn_latency:.2f}ms")
        logger.info(f"📁 Filename: {filename}")
        
        # Clean up session from memory
        del active_recording_sessions[session_id]
        
        return avg_latency, filename
        
    except Exception as e:
        logger.error(f"Error finalizing recording session: {e}")
        import traceback
        traceback.print_exc()
        return None, None

# def save_recording_metadata(session_id, user_text, bot_text, timestamp, latency_info, metadata_dir, latency_records):
#     """Save metadata for a recording session with latency information"""
#     try:
#         metadata_path = os.path.join(metadata_dir, f'{session_id}.json')

#         # Calculate total latency
#         total_latency = sum(latency_info.values())

#         # Add to global latency tracking
#         latency_records.append(total_latency)

#         # Calculate average latency
#         avg_latency = sum(latency_records) / len(latency_records)

#         metadata = {
#             'session_id': session_id,
#             'timestamp': timestamp,
#             'user_text': user_text,
#             'bot_text': bot_text,
#             'audio_file': f'{session_id}_combined.wav',
#             'latency_ms': {
#                 'audio_conversion': round(latency_info.get('audio_conversion', 0), 2),
#                 'vad_validation': round(latency_info.get('vad_validation', 0), 2),
#                 'silence_trimming': round(latency_info.get('silence_trimming', 0), 2),
#                 'asr_transcription': round(latency_info.get('asr_transcription', 0), 2),
#                 'llm_response': round(latency_info.get('llm_response', 0), 2),
#                 'tts_generation': round(latency_info.get('tts_generation', 0), 2),
#                 'total': round(total_latency, 2)
#             },
#             'average_latency_ms': round(avg_latency, 2),
#             'session_count': len(latency_records)
#         }

#         with open(metadata_path, 'w') as f:
#             json.dump(metadata, f, indent=2)

#         logger.info(f"Saved metadata: {metadata_path}")
#         logger.info(f"Total latency: {total_latency:.2f}ms | Average: {avg_latency:.2f}ms")
#         return avg_latency
#     except Exception as e:
#         logger.error(f"Error saving metadata: {e}")
#         return None
