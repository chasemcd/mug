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
    const statusText = badge.querySelector('.status-text');

    switch(status) {
        case 'connected':
            if (statusText) statusText.textContent = 'Connected';
            badge.classList.add('badge-success');
            break;
        case 'disconnected':
            if (statusText) statusText.textContent = 'Disconnected';
            badge.classList.add('badge-error');
            break;
        case 'error':
            if (statusText) statusText.textContent = 'Error';
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
    updateParticipants(state.participants);
    updateWaitingRooms(state.waiting_rooms);
    updateActivityTimeline(state.activity_log);
}

// ============================================
// Summary stats (new element IDs)
// ============================================

function updateSummaryStats(summary) {
    const elConnected = document.getElementById('stat-connected');
    const elWaiting = document.getElementById('stat-waiting');
    const elGames = document.getElementById('stat-games');
    const elCompleted = document.getElementById('stat-completed');
    const elParticipantCount = document.getElementById('participant-count');
    const elActivityCount = document.getElementById('activity-count');

    if (elConnected) {
        elConnected.textContent = summary.connected_count || 0;
    }
    if (elWaiting) {
        elWaiting.textContent = summary.waiting_count || 0;
    }
    if (elGames) {
        elGames.textContent = summary.active_games || 0;
    }
    if (elCompleted) {
        elCompleted.textContent = summary.completed_count || 0;
    }
    if (elParticipantCount) {
        elParticipantCount.textContent = `${summary.total_participants || 0} total`;
    }
    if (elActivityCount && currentState.activity_log) {
        elActivityCount.textContent = `${currentState.activity_log.length} events`;
    }
}

// ============================================
// Participants (card-based display)
// ============================================

function updateParticipants(participants) {
    const container = document.getElementById('participants-container');
    if (!container) return;

    if (!participants || participants.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-12 h-12 mx-auto mb-2 opacity-30">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" />
                </svg>
                <p class="text-base-content/50">No participants connected</p>
            </div>
        `;
        return;
    }

    // Sort: connected first, then by created_at (newest first)
    const sorted = [...participants].sort((a, b) => {
        // Priority: connected > reconnecting > disconnected > completed
        const statusPriority = { 'connected': 0, 'reconnecting': 1, 'disconnected': 2, 'completed': 3 };
        const priorityA = statusPriority[a.connection_status] ?? 4;
        const priorityB = statusPriority[b.connection_status] ?? 4;
        if (priorityA !== priorityB) return priorityA - priorityB;
        return (b.created_at || 0) - (a.created_at || 0);
    });

    container.innerHTML = `
        <div class="participant-grid">
            ${sorted.map(p => renderParticipantCard(p)).join('')}
        </div>
    `;
}

function renderParticipantCard(p) {
    return `
        <div class="participant-card">
            <div class="participant-card-header">
                <span class="participant-card-id" title="${escapeHtml(p.subject_id)}">${escapeHtml(p.subject_id)}</span>
                ${getStatusBadge(p.connection_status)}
            </div>
            <div class="participant-card-body">
                <div class="participant-card-row">
                    <span class="participant-card-label">Scene</span>
                    <span class="participant-card-value">${escapeHtml(p.current_scene_id || '—')}</span>
                </div>
                <div class="participant-card-row">
                    <span class="participant-card-label">Progress</span>
                    <span class="participant-card-value">${getProgressDisplay(p.scene_progress)}</span>
                </div>
                <div class="participant-card-row">
                    <span class="participant-card-label">Updated</span>
                    <span class="participant-card-value">${formatTimestamp(p.last_updated_at)}</span>
                </div>
            </div>
        </div>
    `;
}

function getStatusBadge(status) {
    const badges = {
        'connected': '<span class="badge badge-success badge-xs">Connected</span>',
        'reconnecting': '<span class="badge badge-warning badge-xs">Reconnecting</span>',
        'disconnected': '<span class="badge badge-error badge-xs">Disconnected</span>',
        'completed': '<span class="badge badge-ghost badge-xs">Completed</span>'
    };
    return badges[status] || '<span class="badge badge-ghost badge-xs">Unknown</span>';
}

function getProgressDisplay(progress) {
    if (!progress || !progress.total_scenes) return '—';
    return `${progress.current_index}/${progress.total_scenes}`;
}

// ============================================
// Waiting rooms
// ============================================

function updateWaitingRooms(waitingRooms) {
    const container = document.getElementById('waiting-rooms-container');
    if (!container) return;

    if (!waitingRooms || waitingRooms.length === 0) {
        container.innerHTML = `
            <div class="empty-state-sm">
                <p class="text-base-content/50 text-sm">No active waiting rooms</p>
            </div>
        `;
        return;
    }

    container.innerHTML = waitingRooms.map(room => `
        <div class="waiting-room-card">
            <div class="waiting-room-header">
                <span class="waiting-room-scene">${escapeHtml(room.scene_id)}</span>
                <span class="waiting-room-count">${room.waiting_count}/${room.target_size}</span>
            </div>
            ${room.groups && room.groups.length > 0 ? `
                <div class="waiting-room-groups">
                    ${room.groups.map(g => `
                        <div class="waiting-room-group">
                            <span>Group ${truncateId(g.group_id)}</span>
                            <span>${g.waiting_count} waiting, ${formatDuration(g.wait_duration_ms)}</span>
                        </div>
                    `).join('')}
                </div>
            ` : ''}
            ${room.avg_wait_duration_ms > 0 ? `
                <div class="text-xs text-base-content/50 mt-1">
                    Avg wait: ${formatDuration(room.avg_wait_duration_ms)}
                </div>
            ` : ''}
        </div>
    `).join('');
}

// ============================================
// Activity timeline
// ============================================

function updateActivityTimeline(events) {
    const container = document.getElementById('activity-timeline');
    const countBadge = document.getElementById('activity-count');
    if (!container) return;

    if (countBadge) {
        countBadge.textContent = `${events?.length || 0} events`;
    }

    if (!events || events.length === 0) {
        container.innerHTML = `
            <div class="empty-state-sm">
                <p class="text-base-content/50 text-sm">No activity yet</p>
            </div>
        `;
        return;
    }

    // Show most recent first (reverse chronological)
    const sorted = [...events].sort((a, b) => b.timestamp - a.timestamp);

    container.innerHTML = sorted.slice(0, 50).map(event => `
        <div class="activity-item">
            <span class="activity-time">${formatTime(event.timestamp)}</span>
            <span class="activity-icon">${getEventIcon(event.event_type)}</span>
            <span class="activity-content">
                <span class="subject-id">${escapeHtml(truncateId(event.subject_id))}</span>
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
        'join': '<span class="event-join">+</span>',
        'disconnect': '<span class="event-disconnect">−</span>',
        'scene_advance': '<span class="event-advance">→</span>',
        'game_start': '<span class="event-game">▶</span>',
        'game_end': '<span class="event-game">■</span>'
    };
    return icons[eventType] || '•';
}

function getEventDescription(event) {
    const descriptions = {
        'join': 'joined',
        'disconnect': 'disconnected',
        'scene_advance': `→ ${escapeHtml(event.details?.scene_id || '?')}`,
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
    if (!id) return '—';
    if (id.length <= 12) return id;
    return id.substring(0, 8) + '…';
}

function formatTimestamp(ts) {
    if (!ts) return '—';
    const date = new Date(ts * 1000);
    return date.toLocaleTimeString();
}

function formatTime(ts) {
    if (!ts) return '—';
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
