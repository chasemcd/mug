/**
 * Admin Dashboard JavaScript
 * Handles SocketIO connection and real-time state updates
 */

// Connect to admin SocketIO namespace
const adminSocket = io('/admin', {
    transports: ['websocket', 'polling']
});

// State tracking
let currentState = {
    participants: [],
    waiting_rooms: [],
    activity_log: [],
    summary: {}
};

// ============================================
// Connection status handlers
// ============================================

adminSocket.on('connect', () => {
    console.log('Admin connected to /admin namespace');
    updateConnectionBadge('connected');
    // Request initial state
    adminSocket.emit('request_state');
});

adminSocket.on('disconnect', () => {
    console.log('Admin disconnected');
    updateConnectionBadge('disconnected');
});

adminSocket.on('connect_error', (error) => {
    console.error('Connection error:', error);
    updateConnectionBadge('error');
});

function updateConnectionBadge(status) {
    const badge = document.getElementById('connection-status');
    if (!badge) return;

    badge.classList.remove('badge-success', 'badge-warning', 'badge-error');

    switch(status) {
        case 'connected':
            badge.textContent = 'Connected';
            badge.classList.add('badge-success');
            break;
        case 'disconnected':
            badge.textContent = 'Disconnected';
            badge.classList.add('badge-error');
            break;
        case 'error':
            badge.textContent = 'Error';
            badge.classList.add('badge-error');
            break;
    }
}

// ============================================
// State update handlers
// ============================================

adminSocket.on('state_update', (data) => {
    console.log('State update received:', data);
    currentState = data;
    updateDashboard(data);
});

adminSocket.on('activity_event', (event) => {
    console.log('Activity event:', event);
    addActivityEvent(event);
});

function updateDashboard(state) {
    updateSummaryStats(state.summary);
    updateParticipantsTable(state.participants);
    updateWaitingRooms(state.waiting_rooms);
    updateActivityTimeline(state.activity_log);
}

// ============================================
// Summary stats
// ============================================

function updateSummaryStats(summary) {
    const elParticipants = document.getElementById('stat-participants');
    const elGames = document.getElementById('stat-games');
    const elWaiting = document.getElementById('stat-waiting');

    if (elParticipants) {
        elParticipants.textContent = summary.total_participants || 0;
    }
    if (elGames) {
        elGames.textContent = summary.active_games || 0;
    }
    if (elWaiting) {
        elWaiting.textContent = summary.waiting_count || 0;
    }
}

// ============================================
// Participants table
// ============================================

