// Initialize FullCalendar
document.addEventListener('DOMContentLoaded', function() {
    const calendarEl = document.getElementById('calendar');

    const calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay'
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
        }
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

    // Socket.IO connection (ready for backend)
    // Uncomment when backend is ready
    /*
    const socket = io('http://localhost:5000');

    socket.on('connect', function() {
        console.log('Connected to backend');
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
    });
    */
});
