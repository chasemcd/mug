import * as pgg  from './phaser_gym_graphics.js';

var socket = io({
    transports: ['websocket'],
    upgrade: false
});


// HUD
export function showHUD() {
    $('#hudText').show()
}

export function hideHUD() {
    $('#hudText').hide()
}

export function updateHUDText(text) {
    $('#hudText').html(text)
}

// Key Listeners

var pressedKeys = {};

export function enableKeyListener(input_mode) {
    pressedKeys = {};
    $(document).on('keydown', function(event) {
        // DIAG-01: Capture timestamp at the very first line before any processing
        const keypressTimestamp = performance.now();

        // List of keys to prevent default behavior for (scroll the window)
        var keysToPreventDefault = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', ' ']; // Includes space (' ')

        if (keysToPreventDefault.includes(event.key)) {
            event.preventDefault(); // Prevent default behavior for specified keys
        }

        // If we're using the single keystroke input method, we just send the key when it's pressed.
        // This means no composite actions.
        if (input_mode == "single_keystroke") {
            pgg.addHumanKeyPressToBuffer({key: event.key, keypressTimestamp: keypressTimestamp});
            socket.emit('send_pressed_keys', {'pressed_keys': Array(event.key), session_id: window.sessionId});
            return;
        }

        // Otherwise, we keep track of the keys that are pressed and send them on request
        if (pressedKeys[event.key]) {
            return; // Key is already pressed, so exit the function
        }

        pressedKeys[event.key] = true; // Add key to pressedKeys when it is pressed
        pgg.updatePressedKeys(pressedKeys, keypressTimestamp);
    });

    $(document).on('keyup', function(event) {
        if (input_mode == "single_keystroke") {
            return;
        }

        // If we're tracking pressed keys, remove it
        delete pressedKeys[event.key]; // Remove key from pressedKeys when it is released
        pgg.updatePressedKeys(pressedKeys);
    });
}


export function disableKeyListener() {
        $(document).off('keydown');
        $(document).off('keyup');
        pressedKeys = {};
}

// Episode Transition Overlay

/**
 * Show the episode transition overlay with "waiting" message.
 * Call this when waiting for the server to send the next episode state.
 */
export function showEpisodeWaiting(message = "Next round will begin shortly...") {
    $('#episodeTransitionText').text(message);
    $('#episodeCountdown').text('');
    $('#episodeTransitionOverlay').addClass('visible');
}

/**
 * Show countdown before episode starts.
 * Returns a promise that resolves when countdown completes.
 *
 * @param {number} seconds - Number of seconds to count down
 * @param {string} message - Message to show above countdown
 * @returns {Promise} Resolves when countdown completes
 */
export function showEpisodeCountdown(seconds = 3, message = "Get ready!") {
    return new Promise((resolve) => {
        $('#episodeTransitionText').text(message);
        $('#episodeTransitionOverlay').addClass('visible');

        let remaining = seconds;
        $('#episodeCountdown').text(remaining);

        const countdownInterval = setInterval(() => {
            remaining--;
            if (remaining > 0) {
                $('#episodeCountdown').text(remaining);
            } else {
                clearInterval(countdownInterval);
                $('#episodeCountdown').text('GO!');

                // Brief delay to show "GO!" before hiding
                setTimeout(() => {
                    hideEpisodeOverlay();
                    resolve();
                }, 500);
            }
        }, 1000);
    });
}

/**
 * Hide the episode transition overlay.
 */
export function hideEpisodeOverlay() {
    $('#episodeTransitionOverlay').removeClass('visible');
}
