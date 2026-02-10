/**
 * Admin Dashboard JavaScript - v3
 * Participant-centric dashboard with multiplayer session grouping
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
    completed_games: [],
    activity_log: [],
    console_logs: [],
    problems: [],
    summary: {},
    aggregates: {}
};

// Console log filtering state
let logLevelFilter = 'all';
let logParticipantFilter = 'all';
let consoleLogs = [];

// Participant filter state
let showInactiveParticipants = false;

// Detail panel state
let selectedParticipantId = null;
let selectedSessionId = null;

// ============================================
// Connection status handlers
// ============================================

adminSocket.on('connect', () => {
    console.log('Admin connected to /admin namespace');
    updateConnectionBadge('connected');
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
    currentState = data;
    updateDashboard(data);
});

adminSocket.on('console_log', (log) => {
    addConsoleLog(log);
});

function updateDashboard(state) {
    updateSummaryStats(state.summary);
    updateActiveParticipantsTable(state.participants, state.multiplayer_games);
    updateMultiplayerSessions(state.multiplayer_games);
    updateProblems(state.problems || []);
    updateSessionOutcomes(state.aggregates);
    updateArchivedSessions(state.completed_games || []);
    updateCompletedParticipants(state.participants);

    // Initialize console logs from state on first load
    if (state.console_logs && consoleLogs.length === 0) {
        consoleLogs = [...state.console_logs];
        renderConsoleLogs();
    }
    updateParticipantFilter(state.participants);
    updateProblemsCount();
}

// ============================================
// Summary stats
// ============================================

function updateSummaryStats(summary) {
    setElementText('stat-active', summary.connected_count || 0);
    setElementText('stat-waiting', summary.waiting_count || 0);
    setElementText('stat-completed', summary.completed_count || 0);

    const total = summary.total_started || 0;
    const completed = summary.completed_count || 0;
    const rate = total > 0 ? Math.round((completed / total) * 100) : 0;
    setElementText('stat-completion', `${rate}%`);

    if (summary.avg_session_duration_ms != null) {
        setElementText('stat-duration', formatDuration(summary.avg_session_duration_ms));
    } else {
        setElementText('stat-duration', '--');
    }
}

function setElementText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

// ============================================
// Active Participants Table
// ============================================

function updateActiveParticipantsTable(participants, games) {
    const container = document.getElementById('active-participants-table');
    const countEl = document.getElementById('active-participants-count');
    if (!container) return;

    // Filter to only non-completed participants
    let active = participants.filter(p => p.connection_status !== 'completed');

    // Count all non-completed for the badge (before filtering inactive)
    const totalNonCompleted = active.length;

    // Further filter to hide disconnected/reconnecting unless toggle is on
    if (!showInactiveParticipants) {
        active = active.filter(p =>
            p.connection_status !== 'disconnected' &&
            p.connection_status !== 'reconnecting'
        );
    }

    // Update count badge - show filtered/total if different
    if (countEl) {
        if (active.length !== totalNonCompleted) {
            countEl.textContent = `${active.length}/${totalNonCompleted}`;
        } else {
            countEl.textContent = active.length;
        }
    }

    if (active.length === 0) {
        const hiddenCount = totalNonCompleted - active.length;
        container.innerHTML = `
            <div class="empty-state">
                <p class="text-base-content/50">No active participants${hiddenCount > 0 ? ` (${hiddenCount} inactive hidden)` : ''}</p>
            </div>
        `;
        return;
    }

    // Build a map of game_id -> game for quick lookup
    const gameMap = {};
    (games || []).forEach(g => {
        gameMap[g.game_id] = g;
    });

    // Sort: in-game first, then waiting, then connected, then inactive at end
    const sorted = [...active].sort((a, b) => {
        const getPriority = (p) => {
            if (p.waitroom_info) return 0;  // Waiting first
            if (p.current_game_id && !p.waitroom_info) return 1;  // In game
            if (p.connection_status === 'connected') return 2;  // Connected but not in game/waitroom
            if (p.connection_status === 'reconnecting') return 3;  // Reconnecting
            return 4;  // Disconnected last
        };
        return getPriority(a) - getPriority(b);
    });

    container.innerHTML = `
        <table class="participant-table">
            <thead>
                <tr>
                    <th>Status</th>
                    <th>Subject ID</th>
                    <th>Scene</th>
                    <th>Type</th>
                    <th>Activity</th>
                    <th>Ping</th>
                    <th>Duration</th>
                    <th>Errors</th>
                </tr>
            </thead>
            <tbody>
                ${sorted.map(p => renderParticipantRow(p, gameMap)).join('')}
            </tbody>
        </table>
    `;
}

function renderParticipantRow(p, gameMap) {
    // Status indicator - IMPORTANT: Check waitroom_info BEFORE current_game_id
    // because participants in waitroom also have a game_id assigned
    let statusColor = '#22c55e'; // connected
    let statusLabel = 'Connected';

    if (p.waitroom_info) {
        // Waitroom takes priority - participant is waiting even if they have a game_id
        statusColor = '#eab308'; // yellow for waiting
        statusLabel = 'Waiting';
    } else if (p.current_game_id) {
        statusColor = '#3b82f6'; // blue for in game
        statusLabel = 'In Game';
    } else if (p.connection_status === 'reconnecting') {
        statusColor = '#f97316'; // orange
        statusLabel = 'Reconnecting';
    } else if (p.connection_status === 'disconnected') {
        statusColor = '#ef4444'; // red
        statusLabel = 'Disconnected';
    }

    // Scene display - always show actual scene name
    const sceneDisplay = p.current_scene_id || '--';

    // Determine game type (single-player vs multiplayer)
    let gameType = '--';
    let gameTypeClass = '';
    if (p.waitroom_info) {
        // In waitroom - check target size to determine game type
        const targetSize = p.waitroom_info.target_size || 1;
        if (targetSize > 1) {
            gameType = 'Multiplayer';
            gameTypeClass = 'type-multiplayer';
        } else {
            gameType = 'Single';
            gameTypeClass = 'type-single';
        }
    } else if (p.current_game_id) {
        const game = gameMap[p.current_game_id];
        if (game) {
            const playerCount = game.subject_ids?.length || 1;
            if (playerCount > 1 || game.game_type === 'multiplayer') {
                gameType = 'Multiplayer';
                gameTypeClass = 'type-multiplayer';
            } else {
                gameType = 'Single';
                gameTypeClass = 'type-single';
            }
        }
    }

    // Activity display
    let activityDisplay = '--';
    if (p.waitroom_info) {
        // In waitroom - show wait progress and time
        const w = p.waitroom_info;
        const waitSecs = Math.floor(w.wait_duration_ms / 1000);
        const waitDisplay = waitSecs < 60 ? `${waitSecs}s` : `${Math.floor(waitSecs / 60)}m ${waitSecs % 60}s`;
        activityDisplay = `${w.waiting_count}/${w.target_size} (${waitDisplay})`;
    } else if (p.current_game_id) {
        const game = gameMap[p.current_game_id];
        const episode = p.current_episode != null ? p.current_episode + 1 : (game?.current_episode != null ? game.current_episode + 1 : '?');
        activityDisplay = `Round ${episode}`;
    }

    // Ping - get from game if available (only when actually in game, not waitroom)
    let pingDisplay = '--';
    if (p.current_game_id && !p.waitroom_info) {
        const game = gameMap[p.current_game_id];
        if (game?.p2p_health) {
            // Find this participant's latency
            for (const [playerId, health] of Object.entries(game.p2p_health)) {
                if (health.latency_ms != null) {
                    pingDisplay = `${health.latency_ms}ms`;
                    break;
                }
            }
        }
    }

    // Duration - use last_updated_at for disconnected/reconnecting, Date.now() for active
    let duration = '--';
    if (p.created_at) {
        const isInactive = p.connection_status === 'disconnected' ||
                          p.connection_status === 'reconnecting' ||
                          p.connection_status === 'completed';
        const endTime = isInactive && p.last_updated_at ? p.last_updated_at : Date.now() / 1000;
        duration = formatDuration((endTime - p.created_at) * 1000);
    }

    // Errors
    const errorBadge = p.error_count > 0
        ? `<span class="error-badge">${p.error_count}</span>`
        : '--';

    return `
        <tr class="participant-row" onclick="showParticipantDetail('${escapeHtml(p.subject_id)}')">
            <td>
                <div class="status-indicator">
                    <span class="status-dot" style="background-color: ${statusColor};"></span>
                    <span class="status-label">${statusLabel}</span>
                </div>
            </td>
            <td class="font-mono">${escapeHtml(truncateId(p.subject_id, 16))}</td>
            <td>${escapeHtml(sceneDisplay)}</td>
            <td><span class="game-type-badge ${gameTypeClass}">${gameType}</span></td>
            <td>${escapeHtml(activityDisplay)}</td>
            <td>${pingDisplay}</td>
            <td>${duration}</td>
            <td>${errorBadge}</td>
        </tr>
    `;
}

// ============================================
// Multiplayer Sessions
// ============================================

function updateMultiplayerSessions(games) {
    const container = document.getElementById('multiplayer-sessions-list');
    const countEl = document.getElementById('sessions-count');
    if (!container) return;

    // Only show multiplayer games (more than 1 player)
    const multiplayer = (games || []).filter(g =>
        g.game_type === 'multiplayer' || (g.subject_ids && g.subject_ids.length > 1)
    );

    if (countEl) countEl.textContent = multiplayer.length;

    if (multiplayer.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <p class="text-base-content/50">No active multiplayer sessions</p>
            </div>
        `;
        return;
    }

    // Sort by health status (problems first)
    const sorted = [...multiplayer].sort((a, b) => {
        const priority = { 'reconnecting': 0, 'degraded': 1, 'healthy': 2 };
        return (priority[a.session_health] ?? 2) - (priority[b.session_health] ?? 2);
    });

    container.innerHTML = sorted.map(g => renderMultiplayerSession(g)).join('');
}

function renderMultiplayerSession(game) {
    const health = game.session_health || 'healthy';
    let healthColor = '#22c55e';
    if (health === 'degraded') healthColor = '#eab308';
    if (health === 'reconnecting') healthColor = '#ef4444';

    // Get P2P RTT between players
    const p2pHealth = game.p2p_health || {};
    const latencies = Object.values(p2pHealth).map(h => h.latency_ms).filter(l => l != null);
    const avgLatency = latencies.length > 0
        ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length)
        : null;

    // Connection type
    const firstPlayer = Object.values(p2pHealth)[0] || {};
    const connType = firstPlayer.connection_type || 'unknown';
    const connLabel = getConnectionLabel(connType);

    // Episode
    const episode = game.current_episode != null ? game.current_episode + 1 : '--';

    // Players
    const players = game.subject_ids || [];

    return `
        <div class="multiplayer-session-card" onclick="showSessionDetail('${escapeHtml(game.game_id)}')">
            <div class="session-header-row">
                <div class="session-health">
                    <span class="health-dot" style="background-color: ${healthColor};"></span>
                    <span class="session-id font-mono">${truncateId(game.game_id, 12)}</span>
                </div>
                <div class="session-metrics-row">
                    <span class="metric-pill">RTT: ${avgLatency != null ? avgLatency + 'ms' : '--'}</span>
                    <span class="metric-pill">${connLabel}</span>
                    <span class="metric-pill">Round ${episode}</span>
                </div>
            </div>
            <div class="session-players-row">
                ${players.map(sid => {
                    const participant = currentState.participants?.find(p => p.subject_id === sid);
                    const errorCount = participant?.error_count || 0;
                    return `
                        <div class="session-player">
                            <span class="player-name font-mono">${escapeHtml(truncateId(sid, 14))}</span>
                            ${errorCount > 0 ? `<span class="error-badge-small">${errorCount}</span>` : ''}
                        </div>
                    `;
                }).join('')}
            </div>
        </div>
    `;
}

function getConnectionLabel(type) {
    return {
        'direct': 'P2P Direct',
        'relay': 'TURN Relay',
        'socketio_fallback': 'Fallback',
        'unknown': '--'
    }[type] || type;
}

// ============================================
// Archived Sessions
// ============================================

function updateArchivedSessions(completedGames) {
    const container = document.getElementById('archived-sessions-list');
    const countEl = document.getElementById('archived-sessions-count');
    if (!container) return;

    if (countEl) countEl.textContent = completedGames.length;

    if (!completedGames || completedGames.length === 0) {
        container.innerHTML = '<p class="text-base-content/50 p-4">No archived sessions</p>';
        return;
    }

    container.innerHTML = `
        <table class="archived-sessions-table">
            <thead>
                <tr>
                    <th>Session ID</th>
                    <th>Players</th>
                    <th>Outcome</th>
                    <th>Duration</th>
                    <th>Ended</th>
                </tr>
            </thead>
            <tbody>
                ${completedGames.slice(0, 50).map(g => {
                    const termination = g.termination || {};
                    const players = g.subject_ids || termination.players || [];
                    const reason = getTerminationLabel(termination.reason);
                    const endTime = termination.timestamp ? formatTime(termination.timestamp) : '--';

                    // Calculate duration if we have start time
                    let duration = '--';
                    if (g.created_at && g.completed_at) {
                        duration = formatDuration((g.completed_at - g.created_at) * 1000);
                    }

                    return `
                        <tr class="archived-session-row" onclick="showSessionDetail('${escapeHtml(g.game_id)}')">
                            <td class="font-mono">${escapeHtml(truncateId(g.game_id, 12))}</td>
                            <td>${players.map(p => truncateId(p, 10)).join(', ')}</td>
                            <td><span class="outcome-badge outcome-${termination.reason || 'unknown'}">${reason}</span></td>
                            <td>${duration}</td>
                            <td>${endTime}</td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;
}

// ============================================
// Problems Panel
// ============================================

function updateProblems(problems) {
    const container = document.getElementById('problems-list');
    if (!container) return;

    if (!problems || problems.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <p class="text-base-content/50">No problems detected</p>
            </div>
        `;
        return;
    }

    // Show most recent first, limit to 20
    const recent = [...problems].reverse().slice(0, 20);

    container.innerHTML = recent.map(p => `
        <div class="problem-item problem-${p.severity}">
            <span class="problem-icon">${getProblemIcon(p.severity)}</span>
            <span class="problem-time">${formatTime(p.timestamp)}</span>
            <span class="problem-msg">${escapeHtml(p.message)}</span>
            ${p.subject_id ? `<span class="problem-subject">${escapeHtml(truncateId(p.subject_id, 10))}</span>` : ''}
        </div>
    `).join('');
}

function getProblemIcon(severity) {
    return {
        'error': '!',
        'warning': '!',
        'info': 'i'
    }[severity] || '!';
}

function updateProblemsCount() {
    const indicator = document.getElementById('problems-count-badge');
    if (!indicator) return;

    const errorCount = consoleLogs.filter(l => l.level === 'error').length;
    const problemCount = (currentState.problems || []).filter(p => p.severity === 'error').length;
    const total = Math.max(errorCount, problemCount);

    indicator.textContent = total;
    indicator.style.display = total > 0 ? 'inline-flex' : 'none';
}

// ============================================
// Session Outcomes (Aggregates)
// ============================================

function updateSessionOutcomes(aggregates) {
    if (!aggregates) return;

    const total = aggregates.total_sessions_ended || 0;
    const summaryStats = aggregates.summary_stats || {};

    // Update summary percentage stats with detailed breakdown
    if (total > 0) {
        const completedPct = Math.round((summaryStats.completed || 0) / total * 100);
        const waitroomTimeoutPct = Math.round((summaryStats.waitroom_timeout || 0) / total * 100);
        const partnerAwayPct = Math.round((summaryStats.partner_away || 0) / total * 100);
        const partnerLeftPct = Math.round((summaryStats.partner_left || 0) / total * 100);
        const otherPct = Math.round((summaryStats.other || 0) / total * 100);

        setElementText('stat-pct-completed', `${completedPct}%`);
        setElementText('stat-pct-waitroom-timeout', `${waitroomTimeoutPct}%`);
        setElementText('stat-pct-partner-away', `${partnerAwayPct}%`);
        setElementText('stat-pct-partner-left', `${partnerLeftPct}%`);
        setElementText('stat-pct-other', `${otherPct}%`);
    } else {
        setElementText('stat-pct-completed', '--%');
        setElementText('stat-pct-waitroom-timeout', '--%');
        setElementText('stat-pct-partner-away', '--%');
        setElementText('stat-pct-partner-left', '--%');
        setElementText('stat-pct-other', '--%');
    }

    // Render scene histogram
    const sceneEndings = aggregates.scene_endings || {};
    renderSceneHistogram(sceneEndings);

    // Wait time stats
    const waitTime = aggregates.wait_time || {};
    setElementText('wait-avg', waitTime.avg_ms != null ? formatDuration(waitTime.avg_ms) : '--');
    setElementText('wait-max', waitTime.max_ms != null ? formatDuration(waitTime.max_ms) : '--');

    // Latency sparkline
    const latency = aggregates.latency || {};
    const sparklineContainer = document.getElementById('latency-sparkline');
    if (sparklineContainer && latency.samples && latency.samples.length > 1) {
        sparklineContainer.innerHTML = renderSparkline(latency.samples);
    }
    setElementText('latency-current', latency.current_avg_ms != null ? `${latency.current_avg_ms}ms` : '--');
}

function renderSceneHistogram(sceneEndings) {
    const container = document.getElementById('scene-histogram');
    if (!container) return;

    const scenes = Object.entries(sceneEndings);
    if (scenes.length === 0) {
        container.innerHTML = '<p class="text-base-content/50 text-sm">No data yet</p>';
        return;
    }

    // Sort scenes by name (numeric-aware sorting)
    scenes.sort((a, b) => a[0].localeCompare(b[0], undefined, { numeric: true }));

    // Calculate total for percentages
    const totalEndings = scenes.reduce((sum, [_, count]) => sum + count, 0);
    const maxCount = Math.max(...scenes.map(s => s[1]));
    const maxHeight = 50;

    container.innerHTML = scenes.map(([sceneId, count]) => {
        const height = totalEndings > 0 ? Math.max(4, (count / maxCount) * maxHeight) : 4;
        const percentage = totalEndings > 0 ? Math.round((count / totalEndings) * 100) : 0;
        const displayId = sceneId.length > 10 ? sceneId.substring(0, 9) + '...' : sceneId;
        return `
            <div class="scene-bar-wrapper" title="${escapeHtml(sceneId)}: ${count} (${percentage}%)">
                <span class="scene-bar-pct">${percentage}%</span>
                <div class="scene-bar" style="height: ${height}px"></div>
                <span class="scene-bar-label">${escapeHtml(displayId)}</span>
            </div>
        `;
    }).join('');
}

function renderSparkline(samples, width = 120, height = 30) {
    if (!samples || samples.length < 2) return '';

    const max = Math.max(...samples, 150);
    const min = Math.min(...samples, 0);
    const range = max - min || 1;
    const step = width / (samples.length - 1);

    const points = samples.map((v, i) =>
        `${i * step},${height - ((v - min) / range) * (height - 4) - 2}`
    ).join(' ');

    const lastValue = samples[samples.length - 1];
    const color = lastValue > 150 ? '#ef4444' : lastValue > 100 ? '#eab308' : '#22c55e';

    return `
        <svg width="${width}" height="${height}" class="sparkline">
            <polyline points="${points}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
    `;
}

// ============================================
// Console Logs
// ============================================

function addConsoleLog(log) {
    consoleLogs.unshift(log);
    if (consoleLogs.length > 500) {
        consoleLogs = consoleLogs.slice(0, 500);
    }
    renderConsoleLogs();
    updateProblemsCount();
}

function renderConsoleLogs() {
    const container = document.getElementById('console-logs-list');
    if (!container) return;

    let filtered = consoleLogs;
    if (logLevelFilter !== 'all') {
        filtered = filtered.filter(l => l.level === logLevelFilter);
    }
    if (logParticipantFilter !== 'all') {
        filtered = filtered.filter(l => l.subject_id === logParticipantFilter);
    }

    setElementText('logs-count', filtered.length);

    if (filtered.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <p class="text-base-content/50">No logs</p>
            </div>
        `;
        return;
    }

    container.innerHTML = filtered.slice(0, 100).map(log => `
        <div class="log-entry log-${log.level}">
            <span class="log-time">${formatTime(log.timestamp)}</span>
            <span class="log-level">${(log.level || 'log').toUpperCase()}</span>
            <span class="log-subject">${escapeHtml(truncateId(log.subject_id, 10))}</span>
            <span class="log-msg">${escapeHtml(log.message)}</span>
        </div>
    `).join('');
}

function updateParticipantFilter(participants) {
    const select = document.getElementById('log-participant-filter');
    if (!select) return;

    const currentValue = select.value;
    const participantIds = [...new Set(consoleLogs.map(l => l.subject_id))];

    select.innerHTML = '<option value="all">All Participants</option>';
    participantIds.forEach(id => {
        const option = document.createElement('option');
        option.value = id;
        option.textContent = truncateId(id, 12);
        select.appendChild(option);
    });

    if (participantIds.includes(currentValue) || currentValue === 'all') {
        select.value = currentValue;
    }
}

// ============================================
// Completed Participants (Collapsible)
// ============================================

function updateCompletedParticipants(participants) {
    const container = document.getElementById('completed-participants-list');
    const countEl = document.getElementById('completed-count');
    if (!container) return;

    const completed = participants.filter(p => p.connection_status === 'completed');

    if (countEl) countEl.textContent = completed.length;

    if (completed.length === 0) {
        container.innerHTML = '<p class="text-base-content/50 p-4">No completed participants</p>';
        return;
    }

    container.innerHTML = `
        <table class="completed-table">
            <thead>
                <tr>
                    <th>Subject ID</th>
                    <th>Duration</th>
                    <th>Scenes</th>
                    <th>Errors</th>
                </tr>
            </thead>
            <tbody>
                ${completed.map(p => {
                    const duration = p.created_at && p.last_updated_at
                        ? formatDuration((p.last_updated_at - p.created_at) * 1000)
                        : '--';
                    const progress = p.scene_progress
                        ? `${p.scene_progress.current_index + 1}/${p.scene_progress.total_scenes}`
                        : '--';
                    return `
                        <tr onclick="showParticipantDetail('${escapeHtml(p.subject_id)}')">
                            <td class="font-mono">${escapeHtml(truncateId(p.subject_id, 16))}</td>
                            <td>${duration}</td>
                            <td>${progress}</td>
                            <td>${p.error_count > 0 ? `<span class="error-badge">${p.error_count}</span>` : '--'}</td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;
}

// ============================================
// Participant Detail Panel
// ============================================

function showParticipantDetail(subjectId) {
    selectedParticipantId = subjectId;
    const overlay = document.getElementById('participant-detail-overlay');
    const content = document.getElementById('participant-detail-content');
    if (!overlay || !content) return;

    const participant = currentState.participants?.find(p => p.subject_id === subjectId);
    if (!participant) {
        content.innerHTML = '<p class="text-center p-4">Participant not found</p>';
        overlay.classList.remove('hidden');
        return;
    }

    // Status color - IMPORTANT: Check waitroom_info BEFORE current_game_id
    // because participants in waitroom also have a game_id assigned
    let statusColor = '#22c55e';
    let statusLabel = 'Connected';
    if (participant.waitroom_info) {
        statusColor = '#eab308';
        statusLabel = 'Waiting';
    } else if (participant.current_game_id) {
        statusColor = '#3b82f6';
        statusLabel = 'In Game';
    } else if (participant.connection_status === 'reconnecting') {
        statusColor = '#f97316';
        statusLabel = 'Reconnecting';
    } else if (participant.connection_status === 'disconnected') {
        statusColor = '#ef4444';
        statusLabel = 'Disconnected';
    } else if (participant.connection_status === 'completed') {
        statusColor = '#9ca3af';
        statusLabel = 'Completed';
    }

    // Duration - use last_updated_at for disconnected/reconnecting/completed, Date.now() for active
    let duration = '--';
    if (participant.created_at) {
        const isInactive = participant.connection_status === 'disconnected' ||
                          participant.connection_status === 'reconnecting' ||
                          participant.connection_status === 'completed';
        const endTime = isInactive && participant.last_updated_at ? participant.last_updated_at : Date.now() / 1000;
        duration = formatDuration((endTime - participant.created_at) * 1000);
    }

    const participantLogs = consoleLogs.filter(l => l.subject_id === subjectId).slice(0, 50);

    // Scene display - always show actual scene name
    const sceneDisplay = participant.current_scene_id || '--';

    // Scene progress (separate from scene name)
    let progressDisplay = '';
    if (participant.scene_progress) {
        progressDisplay = `${participant.scene_progress.current_index + 1}/${participant.scene_progress.total_scenes}`;
    }

    // Waitroom info
    let waitroomHtml = '';
    if (participant.waitroom_info) {
        const w = participant.waitroom_info;
        const waitSecs = Math.floor(w.wait_duration_ms / 1000);
        const waitDisplay = waitSecs < 60 ? `${waitSecs}s` : `${Math.floor(waitSecs / 60)}m ${waitSecs % 60}s`;
        waitroomHtml = `
            <div class="detail-item">
                <span class="detail-label">Waitroom</span>
                <span class="detail-value" style="color: #eab308;">${w.waiting_count}/${w.target_size} players</span>
            </div>
            <div class="detail-item">
                <span class="detail-label">Wait Time</span>
                <span class="detail-value">${waitDisplay}</span>
            </div>
        `;
    }

    // Episode info
    let episodeHtml = '';
    if (participant.current_game_id && participant.current_episode != null) {
        episodeHtml = `
            <div class="detail-item">
                <span class="detail-label">Round</span>
                <span class="detail-value">${participant.current_episode + 1}</span>
            </div>
        `;
    }

    content.innerHTML = `
        <div class="detail-section">
            <h4>Info</h4>
            <div class="detail-grid">
                <div class="detail-item">
                    <span class="detail-label">Subject ID</span>
                    <span class="detail-value font-mono">${escapeHtml(participant.subject_id)}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Status</span>
                    <span class="detail-value" style="color: ${statusColor};">${statusLabel}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Scene</span>
                    <span class="detail-value">${escapeHtml(sceneDisplay)}</span>
                </div>
                ${progressDisplay ? `
                <div class="detail-item">
                    <span class="detail-label">Progress</span>
                    <span class="detail-value">${progressDisplay}</span>
                </div>
                ` : ''}
                <div class="detail-item">
                    <span class="detail-label">Duration</span>
                    <span class="detail-value">${duration}</span>
                </div>
                ${participant.current_game_id && !participant.waitroom_info ? `
                <div class="detail-item">
                    <span class="detail-label">Session</span>
                    <span class="detail-value font-mono" style="color: #3b82f6; cursor: pointer;"
                          onclick="showSessionDetail('${escapeHtml(participant.current_game_id)}'); closeParticipantDetail();">
                        ${escapeHtml(truncateId(participant.current_game_id, 12))}
                    </span>
                </div>
                ` : ''}
                ${episodeHtml}
                ${waitroomHtml}
            </div>
        </div>
        <div class="detail-section">
            <h4>Logs (${participantLogs.length})</h4>
            <div class="detail-logs">
                ${participantLogs.length > 0
                    ? participantLogs.map(log => `
                        <div class="log-entry log-${log.level}">
                            <span class="log-time">${formatTime(log.timestamp)}</span>
                            <span class="log-level">${(log.level || 'log').toUpperCase()}</span>
                            <span class="log-msg">${escapeHtml(log.message)}</span>
                        </div>
                    `).join('')
                    : '<p class="text-base-content/50 p-2">No logs</p>'
                }
            </div>
        </div>
    `;
    overlay.classList.remove('hidden');
}

function closeParticipantDetail() {
    selectedParticipantId = null;
    const overlay = document.getElementById('participant-detail-overlay');
    if (overlay) overlay.classList.add('hidden');
}

// ============================================
// Session Detail Panel
// ============================================

function showSessionDetail(gameId) {
    selectedSessionId = gameId;
    const overlay = document.getElementById('session-detail-overlay');
    const content = document.getElementById('session-detail-content');
    if (!overlay || !content) return;

    // Find session in active or completed
    let session = currentState.multiplayer_games?.find(g => g.game_id === gameId);
    let isArchived = false;

    if (!session) {
        session = currentState.completed_games?.find(g => g.game_id === gameId);
        isArchived = true;
    }

    if (!session) {
        content.innerHTML = '<p class="text-center p-4">Session not found</p>';
        overlay.classList.remove('hidden');
        return;
    }

    // For archived sessions, use the stored session_health if available
    const health = isArchived
        ? (session.session_health || 'archived')
        : (session.session_health || 'healthy');
    let healthColor = '#22c55e';
    if (health === 'degraded') healthColor = '#eab308';
    if (health === 'reconnecting' || health === 'problem') healthColor = '#ef4444';
    if (health === 'archived') healthColor = '#9ca3af';

    const p2pHealth = session.p2p_health || {};
    const subjectIds = session.subject_ids || [];
    const termination = session.termination;

    // Calculate connection stats summary for display
    const latencies = Object.values(p2pHealth).map(h => h.latency_ms).filter(l => l != null);
    const avgLatency = latencies.length > 0
        ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length)
        : null;
    const firstPlayerHealth = Object.values(p2pHealth)[0] || {};
    const connectionType = firstPlayerHealth.connection_type || 'unknown';

    // Get all logs for players in this session
    const sessionLogs = isArchived && session.archived_logs
        ? session.archived_logs
        : consoleLogs.filter(l => subjectIds.includes(l.subject_id)).slice(0, 50);

    // Build player stats table
    const playerStatsHtml = subjectIds.map(sid => {
        const participant = currentState.participants?.find(p => p.subject_id === sid);
        const playerHealth = Object.values(p2pHealth).find(h => true); // Get any health data
        const latency = playerHealth?.latency_ms;
        const connType = playerHealth?.connection_type;
        const errorCount = participant?.error_count || 0;

        return `
            <tr onclick="showParticipantDetail('${escapeHtml(sid)}'); closeSessionDetail();">
                <td class="font-mono">${escapeHtml(sid)}</td>
                <td>${latency != null ? latency + 'ms' : '--'}</td>
                <td>${getConnectionLabel(connType || 'unknown')}</td>
                <td>${errorCount > 0 ? `<span class="error-badge">${errorCount}</span>` : '0'}</td>
            </tr>
        `;
    }).join('');

    // Calculate duration - use completed_at if archived, Date.now() if still active
    let sessionDuration = '--';
    if (session.created_at && session.completed_at) {
        sessionDuration = formatDuration((session.completed_at - session.created_at) * 1000);
    } else if (session.created_at && !isArchived) {
        sessionDuration = formatDuration((Date.now() / 1000 - session.created_at) * 1000);
    }

    // Episode info
    const episodeDisplay = session.max_episodes
        ? `${session.current_episode || session.max_episodes}/${session.max_episodes}`
        : (session.current_episode != null ? session.current_episode + 1 : '--');

    content.innerHTML = `
        <div class="detail-section">
            <h4>Session Info</h4>
            <div class="detail-grid">
                <div class="detail-item">
                    <span class="detail-label">Session ID</span>
                    <span class="detail-value font-mono">${escapeHtml(session.game_id)}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Status</span>
                    <span class="detail-value" style="color: ${healthColor};">${health}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Scene</span>
                    <span class="detail-value">${escapeHtml(session.scene_id || '--')}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Episodes</span>
                    <span class="detail-value">${episodeDisplay}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Duration</span>
                    <span class="detail-value">${sessionDuration}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Players</span>
                    <span class="detail-value">${subjectIds.length}</span>
                </div>
            </div>
        </div>

        ${Object.keys(p2pHealth).length > 0 ? `
        <div class="detail-section">
            <h4>Connection Stats</h4>
            <div class="detail-grid">
                <div class="detail-item">
                    <span class="detail-label">Connection</span>
                    <span class="detail-value">${getConnectionLabel(connectionType)}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Avg Latency</span>
                    <span class="detail-value">${avgLatency != null ? avgLatency + 'ms' : '--'}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Health</span>
                    <span class="detail-value" style="color: ${healthColor};">${health}</span>
                </div>
            </div>
        </div>
        ` : ''}

        ${termination ? `
        <div class="detail-section termination-section">
            <h4>Outcome</h4>
            <div class="termination-info">
                <span class="termination-reason">${getTerminationLabel(termination.reason)}</span>
                <span class="termination-time">${formatTime(termination.timestamp)}</span>
            </div>
        </div>
        ` : ''}

        <div class="detail-section">
            <h4>Players</h4>
            <table class="players-table">
                <thead>
                    <tr>
                        <th>Subject ID</th>
                        <th>Latency</th>
                        <th>Connection</th>
                        <th>Errors</th>
                    </tr>
                </thead>
                <tbody>
                    ${playerStatsHtml}
                </tbody>
            </table>
        </div>

        <div class="detail-section">
            <h4>Session Logs (${sessionLogs.length})</h4>
            <div class="detail-logs">
                ${sessionLogs.length > 0
                    ? sessionLogs.map(log => `
                        <div class="log-entry log-${log.level}">
                            <span class="log-time">${formatTime(log.timestamp)}</span>
                            <span class="log-level">${(log.level || 'log').toUpperCase()}</span>
                            <span class="log-subject">${escapeHtml(truncateId(log.subject_id, 8))}</span>
                            <span class="log-msg">${escapeHtml(log.message)}</span>
                        </div>
                    `).join('')
                    : '<p class="text-base-content/50 p-2">No logs</p>'
                }
            </div>
        </div>
    `;
    overlay.classList.remove('hidden');
}

function closeSessionDetail() {
    selectedSessionId = null;
    const overlay = document.getElementById('session-detail-overlay');
    if (overlay) overlay.classList.add('hidden');
}

function getTerminationLabel(reason) {
    return {
        'partner_disconnected': 'Partner Disconnected',
        'focus_loss_timeout': 'Focus Loss Timeout',
        'sustained_ping': 'High Latency',
        'tab_hidden': 'Tab Hidden',
        'exclusion': 'Excluded',
        'normal': 'Completed',
        'reconnection_timeout': 'Reconnection Timeout',
        'waitroom_timeout': 'Waitroom Timeout'
    }[reason] || reason || 'Unknown';
}

// ============================================
// Utility functions
// ============================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function truncateId(id, maxLen = 10) {
    if (!id) return '--';
    const s = String(id);
    if (s.length <= maxLen) return s;
    return s.substring(0, maxLen - 3) + '...';
}

function formatTime(ts) {
    if (!ts) return '--';
    const date = new Date(ts * 1000);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDuration(ms) {
    if (ms == null || ms < 0) return '--';
    const totalSeconds = Math.floor(ms / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    if (hours > 0) return `${hours}h ${minutes}m`;
    if (minutes > 0) return `${minutes}m ${seconds}s`;
    return `${seconds}s`;
}

// ============================================
// Event listeners
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    // Show inactive participants toggle
    const inactiveToggle = document.getElementById('show-inactive-toggle');
    if (inactiveToggle) {
        inactiveToggle.addEventListener('change', (e) => {
            showInactiveParticipants = e.target.checked;
            // Re-render with current state
            if (currentState.participants) {
                updateActiveParticipantsTable(currentState.participants, currentState.multiplayer_games);
            }
        });
    }

    // Log level filter
    const levelFilter = document.getElementById('log-level-filter');
    if (levelFilter) {
        levelFilter.addEventListener('change', (e) => {
            logLevelFilter = e.target.value;
            renderConsoleLogs();
        });
    }

    // Participant filter
    const participantFilter = document.getElementById('log-participant-filter');
    if (participantFilter) {
        participantFilter.addEventListener('change', (e) => {
            logParticipantFilter = e.target.value;
            renderConsoleLogs();
        });
    }

    // Close panels on overlay click
    document.getElementById('participant-detail-overlay')?.addEventListener('click', (e) => {
        if (e.target.id === 'participant-detail-overlay') closeParticipantDetail();
    });
    document.getElementById('session-detail-overlay')?.addEventListener('click', (e) => {
        if (e.target.id === 'session-detail-overlay') closeSessionDetail();
    });
});

// Periodic state refresh (fallback)
setInterval(() => {
    if (adminSocket.connected) {
        adminSocket.emit('request_state');
    }
}, 5000);
