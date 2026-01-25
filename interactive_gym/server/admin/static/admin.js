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
    multiplayer_games: [],
    activity_log: [],
    console_logs: [],
    summary: {}
};

// Console log filtering state
let logLevelFilter = 'all';
let logParticipantFilter = 'all';
let consoleLogs = [];

// Session detail state (Phase 34)
let selectedSessionId = null;

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

adminSocket.on('console_log', (log) => {
    addConsoleLog(log);
});

function updateDashboard(state) {
    updateSummaryStats(state.summary);
    updateParticipants(state.participants);
    updateWaitingRooms(state.waiting_rooms);
    updateSessionList(state.multiplayer_games);
    updateActivityTimeline(state.activity_log);
    // Initialize console logs from state on first load
    if (state.console_logs && consoleLogs.length === 0) {
        consoleLogs = [...state.console_logs];
        renderConsoleLogs();
    }
    updateParticipantFilter(state.participants);

    // Update session detail panel if open (Phase 34)
    if (selectedSessionId) {
        const session = state.multiplayer_games?.find(g => g.game_id === selectedSessionId);
        if (session) {
            const content = document.getElementById('session-detail-content');
            if (content) {
                content.innerHTML = renderSessionDetailContent(session);
            }
        }
    }
}

// ============================================
// Summary stats (new element IDs)
// ============================================

