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
        // List of keys to prevent default behavior for (scroll the window)
        var keysToPreventDefault = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', ' ']; // Includes space (' ')

        if (keysToPreventDefault.includes(event.key)) {
            event.preventDefault(); // Prevent default behavior for specified keys
        }

        // If we're using the single keystroke input method, we just send the key when it's pressed.
        // This means no composite actions.
        if (input_mode == "single_keystroke") {
            pgg.addHumanKeyPressToBuffer(event.key);
            socket.emit('send_pressed_keys', {'pressed_keys': Array(event.key), session_id: window.sessionId});
            return;
        }

        // Otherwise, we keep track of the keys that are pressed and send them on request
        if (pressedKeys[event.key]) {
            return; // Key is already pressed, so exit the function
        }

        pressedKeys[event.key] = true; // Add key to pressedKeys when it is pressed
        pgg.updatePressedKeys(pressedKeys);
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
