import * as phaserGraphics  from './phaser_gym_graphics.js';

var socket = io({
    transports: ['websocket'],
    upgrade: false
});


// HUD
export function showHUD() {
    $('#hudText').show()
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
            phaserGraphics.addHumanKeyPressToBuffer({key: event.key, keypressTimestamp: keypressTimestamp});
            socket.emit('send_pressed_keys', {'pressed_keys': Array(event.key), session_id: window.sessionId});
            return;
        }

        // Otherwise, we keep track of the keys that are pressed and send them on request
        if (pressedKeys[event.key]) {
            return; // Key is already pressed, so exit the function
        }

        pressedKeys[event.key] = true; // Add key to pressedKeys when it is pressed
        phaserGraphics.updatePressedKeys(pressedKeys, keypressTimestamp);
    });

    $(document).on('keyup', function(event) {
        if (input_mode == "single_keystroke") {
            return;
        }

        // If we're tracking pressed keys, remove it
        delete pressedKeys[event.key]; // Remove key from pressedKeys when it is released
        phaserGraphics.updatePressedKeys(pressedKeys);
    });
}


export function disableKeyListener() {
        $(document).off('keydown');
        $(document).off('keyup');
        pressedKeys = {};
}

// Episode Transition Overlay

/**
 * Ensure the episode transition overlay exists in the DOM.
 * Creates it dynamically if it was removed (e.g., by Phaser initialization).
 */
function ensureOverlayExists() {
    let overlay = $('#episodeTransitionOverlay');
    if (overlay.length === 0) {
        // Overlay doesn't exist - create it dynamically
        const gameContainer = $('#gameContainer');
        if (gameContainer.length > 0) {
            const overlayHtml = `
                <div id="episodeTransitionOverlay">
                    <div id="episodeTransitionText">Next round will begin shortly...</div>
                    <div id="episodeCountdown"></div>
                </div>
            `;
            gameContainer.prepend(overlayHtml);
            overlay = $('#episodeTransitionOverlay');
            console.log('[UI] Created episode transition overlay dynamically');
        }
    }
    return overlay;
}

/**
 * Show the episode transition overlay with "waiting" message.
 * Call this when waiting for the server to send the next episode state.
 */
export function showEpisodeWaiting(message = "Next round will begin shortly...") {
    const overlay = ensureOverlayExists();
    $('#episodeTransitionText').text(message);
    $('#episodeCountdown').text('');
    overlay.addClass('visible');
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
        console.log(`[UI] showEpisodeCountdown: ${seconds}s, message="${message}"`);
        const overlay = ensureOverlayExists();
        console.log(`[UI] Overlay element found: ${overlay.length > 0}, current classes: "${overlay.attr('class')}"`);

        $('#episodeTransitionText').text(message);
        overlay.addClass('visible');
        console.log(`[UI] Added visible class, now: "${overlay.attr('class')}"`);

        // Check computed style to verify visibility
        const overlayEl = overlay[0];
        if (overlayEl) {
            const computed = window.getComputedStyle(overlayEl);
            console.log(`[UI] Computed display: "${computed.display}", visibility: "${computed.visibility}", opacity: "${computed.opacity}", z-index: "${computed.zIndex}"`);
        }

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
    console.log('[UI] hideEpisodeOverlay called');
    const overlay = $('#episodeTransitionOverlay');
    if (overlay.length > 0) {
        overlay.removeClass('visible');
    }
}
