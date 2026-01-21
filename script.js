// Initialize FullCalendar
document.addEventListener('DOMContentLoaded', function() {
    const calendarEl = document.getElementById('calendar');

    const calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        headerToolbar: {
            left: 'prev,next',
            center: 'title',
            right: 'today'
        },
        height: 'auto',
        events: [
            // Sample events - these will be populated by the backend later
            {
                title: 'Garage Booking',
                start: '2026-01-25T10:00:00',
                end: '2026-01-25T12:00:00',
                color: '#ff8e3a'
            }
        ],
        eventClick: function(info) {
            alert('Event: ' + info.event.title + '\nTime: ' + info.event.start.toLocaleString());
        },
        dateClick: function(info) {
            console.log('Clicked on: ' + info.dateStr);
        },
        // Disable view switching
        viewClassNames: ['month-view-only']
    });

    calendar.render();

    // Initialize Lottie Animation
    const animation = lottie.loadAnimation({
        container: document.getElementById('lottie-animation'),
        renderer: 'svg',
        loop: true,
        autoplay: true,
        path: 'blob.json' // Path to your blob.json file
    });

    // ============ CONTINUOUS VOICE ASSISTANT LOGIC ============

    // State management
    let systemEnabled = false;
    let currentState = 'idle'; // idle, recording, processing
    let audioContext = null;
    let mediaStream = null;
    let mediaRecorder = null;
    let audioChunks = [];
    let silenceTimeout = null;
    let analyser = null;
    let vadAnimationFrame = null;

    // VAD configuration
    const VAD_THRESHOLD = 0.02; // Voice activity threshold
    const SILENCE_DURATION = 1500; // ms of silence before stopping
    const SPEECH_START_THRESHOLD = 3; // Consecutive frames above threshold to start recording

    // Get DOM elements
    const lottieContainer = document.getElementById('lottie-container');

    let speechFrameCount = 0;

    // Update UI state using blob animation
    function updateState(state) {
        currentState = state;

        // Remove all state classes
        lottieContainer.classList.remove('idle', 'recording', 'processing');

        switch(state) {
            case 'idle':
                // Pause animation, make blob smaller and dimmer
                animation.pause();
                lottieContainer.classList.add('idle');
                console.log('State: Idle - waiting for speech');
                break;
            case 'recording':
                // Play animation, make blob bigger and brighter
                animation.play();
                animation.setSpeed(1.2);
                lottieContainer.classList.add('recording');
                console.log('State: Recording - listening to speech');
                break;
            case 'processing':
                // Keep playing, slightly smaller, faster animation
                animation.play();
                animation.setSpeed(1.8);
                lottieContainer.classList.add('processing');
                console.log('State: Processing - transcribing audio');
                break;
            case 'error':
                // Pause on error
                animation.pause();
                lottieContainer.classList.add('idle');
                console.error('State: Error');
                break;
        }
    }

    // Continuous Voice Activity Detection
    function startContinuousVAD() {
        if (!analyser || !systemEnabled) return;

        const dataArray = new Uint8Array(analyser.frequencyBinCount);

        function detectVoice() {
            if (!systemEnabled) {
                vadAnimationFrame = null;
                return;
            }

            analyser.getByteTimeDomainData(dataArray);

            // Calculate RMS (Root Mean Square) for voice detection
            let sum = 0;
            for (let i = 0; i < dataArray.length; i++) {
                const normalized = (dataArray[i] - 128) / 128;
                sum += normalized * normalized;
            }
            const rms = Math.sqrt(sum / dataArray.length);

            // Voice detected
            if (rms > VAD_THRESHOLD) {
                speechFrameCount++;

                // Start recording if we detect speech and not already recording
                if (speechFrameCount >= SPEECH_START_THRESHOLD && currentState === 'idle') {
                    startRecording();
                }

                // Clear silence timeout if voice is detected during recording
                if (silenceTimeout && currentState === 'recording') {
                    clearTimeout(silenceTimeout);
                    silenceTimeout = null;
                }
            } else {
                speechFrameCount = 0;

                // Silence detected during recording - start countdown
                if (!silenceTimeout && currentState === 'recording') {
                    silenceTimeout = setTimeout(() => {
                        stopRecording();
                    }, SILENCE_DURATION);
                }
            }

            vadAnimationFrame = requestAnimationFrame(detectVoice);
        }

        detectVoice();
    }

    // Initialize continuous listening system
    async function initializeContinuousListening() {
        try {
            updateState('idle');

            // Request microphone access
            mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    sampleRate: 16000,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });

            // Create audio context for VAD
            audioContext = new (window.AudioContext || window.webkitAudioContext)({
                sampleRate: 16000
            });

            // Setup analyser for VAD
            analyser = audioContext.createAnalyser();
            analyser.fftSize = 2048;
            analyser.smoothingTimeConstant = 0.8;

            const source = audioContext.createMediaStreamSource(mediaStream);
            source.connect(analyser);

            systemEnabled = true;

            // Start continuous VAD
            startContinuousVAD();

            console.log('Continuous listening initialized');

        } catch (error) {
            console.error('Error initializing continuous listening:', error);
            updateState('error');
            systemEnabled = false;
            alert('Could not access microphone. Please check permissions.');
        }
    }

    // Start recording when speech is detected
    function startRecording() {
        if (currentState !== 'idle') return;

        try {
            // Setup MediaRecorder
            mediaRecorder = new MediaRecorder(mediaStream, {
                mimeType: 'audio/webm;codecs=opus'
            });

            audioChunks = [];

            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };

            mediaRecorder.onstop = () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                sendAudioToBackend(audioBlob);
            };

            // Start recording
            mediaRecorder.start();
            updateState('recording');

            console.log('Recording started');

        } catch (error) {
            console.error('Error starting recording:', error);
        }
    }

    // Stop recording when silence is detected
    function stopRecording() {
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
            updateState('processing');
            console.log('Recording stopped');
        }

        if (silenceTimeout) {
            clearTimeout(silenceTimeout);
            silenceTimeout = null;
        }
    }

    // Send audio to backend
    function sendAudioToBackend(audioBlob) {
        console.log('Audio blob size:', audioBlob.size, 'bytes');

        // TODO: Send via WebSocket to backend
        // For now, just simulate processing
        setTimeout(() => {
            // Return to idle state to listen for next utterance
            updateState('idle');
            console.log('Ready for next speech');
        }, 2000);

        // When backend is ready, use this:
        /*
        const reader = new FileReader();
        reader.onloadend = () => {
            const base64Audio = reader.result.split(',')[1];
            socket.emit('audio_data', {
                audio: base64Audio,
                format: 'webm'
            });
        };
        reader.readAsDataURL(audioBlob);
        */
    }

    // Auto-start continuous listening on page load
    initializeContinuousListening();

    // Socket.IO connection (ready for backend)
    // Uncomment when backend is ready
    /*
    const socket = io('http://localhost:5000');

    socket.on('connect', function() {
        console.log('Connected to backend');
    });

    socket.on('transcription', function(data) {
        console.log('Transcription:', data.text);
        // Process the transcription here
    });

    socket.on('booking_update', function(data) {
        // Add new event to calendar
        calendar.addEvent({
            title: data.title,
            start: data.start,
            end: data.end,
            color: '#ff8e3a'
        });
    });

    socket.on('bot_response', function(data) {
        console.log('Bot says:', data.message);
        updateState('ready');
    });
    */
});