function updateSummaryStats(summary) {
    const elConnected = document.getElementById('stat-connected');
    const elWaiting = document.getElementById('stat-waiting');
    const elGames = document.getElementById('stat-games');
    const elCompleted = document.getElementById('stat-completed');
    const elCompletion = document.getElementById('stat-completion');
    const elAvgDuration = document.getElementById('stat-avg-duration');
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
    if (elCompletion) {
        const completed = summary.completed_count || 0;
        const total = summary.total_started || 0;
        const rate = summary.completion_rate || 0;
        elCompletion.textContent = `${completed} of ${total} (${rate}%)`;
    }
    if (elAvgDuration) {
        if (summary.avg_session_duration_ms != null) {
            elAvgDuration.textContent = formatDurationLong(summary.avg_session_duration_ms);
        } else {
            elAvgDuration.textContent = '--';
        }
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
// Session list with P2P health (Phase 33)
// ============================================

function updateSessionList(games) {
    const container = document.getElementById('multiplayer-games-container');
    const countBadge = document.getElementById('games-count');
    if (!container) return;

    if (countBadge) {
        countBadge.textContent = `${games?.length || 0} active`;
    }

    if (!games || games.length === 0) {
        container.innerHTML = `
            <div class="empty-state-sm">
                <p class="text-base-content/50 text-sm">No active sessions</p>
            </div>
        `;
        return;
    }

    // Sort: problem sessions first (reconnecting > degraded > healthy)
    const sorted = [...games].sort((a, b) => {
        const priority = { 'reconnecting': 0, 'degraded': 1, 'healthy': 2 };
        const aStatus = a.session_health || 'healthy';
        const bStatus = b.session_health || 'healthy';
        return (priority[aStatus] || 2) - (priority[bStatus] || 2);
    });

    container.innerHTML = sorted.map(game => renderSessionCard(game)).join('');
}

function renderSessionCard(game) {
    const health = game.session_health || 'healthy';
    const hasProblem = health !== 'healthy';
    const p2pHealth = game.p2p_health || {};

    // Get connection type (use first player's data, both should match)
    const firstPlayerHealth = Object.values(p2pHealth)[0] || {};
    const connectionType = firstPlayerHealth.connection_type || 'unknown';
    const connectionTypeLabel = getConnectionTypeLabel(connectionType);

    // Get latency (average of both players if available)
    const latencies = Object.values(p2pHealth).map(h => h.latency_ms).filter(l => l != null);
    const avgLatency = latencies.length > 0 ? Math.round(latencies.reduce((a,b) => a+b, 0) / latencies.length) : null;

    // Get episode
    const episode = game.current_episode ?? '--';

    return `
        <div class="session-card ${hasProblem ? 'session-problem' : ''}" onclick="showSessionDetail('${escapeHtml(game.game_id)}')" role="button" tabindex="0">
            <div class="session-card-header">
                <div class="session-card-title">
                    <span class="health-indicator health-${health}"></span>
                    <span class="session-id" title="${escapeHtml(game.game_id)}">
                        Session ${truncateId(game.game_id)}
                    </span>
                </div>
                <span class="badge badge-xs ${game.is_server_authoritative ? 'badge-warning' : 'badge-success'}">
                    ${game.is_server_authoritative ? 'Server Auth' : 'P2P'}
                </span>
            </div>
            <div class="session-card-metrics">
                <div class="session-metric">
                    <span class="session-metric-label">Episode</span>
                    <span class="session-metric-value">${episode}</span>
                </div>
                <div class="session-metric">
                    <span class="session-metric-label">Connection</span>
                    <span class="session-metric-value">${connectionTypeLabel}</span>
                </div>
                <div class="session-metric">
                    <span class="session-metric-label">Latency</span>
                    <span class="session-metric-value ${avgLatency && avgLatency > 150 ? 'text-warning' : ''}">
                        ${avgLatency != null ? avgLatency + 'ms' : '--'}
                    </span>
                </div>
                <div class="session-metric">
                    <span class="session-metric-label">Status</span>
                    <span class="session-metric-value session-status-${health}">
                        ${health.charAt(0).toUpperCase() + health.slice(1)}
                    </span>
                </div>
            </div>
            <div class="session-card-players">
                ${game.players.map(player => `
                    <span class="session-player ${player === game.host_id ? 'host' : ''}">
                        ${escapeHtml(truncateId(String(player)))}
                        ${player === game.host_id ? '<span class="host-badge">Host</span>' : ''}
                    </span>
                `).join('')}
            </div>
        </div>
    `;
}

function getConnectionTypeLabel(type) {
    if (!type || type === 'unknown') return 'Unknown';
    if (type === 'relay') return 'TURN Relay';
    if (type === 'direct') return 'P2P Direct';
    if (type === 'socketio_fallback') return 'SocketIO';
    return type;
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
// Console logs
// ============================================

function addConsoleLog(log) {
    consoleLogs.unshift(log);
    // Keep only last 500
    if (consoleLogs.length > 500) {
        consoleLogs = consoleLogs.slice(0, 500);
    }
    renderConsoleLogs();
}

function renderConsoleLogs() {
    const container = document.getElementById('console-logs-container');
    const countBadge = document.getElementById('logs-count');
    if (!container) return;

    // Apply filters
    let filtered = consoleLogs;
    if (logLevelFilter !== 'all') {
        filtered = filtered.filter(l => l.level === logLevelFilter);
    }
    if (logParticipantFilter !== 'all') {
        filtered = filtered.filter(l => l.subject_id === logParticipantFilter);
    }

    if (countBadge) {
        countBadge.textContent = `${filtered.length}`;
    }

    if (!filtered || filtered.length === 0) {
        container.innerHTML = `
            <div class="empty-state-sm">
                <p class="text-base-content/50 text-sm">No logs captured</p>
            </div>
        `;
        return;
    }

    container.innerHTML = filtered.slice(0, 100).map(log => `
        <div class="log-entry log-${log.level}">
            <span class="log-time">${formatTime(log.timestamp)}</span>
            <span class="log-level log-level-${log.level}">${log.level.toUpperCase()}</span>
            <span class="log-subject">${escapeHtml(truncateId(log.subject_id))}</span>
            <span class="log-message">${escapeHtml(log.message)}</span>
        </div>
    `).join('');
}

function updateParticipantFilter(participants) {
    const select = document.getElementById('log-participant-filter');
    if (!select) return;

    // Get current selection
    const currentValue = select.value;

    // Build unique participant list
    const participantIds = [...new Set(consoleLogs.map(l => l.subject_id))];

    // Rebuild options
    select.innerHTML = '<option value="all">All Participants</option>';
    participantIds.forEach(id => {
        const option = document.createElement('option');
        option.value = id;
        option.textContent = truncateId(id);
        select.appendChild(option);
    });

    // Restore selection if still valid
    if (participantIds.includes(currentValue) || currentValue === 'all') {
        select.value = currentValue;
    }
}

// Set up filter event listeners
document.addEventListener('DOMContentLoaded', () => {
    const levelFilter = document.getElementById('log-level-filter');
    const participantFilter = document.getElementById('log-participant-filter');

    if (levelFilter) {
        levelFilter.addEventListener('change', (e) => {
            logLevelFilter = e.target.value;
            renderConsoleLogs();
        });
    }

    if (participantFilter) {
        participantFilter.addEventListener('change', (e) => {
            logParticipantFilter = e.target.value;
            renderConsoleLogs();
        });
    }
});

// ============================================
// Session Detail Panel (Phase 34)
// ============================================

function showSessionDetail(gameId) {
    selectedSessionId = gameId;
    const overlay = document.getElementById('session-detail-overlay');
    const content = document.getElementById('session-detail-content');

    if (!overlay || !content) return;

    // Find session in current state
    const session = currentState.multiplayer_games?.find(g => g.game_id === gameId);

    if (!session) {
        content.innerHTML = '<div class="empty-state-sm"><p>Session not found</p></div>';
        overlay.classList.remove('hidden');
        return;
    }

    // Render session detail
    content.innerHTML = renderSessionDetailContent(session);
    overlay.classList.remove('hidden');
}

function closeSessionDetail() {
    selectedSessionId = null;
    const overlay = document.getElementById('session-detail-overlay');
    if (overlay) {
        overlay.classList.add('hidden');
    }
}

function renderSessionDetailContent(session) {
    const health = session.session_health || 'healthy';
    const p2pHealth = session.p2p_health || {};
    const termination = session.termination;

    // Get connection info from first player
    const firstPlayerHealth = Object.values(p2pHealth)[0] || {};
    const connectionType = getConnectionTypeLabel(firstPlayerHealth.connection_type || 'unknown');

    // Calculate latency
    const latencies = Object.values(p2pHealth).map(h => h.latency_ms).filter(l => l != null);
    const avgLatency = latencies.length > 0
        ? Math.round(latencies.reduce((a,b) => a+b, 0) / latencies.length)
        : null;

    // Get console errors for this session's players
    const playerIds = session.players || [];
    const playerErrors = consoleLogs.filter(log =>
        playerIds.includes(log.subject_id) &&
        (log.level === 'error' || log.level === 'warn')
    ).slice(0, 20);

    return `
        <div class="session-detail-section">
            <h4 class="session-detail-section-title">Session Info</h4>
            <div class="session-detail-grid">
                <div class="session-detail-item">
                    <span class="session-detail-label">Game ID</span>
                    <span class="session-detail-value font-mono text-sm">${escapeHtml(session.game_id)}</span>
                </div>
                <div class="session-detail-item">
                    <span class="session-detail-label">Status</span>
                    <span class="session-detail-value session-status-${health}">
                        <span class="health-indicator health-${health}"></span>
                        ${health.charAt(0).toUpperCase() + health.slice(1)}
                    </span>
                </div>
                <div class="session-detail-item">
                    <span class="session-detail-label">Connection</span>
                    <span class="session-detail-value">${connectionType}</span>
                </div>
                <div class="session-detail-item">
                    <span class="session-detail-label">Latency</span>
                    <span class="session-detail-value ${avgLatency && avgLatency > 150 ? 'text-warning' : ''}">
                        ${avgLatency != null ? avgLatency + 'ms' : '--'}
                    </span>
                </div>
                <div class="session-detail-item">
                    <span class="session-detail-label">Episode</span>
                    <span class="session-detail-value">${session.current_episode ?? '--'}</span>
                </div>
                <div class="session-detail-item">
                    <span class="session-detail-label">Mode</span>
                    <span class="session-detail-value">${session.is_server_authoritative ? 'Server Auth' : 'P2P'}</span>
                </div>
            </div>
        </div>

        <div class="session-detail-section">
            <h4 class="session-detail-section-title">Players</h4>
            <div class="session-detail-players">
                ${playerIds.map(player => `
                    <div class="session-detail-player ${player === session.host_id ? 'host' : ''}">
                        <span class="player-id">${escapeHtml(player)}</span>
                        ${player === session.host_id ? '<span class="host-badge">Host</span>' : ''}
                        ${renderPlayerHealth(p2pHealth[player])}
                    </div>
                `).join('')}
            </div>
        </div>

        ${termination ? `
        <div class="session-detail-section session-termination">
            <h4 class="session-detail-section-title">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                </svg>
                Termination
            </h4>
            <div class="termination-info">
                <div class="termination-reason">${getTerminationReasonLabel(termination.reason)}</div>
                ${termination.details?.message ? `
                    <div class="termination-message">${escapeHtml(termination.details.message)}</div>
                ` : ''}
                <div class="termination-time">Ended: ${formatTime(termination.timestamp)}</div>
            </div>
        </div>
        ` : ''}

        <div class="session-detail-section">
            <h4 class="session-detail-section-title">
                Console Errors & Warnings
                <span class="badge badge-ghost badge-xs">${playerErrors.length}</span>
            </h4>
            ${playerErrors.length > 0 ? `
                <div class="session-detail-logs">
                    ${playerErrors.map(log => `
                        <div class="log-entry log-${log.level}">
                            <span class="log-time">${formatTime(log.timestamp)}</span>
                            <span class="log-level log-level-${log.level}">${log.level.toUpperCase()}</span>
                            <span class="log-subject">${escapeHtml(truncateId(log.subject_id))}</span>
                            <span class="log-message">${escapeHtml(log.message)}</span>
                        </div>
                    `).join('')}
                </div>
            ` : `
                <div class="empty-state-sm">
                    <p class="text-base-content/50 text-sm">No errors or warnings</p>
                </div>
            `}
        </div>
    `;
}

function renderPlayerHealth(health) {
    if (!health) return '<span class="player-health-unknown">No data</span>';

    const status = health.status || 'unknown';
    const latency = health.latency_ms;
    const connType = health.connection_type;

    return `
        <span class="player-health player-health-${status}">
            ${latency != null ? latency + 'ms' : '--'}
            (${getConnectionTypeLabel(connType)})
        </span>
    `;
}

function getTerminationReasonLabel(reason) {
    const labels = {
        'partner_disconnected': 'Partner Disconnected',
        'focus_loss_timeout': 'Focus Loss Timeout',
        'sustained_ping': 'High Latency (Sustained)',
        'tab_hidden': 'Tab Hidden Too Long',
        'exclusion': 'Participant Excluded',
        'custom_callback': 'Custom Exclusion Rule',
        'normal': 'Normal Completion'
    };
    return labels[reason] || reason || 'Unknown';
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

function formatDurationLong(ms) {
    if (ms == null || ms < 0) return '--';
    const totalSeconds = Math.floor(ms / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    if (hours > 0) {
        // Format: "1h 15m"
        return `${hours}h ${minutes}m`;
    } else if (minutes > 0) {
        // Format: "5m 30s"
        return `${minutes}m ${seconds}s`;
    } else {
        // Format: "45s"
        return `${seconds}s`;
    }
}

// Request fresh state periodically (fallback if push fails)
setInterval(() => {
    if (adminSocket.connected) {
        adminSocket.emit('request_state');
    }
}, 5000);
