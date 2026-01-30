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
    completed_games: [],  // Session history
    activity_log: [],
    console_logs: [],
    summary: {}
};

// Session tab state
let activeSessionTab = 'active';  // 'active' or 'history'

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
    updateSessionHistory(state.completed_games);
    updateActivityTimeline(state.activity_log);
    // Initialize console logs from state on first load
    if (state.console_logs && consoleLogs.length === 0) {
        consoleLogs = [...state.console_logs];
        renderConsoleLogs();
    }
    updateParticipantFilter(state.participants);
    updateProblemsIndicator();

    // Update session detail panel if open (Phase 34)
    if (selectedSessionId) {
        const session = state.multiplayer_games?.find(g => g.game_id === selectedSessionId);
        if (session) {
            const content = document.getElementById('session-detail-content');
            if (content) {
                // Preserve scroll positions before re-rendering
                const contentScrollTop = content.scrollTop;
                const logsContainer = content.querySelector('.session-detail-logs');
                const logsScrollTop = logsContainer ? logsContainer.scrollTop : 0;

                content.innerHTML = renderSessionDetailContent(session);

                // Restore scroll positions
                content.scrollTop = contentScrollTop;
                const newLogsContainer = content.querySelector('.session-detail-logs');
                if (newLogsContainer) {
                    newLogsContainer.scrollTop = logsScrollTop;
                }
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
            <div class="empty-state-sm">
                <p class="text-base-content/50 text-sm">No participants connected</p>
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

    // Grid view of participant cards (clickable)
    container.innerHTML = `
        <div class="participant-card-grid">
            ${sorted.map(p => renderParticipantCard(p)).join('')}
        </div>
    `;
}

function renderParticipantCard(p) {
    const hasErrors = p.error_count > 0;
    const statusIndicator = getConnectionStatusIndicator(p.connection_status);

    return `
        <div class="participant-card ${hasErrors ? 'participant-has-errors' : ''}"
             onclick="showParticipantDetail('${escapeHtml(p.subject_id)}')"
             role="button" tabindex="0">
            <div class="participant-card-header">
                <div class="participant-card-title">
                    <span class="health-indicator ${statusIndicator}"></span>
                    <span class="participant-card-id" title="${escapeHtml(p.subject_id)}">${escapeHtml(truncateId(p.subject_id))}</span>
                </div>
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
                ${p.current_game_id ? `
                <div class="participant-card-row">
                    <span class="participant-card-label">Game</span>
                    <span class="participant-card-value font-mono text-xs">${escapeHtml(truncateId(p.current_game_id))}</span>
                </div>
                ` : ''}
                <div class="participant-card-row">
                    <span class="participant-card-label">Logs</span>
                    <span class="participant-card-value">
                        ${p.log_count || 0}
                        ${hasErrors ? `<span class="badge badge-error badge-xs ml-1">${p.error_count} errors</span>` : ''}
                    </span>
                </div>
            </div>
        </div>
    `;
}

function getConnectionStatusIndicator(status) {
    const indicators = {
        'connected': 'health-healthy',
        'reconnecting': 'health-reconnecting',
        'disconnected': 'health-disconnected',
        'completed': 'health-completed'
    };
    return indicators[status] || 'health-completed';
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
                <p class="text-base-content/50 text-sm">No active multiplayer sessions</p>
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

    // Wrap in grid container for responsive layout
    container.innerHTML = `<div class="session-card-grid">${sorted.map(game => renderSessionCard(game)).join('')}</div>`;
}

function renderSessionCard(game) {
    const health = game.session_health || 'healthy';
    const hasProblem = health !== 'healthy';
    const p2pHealth = game.p2p_health || {};
    const isMultiplayer = game.game_type === 'multiplayer';
    const isSinglePlayer = game.game_type === 'single_player';

    // Get connection type (use first player's data for multiplayer)
    const firstPlayerHealth = Object.values(p2pHealth)[0] || {};
    const connectionType = isMultiplayer ? (firstPlayerHealth.connection_type || 'unknown') : null;
    const connectionTypeLabel = isMultiplayer ? getConnectionTypeLabel(connectionType) : 'Local';

    // Get latency (average of both players if available, only for multiplayer)
    const latencies = Object.values(p2pHealth).map(h => h.latency_ms).filter(l => l != null);
    const avgLatency = latencies.length > 0 ? Math.round(latencies.reduce((a,b) => a+b, 0) / latencies.length) : null;

    // Get episode (1-indexed for display)
    const episodeNum = game.current_episode;
    const episode = episodeNum != null ? episodeNum + 1 : '--';

    // Get participant IDs for display
    const subjectIds = game.subject_ids || [];

    // Badge for game type
    const typeBadge = isSinglePlayer
        ? '<span class="badge badge-xs badge-info">Solo</span>'
        : `<span class="badge badge-xs ${game.is_server_authoritative ? 'badge-warning' : 'badge-success'}">${game.is_server_authoritative ? 'Server Auth' : 'P2P'}</span>`;

    return `
        <div class="session-card ${hasProblem ? 'session-problem' : ''}" onclick="showSessionDetail('${escapeHtml(game.game_id)}')" role="button" tabindex="0">
            <div class="session-card-header">
                <div class="session-card-title">
                    <span class="health-indicator health-${health}"></span>
                    <span class="session-id" title="${escapeHtml(game.game_id)}">
                        ${isSinglePlayer ? 'Game' : 'Session'} ${truncateId(game.game_id)}
                    </span>
                </div>
                ${typeBadge}
            </div>
            <div class="session-card-metrics">
                <div class="session-metric">
                    <span class="session-metric-label">Episode</span>
                    <span class="session-metric-value">${episode}</span>
                </div>
                ${isMultiplayer ? `
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
                ` : `
                <div class="session-metric">
                    <span class="session-metric-label">Scene</span>
                    <span class="session-metric-value">${escapeHtml(truncateId(game.scene_id || 'unknown'))}</span>
                </div>
                `}
                <div class="session-metric">
                    <span class="session-metric-label">Status</span>
                    <span class="session-metric-value session-status-${health}">
                        ${health.charAt(0).toUpperCase() + health.slice(1)}
                    </span>
                </div>
            </div>
            <div class="session-card-players">
                ${subjectIds.length > 0
                    ? subjectIds.map(subject => `
                        <span class="session-player">
                            ${escapeHtml(truncateId(String(subject)))}
                        </span>
                    `).join('')
                    : game.players.map(player => `
                        <span class="session-player">
                            ${escapeHtml(truncateId(String(player)))}
                        </span>
                    `).join('')
                }
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
// Participant Detail Panel (Phase 35 rework)
// ============================================

let selectedParticipantId = null;

function showParticipantDetail(subjectId) {
    selectedParticipantId = subjectId;
    const overlay = document.getElementById('participant-detail-overlay');
    const content = document.getElementById('participant-detail-content');

    if (!overlay || !content) return;

    // Find participant in current state
    const participant = currentState.participants?.find(p => p.subject_id === subjectId);

    if (!participant) {
        content.innerHTML = '<div class="empty-state-sm"><p>Participant not found</p></div>';
        overlay.classList.remove('hidden');
        return;
    }

    // Render participant detail
    content.innerHTML = renderParticipantDetailContent(participant);
    overlay.classList.remove('hidden');
}

function closeParticipantDetail() {
    selectedParticipantId = null;
    const overlay = document.getElementById('participant-detail-overlay');
    if (overlay) {
        overlay.classList.add('hidden');
    }
}

function renderParticipantDetailContent(participant) {
    const statusIndicator = getConnectionStatusIndicator(participant.connection_status);
    const gameHistory = participant.game_history || [];

    // Get all logs for this participant from current state
    const participantLogs = consoleLogs.filter(log =>
        log.subject_id === participant.subject_id
    );

    // Calculate session duration
    let sessionDuration = '--';
    if (participant.created_at) {
        const durationMs = (Date.now() / 1000 - participant.created_at) * 1000;
        sessionDuration = formatDurationLong(durationMs);
    }

    return `
        <div class="session-detail-section">
            <h4 class="session-detail-section-title">Participant Info</h4>
            <div class="session-detail-grid">
                <div class="session-detail-item">
                    <span class="session-detail-label">Subject ID</span>
                    <span class="session-detail-value font-mono text-sm">${escapeHtml(participant.subject_id)}</span>
                </div>
                <div class="session-detail-item">
                    <span class="session-detail-label">Status</span>
                    <span class="session-detail-value">
                        <span class="health-indicator ${statusIndicator}"></span>
                        ${participant.connection_status.charAt(0).toUpperCase() + participant.connection_status.slice(1)}
                    </span>
                </div>
                <div class="session-detail-item">
                    <span class="session-detail-label">Current Scene</span>
                    <span class="session-detail-value">${escapeHtml(participant.current_scene_id || '—')}</span>
                </div>
                <div class="session-detail-item">
                    <span class="session-detail-label">Progress</span>
                    <span class="session-detail-value">${getProgressDisplay(participant.scene_progress)}</span>
                </div>
                <div class="session-detail-item">
                    <span class="session-detail-label">Session Duration</span>
                    <span class="session-detail-value">${sessionDuration}</span>
                </div>
                <div class="session-detail-item">
                    <span class="session-detail-label">Last Updated</span>
                    <span class="session-detail-value">${formatTime(participant.last_updated_at)}</span>
                </div>
                ${participant.current_game_id ? `
                <div class="session-detail-item">
                    <span class="session-detail-label">Current Game</span>
                    <span class="session-detail-value font-mono text-sm cursor-pointer text-primary"
                          onclick="showSessionDetail('${escapeHtml(participant.current_game_id)}'); closeParticipantDetail();">
                        ${escapeHtml(truncateId(participant.current_game_id))}
                    </span>
                </div>
                ` : ''}
            </div>
        </div>

        ${gameHistory.length > 0 ? `
        <div class="session-detail-section">
            <h4 class="session-detail-section-title">Game History (${gameHistory.length})</h4>
            <div class="game-history-list">
                ${gameHistory.map(game => `
                    <div class="game-history-item">
                        <div class="game-history-header">
                            <span class="font-mono text-xs">${escapeHtml(truncateId(game.game_id))}</span>
                            <span class="badge badge-xs ${game.ended_at ? (game.termination_reason === 'normal' ? 'badge-success' : 'badge-warning') : 'badge-primary'}">
                                ${game.ended_at ? (game.termination_reason || 'ended') : 'active'}
                            </span>
                        </div>
                        <div class="game-history-details">
                            <span>Role: ${game.role || 'player'}</span>
                            ${game.ended_at ? `<span>Duration: ${formatDuration((game.ended_at - game.started_at) * 1000)}</span>` : ''}
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
        ` : ''}

        <div class="session-detail-section">
            <h4 class="session-detail-section-title">Console Logs (${participantLogs.length})</h4>
            <div class="session-detail-logs">
                ${participantLogs.length > 0 ? participantLogs.slice(-50).map(log => `
                    <div class="log-entry log-${log.level || 'log'}">
                        <span class="log-time">${formatTime(log.timestamp)}</span>
                        <span class="log-level log-level-${log.level || 'log'}">${(log.level || 'LOG').toUpperCase()}</span>
                        <span class="log-message">${escapeHtml(log.message || '')}</span>
                    </div>
                `).join('') : '<div class="empty-state-sm"><p class="text-base-content/50">No logs captured</p></div>'}
            </div>
        </div>
    `;
}

// ============================================
// Session History (Phase 35)
// ============================================

function switchSessionTab(tab) {
    activeSessionTab = tab;
    const activeContainer = document.getElementById('multiplayer-games-container');
    const historyContainer = document.getElementById('session-history-container');
    const activeTab = document.getElementById('tab-active-sessions');
    const historyTab = document.getElementById('tab-session-history');
    const countBadge = document.getElementById('games-count');

    if (tab === 'active') {
        activeContainer?.classList.remove('hidden');
        historyContainer?.classList.add('hidden');
        activeTab?.classList.add('tab-active');
        historyTab?.classList.remove('tab-active');
        if (countBadge) {
            countBadge.textContent = `${currentState.multiplayer_games?.length || 0} active`;
        }
    } else {
        activeContainer?.classList.add('hidden');
        historyContainer?.classList.remove('hidden');
        activeTab?.classList.remove('tab-active');
        historyTab?.classList.add('tab-active');
        if (countBadge) {
            countBadge.textContent = `${currentState.completed_games?.length || 0} completed`;
        }
    }
}

function updateSessionHistory(completedGames) {
    const container = document.getElementById('session-history-container');
    if (!container) return;

    // Store in state
    currentState.completed_games = completedGames || [];

    // Update count badge if on history tab
    if (activeSessionTab === 'history') {
        const countBadge = document.getElementById('games-count');
        if (countBadge) {
            countBadge.textContent = `${completedGames?.length || 0} completed`;
        }
    }

    if (!completedGames || completedGames.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-12 h-12 mx-auto mb-2 opacity-30">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <p class="text-base-content/50">No session history</p>
                <p class="text-base-content/30 text-sm mt-1">Completed sessions will appear here</p>
            </div>
        `;
        return;
    }

    // Render completed sessions (most recent first - already sorted by server)
    container.innerHTML = `<div class="session-card-grid">${completedGames.map(game => renderHistoricalSessionCard(game)).join('')}</div>`;
}

function renderHistoricalSessionCard(game) {
    const termination = game.termination || {};
    const reason = termination.reason || 'unknown';
    const isMultiplayer = game.game_type === 'multiplayer';
    const isSinglePlayer = game.game_type === 'single_player';

    // Get subject IDs for display
    const subjectIds = game.subject_ids || [];

    // Episode display (1-indexed)
    const episodeNum = game.current_episode;
    const episode = episodeNum != null ? episodeNum + 1 : '--';

    // Time completed
    const completedAt = game.completed_at ? formatTime(game.completed_at) : '--';

    // Duration (if we have created_at and completed_at)
    let duration = '--';
    if (game.created_at && game.completed_at) {
        const durationMs = (game.completed_at - game.created_at) * 1000;
        duration = formatDuration(durationMs);
    }

    // Termination badge color based on reason
    const reasonBadgeClass = reason === 'normal' ? 'badge-success' :
                             reason === 'partner_disconnected' ? 'badge-error' :
                             'badge-warning';

    return `
        <div class="session-card session-historical" onclick="showSessionDetail('${escapeHtml(game.game_id)}', true)" role="button" tabindex="0">
            <div class="session-card-header">
                <div class="session-card-title">
                    <span class="health-indicator health-completed"></span>
                    <span class="session-id" title="${escapeHtml(game.game_id)}">
                        ${isSinglePlayer ? 'Game' : 'Session'} ${truncateId(game.game_id)}
                    </span>
                </div>
                <span class="badge badge-xs ${reasonBadgeClass}">${getTerminationReasonLabel(reason)}</span>
            </div>
            <div class="session-card-metrics">
                <div class="session-metric">
                    <span class="session-metric-label">Episode</span>
                    <span class="session-metric-value">${episode}</span>
                </div>
                <div class="session-metric">
                    <span class="session-metric-label">Duration</span>
                    <span class="session-metric-value">${duration}</span>
                </div>
                <div class="session-metric">
                    <span class="session-metric-label">Ended</span>
                    <span class="session-metric-value">${completedAt}</span>
                </div>
            </div>
            <div class="session-card-players">
                ${subjectIds.length > 0
                    ? subjectIds.map(subject => `
                        <span class="session-player">
                            ${escapeHtml(truncateId(String(subject)))}
                        </span>
                    `).join('')
                    : game.players?.map(player => `
                        <span class="session-player">
                            ${escapeHtml(truncateId(String(player)))}
                        </span>
                    `).join('') || ''
                }
            </div>
        </div>
    `;
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
    updateProblemsIndicator();
}

function renderConsoleLogs() {
    const container = document.getElementById('console-logs-container');
    const countBadge = document.getElementById('logs-count');
    if (!container) return;

    // Preserve scroll position
    const scrollTop = container.scrollTop;
    const wasScrolledToBottom = container.scrollHeight - container.scrollTop <= container.clientHeight + 50;

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

    // Restore scroll position (only auto-scroll if user was already at bottom)
    if (wasScrolledToBottom) {
        container.scrollTop = container.scrollHeight;
    } else {
        container.scrollTop = scrollTop;
    }
}

// ============================================
// Problems indicator (Phase 35)
// ============================================

function updateProblemsIndicator() {
    const indicator = document.getElementById('problems-indicator');
    if (!indicator) return;

    // Count errors and warnings
    const problemCount = consoleLogs.filter(l =>
        l.level === 'error' || l.level === 'warn'
    ).length;

    const countEl = indicator.querySelector('.problems-count');
    if (countEl) {
        countEl.textContent = problemCount;
    }

    // Show/hide based on count
    if (problemCount > 0) {
        indicator.classList.remove('hidden');
    } else {
        indicator.classList.add('hidden');
    }
}

function scrollToProblems() {
    const logsSection = document.getElementById('console-logs-container');
    if (logsSection) {
        logsSection.scrollIntoView({ behavior: 'smooth' });
    }
    // Set filter to show only errors and warnings
    const levelFilter = document.getElementById('log-level-filter');
    if (levelFilter) {
        levelFilter.value = 'error';
        logLevelFilter = 'error';
        renderConsoleLogs();
    }
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

function showSessionDetail(gameId, isHistorical = false) {
    selectedSessionId = gameId;
    const overlay = document.getElementById('session-detail-overlay');
    const content = document.getElementById('session-detail-content');

    if (!overlay || !content) return;

    // Find session in current state (check both active and completed)
    let session = currentState.multiplayer_games?.find(g => g.game_id === gameId);
    let sessionIsHistorical = false;

    if (!session) {
        // Check completed games
        session = currentState.completed_games?.find(g => g.game_id === gameId);
        sessionIsHistorical = true;
    }

    if (!session) {
        content.innerHTML = '<div class="empty-state-sm"><p>Session not found</p></div>';
        overlay.classList.remove('hidden');
        return;
    }

    // Render session detail (with historical flag)
    content.innerHTML = renderSessionDetailContent(session, sessionIsHistorical);
    overlay.classList.remove('hidden');
}

function closeSessionDetail() {
    selectedSessionId = null;
    const overlay = document.getElementById('session-detail-overlay');
    if (overlay) {
        overlay.classList.add('hidden');
    }
}

function renderSessionDetailContent(session, isHistorical = false) {
    const health = isHistorical ? 'completed' : (session.session_health || 'healthy');
    const p2pHealth = session.p2p_health || {};
    const termination = session.termination;
    const isMultiplayer = session.game_type === 'multiplayer';
    const isSinglePlayer = session.game_type === 'single_player';

    // Get connection info from first player (multiplayer only)
    const firstPlayerHealth = Object.values(p2pHealth)[0] || {};
    const connectionType = isMultiplayer
        ? getConnectionTypeLabel(firstPlayerHealth.connection_type || 'unknown')
        : 'Local';

    // Calculate latency (multiplayer only)
    const latencies = Object.values(p2pHealth).map(h => h.latency_ms).filter(l => l != null);
    const avgLatency = latencies.length > 0
        ? Math.round(latencies.reduce((a,b) => a+b, 0) / latencies.length)
        : null;

    // Get console logs for this session
    // For historical sessions, use archived_logs if available
    // For active sessions, filter from current logs
    const subjectIds = session.subject_ids || [];
    let playerLogs;
    if (isHistorical && session.archived_logs) {
        playerLogs = session.archived_logs;
    } else {
        playerLogs = consoleLogs.filter(log =>
            subjectIds.includes(log.subject_id)
        ).slice(-30);  // Show last 30 logs
    }

    // Episode display (1-indexed)
    const episodeNum = session.current_episode;
    const episodeDisplay = episodeNum != null ? episodeNum + 1 : '--';

    // Mode display
    const modeDisplay = isSinglePlayer
        ? 'Single Player'
        : (session.is_server_authoritative ? 'Server Auth' : 'P2P');

    // Duration for historical sessions
    let durationDisplay = '--';
    if (isHistorical && session.created_at && session.completed_at) {
        const durationMs = (session.completed_at - session.created_at) * 1000;
        durationDisplay = formatDurationLong(durationMs);
    }

    return `
        <div class="session-detail-section">
            <h4 class="session-detail-section-title">${isSinglePlayer ? 'Game' : 'Session'} Info</h4>
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
                ${isMultiplayer ? `
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
                ` : `
                <div class="session-detail-item">
                    <span class="session-detail-label">Scene</span>
                    <span class="session-detail-value">${escapeHtml(session.scene_id || 'unknown')}</span>
                </div>
                `}
                <div class="session-detail-item">
                    <span class="session-detail-label">Episode</span>
                    <span class="session-detail-value">${episodeDisplay}</span>
                </div>
                <div class="session-detail-item">
                    <span class="session-detail-label">Mode</span>
                    <span class="session-detail-value">${modeDisplay}</span>
                </div>
                ${isHistorical ? `
                <div class="session-detail-item">
                    <span class="session-detail-label">Duration</span>
                    <span class="session-detail-value">${durationDisplay}</span>
                </div>
                <div class="session-detail-item">
                    <span class="session-detail-label">Ended</span>
                    <span class="session-detail-value">${session.completed_at ? formatTime(session.completed_at) : '--'}</span>
                </div>
                ` : ''}
            </div>
        </div>

        <div class="session-detail-section">
            <h4 class="session-detail-section-title">${isSinglePlayer ? 'Participant' : 'Players'}</h4>
            <div class="session-detail-players">
                ${subjectIds.map((subject, idx) => `
                    <div class="session-detail-player">
                        <span class="player-id">${escapeHtml(subject)}</span>
                        ${isMultiplayer ? renderPlayerHealth(p2pHealth[session.players[idx]]) : ''}
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
                Console Logs
                <span class="badge badge-ghost badge-xs">${playerLogs.length}</span>
            </h4>
            ${playerLogs.length > 0 ? `
                <div class="session-detail-logs">
                    ${playerLogs.map(log => `
                        <div class="log-entry log-${log.level}">
                            <span class="log-time">${formatTime(log.timestamp)}</span>
                            <span class="log-level log-level-${log.level}">${log.level.toUpperCase()}</span>
                            <span class="log-message">${escapeHtml(log.message)}</span>
                        </div>
                    `).join('')}
                </div>
            ` : `
                <div class="empty-state-sm">
                    <p class="text-base-content/50 text-sm">No logs for this session</p>
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