function updateParticipantsTable(participants) {
    const tbody = document.getElementById('participants-tbody');
    if (!tbody) return;

    if (!participants || participants.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-base-content/50">
                    No participants connected
                </td>
            </tr>
        `;
        return;
    }

    // Sort by created_at (newest first)
    const sorted = [...participants].sort((a, b) =>
        (b.created_at || 0) - (a.created_at || 0)
    );

    tbody.innerHTML = sorted.map(p => `
        <tr class="hover">
            <td class="font-mono text-sm">${escapeHtml(truncateId(p.subject_id))}</td>
            <td>${getStatusBadge(p.connection_status)}</td>
            <td>${escapeHtml(p.current_scene_id || '-')}</td>
            <td>${getProgressBadge(p.scene_progress)}</td>
            <td class="text-xs text-base-content/60">
                ${formatTimestamp(p.last_updated_at)}
            </td>
        </tr>
    `).join('');
}

function getStatusBadge(status) {
    const badges = {
        'connected': '<span class="badge badge-success badge-sm">Connected</span>',
        'reconnecting': '<span class="badge badge-warning badge-sm">Reconnecting</span>',
        'disconnected': '<span class="badge badge-error badge-sm">Disconnected</span>',
        'completed': '<span class="badge badge-ghost badge-sm">Completed</span>'
    };
    return badges[status] || '<span class="badge badge-ghost badge-sm">Unknown</span>';
}

function getProgressBadge(progress) {
    if (!progress) return '-';
    const pct = Math.round((progress.current_index / progress.total_scenes) * 100);
    return `<progress class="progress progress-primary w-16" value="${progress.current_index}" max="${progress.total_scenes}"></progress>
            <span class="text-xs ml-2">${progress.current_index}/${progress.total_scenes}</span>`;
}

// ============================================
// Waiting rooms
// ============================================

function updateWaitingRooms(waitingRooms) {
    const container = document.getElementById('waiting-rooms-container');
    if (!container) return;

    if (!waitingRooms || waitingRooms.length === 0) {
        container.innerHTML = `
            <div class="text-center text-base-content/50 py-4">
                No active waiting rooms
            </div>
        `;
        return;
    }

    container.innerHTML = waitingRooms.map(room => `
        <div class="card bg-base-100 shadow-sm border border-base-300 mb-2">
            <div class="card-body p-3">
                <div class="flex justify-between items-center">
                    <span class="font-medium text-sm">${escapeHtml(room.scene_id)}</span>
                    <span class="badge badge-outline badge-sm">
                        ${room.waiting_count}/${room.target_size} waiting
                    </span>
                </div>
                ${room.groups && room.groups.length > 0 ? `
                    <div class="mt-2 text-xs text-base-content/60">
                        ${room.groups.map(g => `
                            <div class="flex justify-between">
                                <span>Group ${truncateId(g.group_id)}</span>
                                <span>${g.waiting_count} waiting, ${formatDuration(g.wait_duration_ms)}</span>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
                ${room.avg_wait_duration_ms > 0 ? `
                    <div class="text-xs text-base-content/60 mt-1">
                        Avg wait: ${formatDuration(room.avg_wait_duration_ms)}
                    </div>
                ` : ''}
            </div>
        </div>
    `).join('');
}

// ============================================
// Activity timeline
// ============================================

function updateActivityTimeline(events) {
    const container = document.getElementById('activity-timeline');
    if (!container) return;

    if (!events || events.length === 0) {
        container.innerHTML = `
            <div class="text-center text-base-content/50 py-4">
                No activity yet
            </div>
        `;
        return;
    }

    // Show most recent first (reverse chronological)
    const sorted = [...events].sort((a, b) => b.timestamp - a.timestamp);

    container.innerHTML = sorted.slice(0, 50).map(event => `
        <div class="flex items-start gap-2 py-1 border-b border-base-200 last:border-0">
            <span class="text-xs text-base-content/50 min-w-[60px]">
                ${formatTime(event.timestamp)}
            </span>
            ${getEventIcon(event.event_type)}
            <span class="text-sm flex-1">
                <span class="font-mono text-xs">${escapeHtml(truncateId(event.subject_id))}</span>
                ${getEventDescription(event)}
            </span>
        </div>
    `).join('');
}

function addActivityEvent(event) {
    // Add to current state (for persistence across reconnects)
    if (!currentState.activity_log) {
        currentState.activity_log = [];
    }
    currentState.activity_log.unshift(event);

    // Keep only last 100
    if (currentState.activity_log.length > 100) {
        currentState.activity_log = currentState.activity_log.slice(0, 100);
    }

    // Re-render timeline
    updateActivityTimeline(currentState.activity_log);
}

function getEventIcon(eventType) {
    const icons = {
        'join': '<span class="text-success">+</span>',
        'disconnect': '<span class="text-error">-</span>',
        'scene_advance': '<span class="text-info">></span>',
        'game_start': '<span class="text-primary">*</span>',
        'game_end': '<span class="text-warning">*</span>'
    };
    return `<span class="w-4 text-center">${icons[eventType] || '.'}</span>`;
}

function getEventDescription(event) {
    const descriptions = {
        'join': 'joined',
        'disconnect': 'disconnected',
        'scene_advance': `advanced to <span class="font-mono text-xs">${escapeHtml(event.details?.scene_id || '?')}</span>`,
        'game_start': 'started game',
        'game_end': 'ended game'
    };
    return descriptions[event.event_type] || event.event_type;
}

// ============================================
// Utility functions
// ============================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function truncateId(id) {
    if (!id) return '-';
    if (id.length <= 12) return id;
    return id.substring(0, 8) + '...';
}

function formatTimestamp(ts) {
    if (!ts) return '-';
    const date = new Date(ts * 1000);
    return date.toLocaleTimeString();
}

function formatTime(ts) {
    if (!ts) return '-';
    const date = new Date(ts * 1000);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDuration(ms) {
    if (!ms || ms < 0) return '0s';
    const seconds = Math.floor(ms / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}m ${remainingSeconds}s`;
}

// Request fresh state periodically (fallback if push fails)
setInterval(() => {
    if (adminSocket.connected) {
        adminSocket.emit('request_state');
    }
}, 5000);
