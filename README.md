hii, to start this, just create a python env, download the requirements file, and run the python file app.py. This will start the server and run the 
website on localhost:5001

create a .env file, and enter the following 



feat: optimize LLM selection and migrate to browser-native TTS

- Switched to a high-performance LLM with ~1s latency.
- Enhanced memory capacity (note: intermittent context loss may occur).
- Removed Puter intermediary to eliminate dependency and API costs.
- Implemented local browser speech synthesis for voice output.


# LLM Provider: "openrouter" or "cohere" or "groq"
LLM_PROVIDER=cohere

# OpenRouter API Key
OPENROUTER_API_KEY=

# Cohere API Key
COHERE_API_KEY=

# GROQ_API_KEY

GROQ_API_KEY=

# ElevenLabs API Key (for STT and TTS)
ELEVENLABS_API_KEY=

you will have to login to openrouter, cohere and elevenlabs and get their api keys and add in your .env file... 
