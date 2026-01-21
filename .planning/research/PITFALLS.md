# Pitfalls Research: Participant Exclusion

**Domain:** Browser-based RL experiments with participant screening
**Researched:** 2026-01-21
**Confidence:** MEDIUM (WebSearch-based research, verified against documented patterns)

## Executive Summary

The top 5 critical pitfalls for participant exclusion systems in interactive experiments:

1. **Ping measurement inaccuracy** — Browser TCP-based ping measurements include HTTP/TLS overhead, reporting 30-50ms higher than actual network latency. A 200ms threshold may exclude participants with 150ms true latency.

2. **Browser detection unreliability** — User agent strings are spoofable, outdated, and inconsistent across browsers. Firefox exclusion rules could incorrectly block legitimate Chromium browsers or miss Firefox users spoofing Chrome.

3. **Power-saving mode WebSocket disconnects** — Backgrounded browser tabs throttle timers to 1/minute, causing false-positive inactivity detection and heartbeat failures even when participants are actively engaged.

4. **Multiplayer cascade exclusion unfairness** — When one player is excluded mid-game, the other player loses their session through no fault of their own. Without clear messaging and compensation, this damages participant trust.

5. **Demographic sampling bias** — Strict technical requirements (modern browser, screen size, low ping) systematically exclude participants with older hardware, rural connections, or mobile devices, reducing sample representativeness.

## Measurement Pitfalls

### P1: TCP/HTTP Ping Overhead vs. True Network Latency

**What goes wrong:** Browser-based ping measurements use HTTP/HTTPS requests over TCP, which includes TLS handshake, HTTP headers, and application layer overhead. This reports latency 30-50ms higher than ICMP ping or raw TCP.

**Why it happens:** Browsers cannot access ICMP (layer 3) directly. Even WebSocket ping/pong operates at layer 4+ with application overhead. WebRTC DataChannels can get closer to true UDP latency but still include protocol overhead.

**Consequences:** A participant with 150ms true network latency may measure 180-200ms via HTTP ping, crossing a 200ms exclusion threshold. You exclude participants who would actually perform acceptably.

**Warning signs:**
- Participants who report their connection is fast but are excluded
- Exclusion rates higher than expected for geographic regions
- Mismatch between pre-experiment ping and in-game RTT measurements

**Prevention:**
- Measure RTT using WebRTC DataChannel once P2P connection is established (closer to game-relevant latency)
- Use percentile thresholds (e.g., 95th percentile over N samples) rather than single measurements
- Add 30-50ms buffer to account for measurement overhead
- Measure multiple times and average, discarding outliers

**Phase mapping:** Address during initial screening implementation (core infrastructure)

**Sources:**
- [Azure Speed Test Documentation](https://www.azurespeed.com/Azure/Latency) - explains TCP vs ICMP differences
- [websockets library documentation](https://websockets.readthedocs.io/en/stable/topics/keepalive.html)

---

### P2: Temporary Latency Spikes Causing False Positive Exclusions

**What goes wrong:** A single latency spike (due to WiFi interference, background process, or network congestion) triggers exclusion even though the participant's connection is generally stable.

**Why it happens:** Instantaneous measurements capture point-in-time conditions. Wireless networks experience transient issues from channel congestion, signal noise, or even microwave interference. These spikes are typically seconds long, not minutes.

**Consequences:** Participant is excluded mid-experiment for a 2-second network hiccup that doesn't affect gameplay meaningfully.

**Warning signs:**
- Mid-experiment exclusions that don't correlate with observable gameplay issues
- Exclusion logs showing single spike followed by normal values
- Higher exclusion rates during certain times of day (network congestion patterns)

**Prevention:**
- Require N consecutive violations before exclusion (e.g., 3 consecutive ping measurements > threshold)
- Use rolling average or sliding window (e.g., 5-second moving average)
- Distinguish between sustained degradation and transient spikes
- Log spike events without immediate exclusion, analyze patterns

**Phase mapping:** Address in continuous monitoring logic

---

### P3: Jitter Ignored in Quality Assessment

**What goes wrong:** Focus only on mean latency while ignoring jitter (variance in latency). A participant with 100ms mean but 50ms jitter experiences worse gameplay than one with 150ms mean and 5ms jitter.

**Why it happens:** Ping thresholds are intuitive; jitter measurement requires tracking multiple samples and calculating variance.

**Consequences:** Participants with stable-but-slow connections are excluded while participants with unstable-but-average connections are admitted. The unstable connections cause more gameplay issues.

**Warning signs:**
- Admitted participants experience more rollbacks/corrections than excluded ones
- Post-experiment surveys report lag despite passing screening
- Game data shows high rollback rates for nominally-qualifying participants

**Prevention:**
- Track both mean RTT and jitter (standard deviation of RTT)
- Consider composite scoring: `quality_score = mean_rtt + (2 * jitter)`
- Set thresholds for both metrics independently

**Phase mapping:** Enhancement after basic ping threshold works

---

### P4: Browser Detection via User Agent Is Unreliable

**What goes wrong:** User agent string parsing incorrectly identifies browser, leading to false exclusions or false admissions.

**Why it happens:**
- User agent strings are user-configurable and frequently spoofed
- Browsers lie about their identity (Vivaldi reports as Chrome, iPad Safari reports as desktop Safari)
- Detection libraries become outdated as new browser versions release
- Modern browsers are converging on similar UA patterns

**Consequences:**
- Block legitimate Chrome users because UA contains "Firefox" compatibility token
- Admit Firefox users who spoofed their UA to Chrome
- Exclude all iPad users because they report desktop Safari UA

**Warning signs:**
- Exclusion/admission doesn't match reported browser in post-experiment survey
- Inconsistent behavior between "same browser" participants
- Sudden spike in exclusions after browser update releases

**Prevention:**
- Use feature detection over browser detection where possible
- If browser-specific, use multiple signals: `navigator.userAgent`, `navigator.userAgentData` (Client Hints API), and feature probes
- Consider why you're excluding a browser — if it's a feature concern, test for the feature directly
- Accept that 100% accuracy is impossible; design for graceful degradation

**Phase mapping:** Address during browser exclusion rule implementation

**Sources:**
- [MDN Browser Detection Guide](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Browser_detection_using_the_user_agent)
- [Niels Leenheer article on browser detection](https://nielsleenheer.com/articles/2024/should-we-rely-on-browser-detection/)

---

### P5: Screen Size Detection Pitfalls

**What goes wrong:** Screen size checks fail due to device pixel ratio, browser chrome, or resize events.

**Why it happens:**
- `screen.width` vs `screen.availWidth` vs `window.innerWidth` measure different things
- Retina/HiDPI displays have device pixel ratio > 1, meaning 1 CSS pixel != 1 device pixel
- Browser chrome (toolbar, bookmarks bar) reduces available viewport
- Window resize events fire hundreds of times per second

**Consequences:**
- Exclude participants on high-resolution devices (e.g., 4K monitor at 200% scaling shows as 960px logical width)
- Admit participants who then resize window below minimum during experiment
- Performance issues from unthrottled resize event handlers

**Warning signs:**
- Participants with large monitors being excluded for screen size
- Game elements clipped or unusable despite passing initial check
- Client-side performance issues during window manipulation

**Prevention:**
- Use `window.innerWidth`/`window.innerHeight` for viewport (what's usable)
- Account for device pixel ratio in threshold calculations
- Throttle/debounce resize event handlers
- Re-check screen size on resize and warn/exclude if it drops below minimum
- Consider CSS media queries for responsive adjustments vs hard exclusion

**Phase mapping:** Address during device requirement rule implementation

**Sources:**
- [OpenReplay article on resize pitfalls](https://blog.openreplay.com/avoiding-resize-event-pitfalls-js/)
- [MDN Screen.width](https://developer.mozilla.org/en-US/docs/Web/API/Screen/width)

## UX Pitfalls

### P6: Opaque Exclusion Messages Frustrate Participants

**What goes wrong:** Participant sees "You cannot participate" without understanding why or what they could do differently.

**Why it happens:** System designed from researcher perspective (need to filter), not participant perspective (want to participate).

**Consequences:**
- Frustrated participants leave negative reviews on Prolific/MTurk
- Participants retry repeatedly, wasting their time and creating support burden
- Lower completion rates as word spreads that the experiment is "broken"

**Warning signs:**
- Support tickets asking "why was I excluded?"
- Low ratings despite experiment content being fine
- Participants attempting to circumvent screening (VPN, browser changes)

**Prevention:**
- Per-rule messaging that explains: (1) what failed, (2) why it matters, (3) what they could try
- Example: "Your network latency is 250ms (our limit is 200ms). This experiment requires fast connections for real-time gameplay. You might try a wired connection or closing other applications."
- Distinguish between "try again later" issues (ping) and "cannot participate" issues (browser requirement)
- Provide estimated compensation for time spent in screening if excluded

**Phase mapping:** Address in messaging system design (early)

---

### P7: Screening Takes Too Long, Causing Abandonment

**What goes wrong:** Pre-experiment screening runs multiple tests sequentially, taking 30+ seconds. Participants abandon before completing.

**Why it happens:** Conservative approach runs all checks thoroughly. Each check (ping, browser, screen, etc.) runs independently.

**Consequences:**
- High pre-experiment dropout rate
- Wasted participant pool — they saw the experiment, can't re-recruit them
- Selection bias toward patient participants

**Warning signs:**
- Analytics show high dropout during "loading" phase
- Time-to-game-start metrics are high
- Participants report experiment is "slow to start"

**Prevention:**
- Run checks in parallel where possible (browser check while ping is measured)
- Fail fast: check cheapest/most-likely-to-fail criteria first
- Show progress indicator: "Checking your connection... Checking your browser..."
- Set timeout on screening phase (if screening takes > 10s, something is wrong)
- Cache browser/screen checks — they don't change during session

**Phase mapping:** Address in screening flow implementation

---

### P8: Mid-Experiment Exclusion Without Warning

**What goes wrong:** Participant is playing, everything seems fine, then suddenly excluded without warning.

**Why it happens:** Continuous monitoring detects violation, system immediately excludes per design.

**Consequences:**
- Participant loses progress, feels cheated
- No opportunity to correct issue (close background apps, etc.)
- Higher complaint rate than pre-experiment exclusion

**Warning signs:**
- Spike in complaints specifically about mid-game exclusions
- Participants reporting they were excluded "for no reason"
- Data shows brief threshold violations before exclusion

**Prevention:**
- Implement warning system before exclusion: "Your connection is unstable. Please close other applications."
- Allow grace period after warning before actual exclusion
- Distinguish between immediate exclusion criteria (inactivity = cheating concern) vs warning-first criteria (ping spike = technical issue)
- Log warning events for post-experiment analysis

**Phase mapping:** Address in continuous monitoring design

---

### P9: False Positive Inactivity Detection

**What goes wrong:** Participant is watching/thinking (valid in many games) but gets flagged as inactive because no input events fire.

**Why it happens:** Inactivity detection monitors keyboard/mouse events. Some game states don't require input (watching replay, waiting for other player, planning phase).

**Consequences:**
- Exclude participants who are legitimately engaged but not pressing keys
- Particularly problematic in turn-based or observation-heavy experiments

**Warning signs:**
- Inactivity exclusions cluster during specific game phases
- Excluded participants report they were paying attention
- Game logs show exclusion during non-interactive portions

**Prevention:**
- Reset inactivity timer on any user interaction (mouse movement, not just clicks)
- Context-aware inactivity: longer timeout during known low-input phases
- Combine with attention signals: tab visibility, mouse position (on game vs away)
- Consider eye-tracking if available, or periodic low-friction attention checks

**Phase mapping:** Address during inactivity detection implementation

**Sources:**
- [MDN Idle Detection API](https://developer.mozilla.org/en-US/docs/Web/API/Idle_Detection_API)
- [Kirupa article on idle detection](https://www.kirupa.com/html5/detecting_if_the_user_is_idle_or_inactive.htm)

## Timing Pitfalls

### P10: Power-Saving Mode Breaks Heartbeat/Inactivity Detection

**What goes wrong:** When browser tab is backgrounded, timers are throttled to 1/minute. Heartbeat fails, inactivity timer fires incorrectly.

**Why it happens:** Browser power-saving mechanisms throttle `setTimeout`/`setInterval` in background tabs to reduce CPU/battery usage. A 5-second heartbeat becomes 60-second.

**Consequences:**
- Participant switches tabs briefly (check email), returns to find they've been excluded
- Heartbeat-based disconnect detection fails or triggers false positive
- WebSocket connection drops due to missed pongs

**Warning signs:**
- Exclusions correlate with tab switch events (can detect via `visibilitychange`)
- Heartbeat logs show 60s gaps
- Participants report being excluded when they "just switched tabs for a second"

**Prevention:**
- Use Web Workers for critical timers (not affected by tab throttling)
- Listen for `visibilitychange` event — pause inactivity timer when hidden, resume when visible
- Don't treat backgrounded tab as inactivity if it returns within reasonable window
- For WebSocket heartbeat, increase `pingTimeout` to account for throttling, or use Web Worker

**Phase mapping:** Critical — address in heartbeat/inactivity infrastructure

**Sources:**
- [PixelsTech article on WebSocket power-saving pitfalls](https://www.pixelstech.net/article/1719122489-the-pitfall-of-websocket-disconnections-caused-by-browser-power-saving-mechanisms)
- [Socket.IO heartbeat discussion](https://github.com/socketio/socket.io/discussions/4161)

---

### P11: Race Condition Between Screening and Game Start

**What goes wrong:** Participant passes screening, but by the time game actually starts, their conditions have changed (ping spiked, window resized).

**Why it happens:** Screening happens before game initialization. Multiplayer requires waiting for other player. Gap between screen and start can be seconds to minutes.

**Consequences:**
- Participant admitted but then has poor experience due to degraded conditions
- Or: participant meets criteria at start, fails continuous monitoring immediately
- State mismatch between what was checked and current reality

**Warning signs:**
- Continuous monitoring exclusions cluster immediately after game start
- Large gap between screening timestamp and game start timestamp
- Participants report passing screening but being excluded at start

**Prevention:**
- Re-validate critical criteria immediately before game start
- Keep screening criteria "fresh" — re-measure ping if waitroom time exceeds threshold
- Design continuous monitoring to expect initial fluctuation (grace period at start)

**Phase mapping:** Address in screening-to-game transition logic

---

### P12: Screening Check Order Creates Bad UX

**What goes wrong:** Slow check runs first (10-second ping sampling), then fast check fails (wrong browser). Participant waited 10 seconds only to be immediately rejected.

**Why it happens:** Checks run in code order, not optimized order.

**Consequences:**
- Wasted participant time
- Higher dropout during screening
- Poor perceived performance

**Warning signs:**
- Screening takes longer than necessary before rejection
- Analytics show most rejections happen after slow checks

**Prevention:**
- Order checks: fastest first, then most-likely-to-fail first
- Run independent checks in parallel
- Fail fast: browser/device checks are instant, run before ping sampling

**Phase mapping:** Address in screening orchestration

## Multiplayer Pitfalls

### P13: One Player Excluded, Other Player Stranded

**What goes wrong:** Player A gets excluded mid-game. Player B's game ends abruptly with no explanation.

**Why it happens:** System designed for exclusion mechanics, not for partner communication.

**Consequences:**
- Player B confused and frustrated
- Player B may think they were excluded
- Both players rate experiment poorly

**Warning signs:**
- Complaints from players who "didn't do anything wrong"
- Confusion in post-experiment surveys about why game ended
- Lower ratings from multiplayer sessions than single-player

**Prevention:**
- Explicit messaging for non-excluded player: "The game has ended because your partner experienced a technical issue. This is not your fault."
- Compensate non-excluded player appropriately
- Log reason in research data (distinguish partner-exclusion from self-exclusion)
- Consider allowing non-excluded player to re-queue for new partner

**Phase mapping:** Address in multiplayer exclusion handling (critical for multiplayer experiments)

---

### P14: Asymmetric Exclusion Criteria Cause Unfairness

**What goes wrong:** Player A has stricter hardware, Player B has lenient hardware. A gets excluded, B doesn't. Or vice versa — A's criteria should have excluded them earlier.

**Why it happens:** Screening criteria evaluated independently per player. Criteria designed for individual participation, not pairs.

**Consequences:**
- Player B paired with Player A who should have been excluded earlier
- Game experience poor due to A's issues before exclusion triggers
- Perception of unfairness

**Warning signs:**
- Multiplayer games with high variance in partner quality
- Complaints about being paired with "laggy" partners
- Post-game data shows one player consistently experiencing issues

**Prevention:**
- Consider screening pairs, not just individuals — if pair has high RTT delta, warn or re-match
- Set minimum criteria for all multiplayer participants (higher bar than single-player)
- Monitor game-level metrics (P2P latency between specific pair) not just individual metrics

**Phase mapping:** Enhancement after basic exclusion works

---

### P15: State Synchronization Issues During Exclusion

**What goes wrong:** Player A is excluded, but exclusion message races with game state updates. Player B sees inconsistent state — game appears to continue for a frame, then ends.

**Why it happens:** P2P systems have state synchronization challenges. Exclusion is server-initiated but game state is peer-maintained.

**Consequences:**
- Visual glitches during exclusion
- Potential for game logic issues if one peer processes inputs after other has stopped
- Data integrity concerns — which state is canonical at exclusion time?

**Warning signs:**
- Visual "flash" or "jump" during partner exclusion
- Data logs show continued game steps after exclusion timestamp
- State mismatch between exported game data

**Prevention:**
- Exclusion should be coordinated: server sends exclusion to both peers simultaneously
- Implement clean shutdown sequence: stop input processing, finalize state, then display message
- Log exclusion timestamp and frame number for data alignment
- Test exclusion at various game states and frame timings

**Phase mapping:** Address in exclusion implementation, test thoroughly

**Sources:**
- [Game state synchronization patterns](https://canbayar91.medium.com/game-mechanics-1-multiplayer-network-synchronization-46cbe21be16a)
- [Hacker News discussion on multiplayer sync](https://news.ycombinator.com/item?id=31512257)

---

### P16: Reconnection vs. Exclusion Conflict

**What goes wrong:** System has reconnection support (player drops, reconnects within window). But exclusion system treats disconnect as exclusion. Player can't reconnect because they're "excluded."

**Why it happens:** Two systems (reconnection, exclusion) with overlapping triggers but different logic.

**Consequences:**
- Legitimate disconnects treated as exclusions when they should allow reconnection
- Or: excluded players attempting to reconnect and re-entering experiment

**Warning signs:**
- Players report being able to reconnect after exclusion (security issue)
- Players report not being able to reconnect after brief disconnect (UX issue)
- Inconsistent behavior between disconnect types

**Prevention:**
- Clear distinction: exclusion = permanent removal with reason recorded, disconnect = temporary with reconnection window
- Exclusion should invalidate reconnection token
- Disconnect handling should not create exclusion record unless it exceeds reconnection window
- State machine: Connected -> Disconnected -> (Reconnected | Excluded by Timeout)

**Phase mapping:** Address in exclusion architecture, coordinate with existing reconnection logic

## Configuration Pitfalls

### P17: Overly Strict Defaults Cause Unacceptable Exclusion Rates

**What goes wrong:** Default configuration sets strict thresholds (100ms ping, latest Chrome only, 1920x1080 minimum). Exclusion rate is 40%+, depleting participant pool.

**Why it happens:** Developers test on good hardware/connections. Defaults reflect developer environment, not participant reality.

**Consequences:**
- Study cannot recruit enough participants
- Demographic skew toward high-resource participants
- Wasted recruitment budget

**Warning signs:**
- Exclusion rates in pilot significantly higher than expected
- Exclusion rates vary dramatically by geographic region or time of day
- Post-exclusion surveys show participants have "normal" setups

**Prevention:**
- Research typical participant conditions before setting defaults
- Provide conservative (lenient) defaults, document how to make stricter
- Include exclusion rate estimation in pilot phase
- A/B test thresholds during pilot to find balance

**Phase mapping:** Address in default configuration design

---

### P18: Rule Interaction/Conflict Creates Unexpected Behavior

**What goes wrong:** Multiple rules interact unexpectedly. Rule A says "exclude if ping > 200ms", Rule B says "warn if ping > 150ms". What happens at 175ms?

**Why it happens:** Rules designed independently, interactions not considered.

**Consequences:**
- Participant sees warning, then is excluded (expected warn, got exclude)
- Or: participant should be warned but isn't due to rule ordering
- Researcher intent not reflected in actual behavior

**Warning signs:**
- Unexpected exclusion/warning patterns
- Difficulty explaining system behavior to collaborators
- Bug reports about "inconsistent" screening

**Prevention:**
- Define rule precedence explicitly: exclusion rules > warning rules
- Validate configuration at startup: flag conflicting thresholds
- Provide rule simulation/preview: "with this config, here's what happens to a participant with these conditions"
- Document rule interaction model clearly

**Phase mapping:** Address in rule configuration system design

---

### P19: Custom Callbacks Are Difficult to Test

**What goes wrong:** Researcher writes custom exclusion callback. It has bugs that only manifest in production.

**Why it happens:** Custom callbacks run in production context, which is hard to replicate in testing. Edge cases not considered.

**Consequences:**
- Callback throws exception, breaking screening flow
- Callback has false positives/negatives due to untested edge cases
- Debugging is difficult because callback runs in participant's browser

**Warning signs:**
- Errors in production not reproducible locally
- Custom rule behavior differs from researcher expectation
- Increased screening failures after custom rule deployed

**Prevention:**
- Provide callback testing harness with mock participant conditions
- Wrap callbacks in try/catch with fallback behavior (fail open or fail closed, configurable)
- Log callback execution details for debugging
- Validate callback returns expected type (boolean or object with reason)
- Example callbacks for common custom scenarios

**Phase mapping:** Address in custom callback system design

---

### P20: No Visibility Into Exclusion Patterns

**What goes wrong:** Researcher knows exclusion is happening but not why, when, or to whom.

**Why it happens:** System logs exclusion events but doesn't surface analytics.

**Consequences:**
- Cannot diagnose high exclusion rates
- Cannot identify if specific criteria are too strict
- Cannot detect systematic biases

**Warning signs:**
- Researcher asks "why is my exclusion rate so high?"
- No way to answer "which rule excludes the most participants?"
- Cannot segment exclusions by demographic/condition

**Prevention:**
- Log every exclusion with: timestamp, participant ID, rule that triggered, measured value, threshold value
- Provide dashboard or export for exclusion analytics
- Aggregate metrics: exclusion rate by rule, by time of day, by browser
- Alert if exclusion rate exceeds expected threshold

**Phase mapping:** Address in monitoring/logging infrastructure

## Bias and Fairness Pitfalls

### P21: Technical Requirements Create Demographic Sampling Bias

**What goes wrong:** Strict technical requirements systematically exclude certain populations, biasing sample.

**Why it happens:** Technical requirements designed for experiment validity (need low latency) but have demographic correlates (rural areas have worse internet, older participants have older hardware).

**Consequences:**
- Sample is not representative of target population
- Results may not generalize
- Ethical concerns about excluding disadvantaged groups

**Warning signs:**
- Post-exclusion demographic analysis shows skew
- Exclusion rates higher for certain geographic regions, age groups
- Sample demographics don't match recruitment platform demographics

**Prevention:**
- Analyze exclusion impact on sample demographics during pilot
- Consider looser technical requirements with post-hoc data quality filtering
- Report exclusion demographics in research publications
- Design experiments that tolerate broader range of technical conditions where possible
- Provide alternative participation pathways (lower-fidelity version) where appropriate

**Phase mapping:** Address in research design phase, before implementation

**Sources:**
- [Cognitive Research Journal - Shadow biases in participant exclusion](https://cognitiveresearchjournal.springeropen.com/articles/10.1186/s41235-023-00520-y)
- [Nature - Demographic recruitment bias in clinical trials](https://www.nature.com/articles/s41598-022-23664-1)

---

### P22: Self-Selection Bias from Screening Friction

**What goes wrong:** Screening process itself causes differential dropout. Participants who experience screening issues (even if eventually passing) are more likely to abandon.

**Why it happens:** Screening adds friction. Participants with lower motivation or patience disproportionately drop out.

**Consequences:**
- Sample biased toward high-motivation participants
- May affect research validity if motivation correlates with study outcomes

**Warning signs:**
- High dropout during screening phase
- Dropout rate varies by technical conditions (e.g., those with borderline ping drop out more)
- Screened-in participants have different characteristics than general population

**Prevention:**
- Minimize screening friction (fast, clear, helpful)
- Track dropout at each screening stage
- Compare demographics of dropouts vs completers
- Consider paying for screening time even if excluded

**Phase mapping:** Address in UX design of screening flow

## Prevention Strategies Summary

| Pitfall | Category | Prevention Strategy | Phase |
|---------|----------|---------------------|-------|
| P1: TCP/HTTP ping overhead | Measurement | Measure via DataChannel, add buffer, multiple samples | Core infrastructure |
| P2: Temporary latency spikes | Measurement | Require consecutive violations, rolling average | Continuous monitoring |
| P3: Jitter ignored | Measurement | Track mean + jitter, composite score | Enhancement |
| P4: Browser UA unreliable | Measurement | Feature detection, multiple signals, graceful degradation | Browser rule implementation |
| P5: Screen size confusion | Measurement | Use innerWidth, account for DPR, throttle events | Device rule implementation |
| P6: Opaque messages | UX | Per-rule messaging explaining what, why, what to try | Messaging system |
| P7: Slow screening | UX | Parallel checks, fail fast, progress indicator | Screening flow |
| P8: No warning before exclusion | UX | Warning system with grace period | Continuous monitoring |
| P9: False positive inactivity | UX | Mouse movement, context-aware timeouts | Inactivity rule |
| P10: Power-saving breaks timers | Timing | Web Workers, visibilitychange handling | Core infrastructure |
| P11: Screen-to-start race | Timing | Re-validate before start, grace period | Transition logic |
| P12: Check order suboptimal | Timing | Fast checks first, parallel where possible | Screening orchestration |
| P13: Partner stranded | Multiplayer | Clear messaging, compensation, re-queue option | Multiplayer handling |
| P14: Asymmetric criteria | Multiplayer | Pair-level screening, minimum bar for multiplayer | Enhancement |
| P15: State sync during exclusion | Multiplayer | Coordinated shutdown, test thoroughly | Exclusion implementation |
| P16: Reconnect vs exclude conflict | Multiplayer | Clear state machine, invalidate tokens | Architecture |
| P17: Overly strict defaults | Configuration | Research-based defaults, pilot testing | Default design |
| P18: Rule conflicts | Configuration | Explicit precedence, validation, simulation | Config system |
| P19: Untestable callbacks | Configuration | Test harness, try/catch, logging | Callback system |
| P20: No visibility | Configuration | Detailed logging, dashboard, alerts | Monitoring |
| P21: Demographic bias | Bias | Pilot analysis, report demographics, looser requirements | Research design |
| P22: Self-selection from friction | Bias | Minimize friction, track dropout, pay for screening | UX design |

## Phase-Specific Warnings

| Phase/Component | Likely Pitfalls | Mitigation Priority |
|-----------------|-----------------|---------------------|
| Core exclusion infrastructure | P10 (power-saving), P16 (reconnect conflict) | HIGH - foundational |
| Pre-experiment screening | P7 (slow), P12 (order), P17 (strict defaults) | HIGH - first impression |
| Continuous monitoring | P2 (spikes), P8 (no warning), P11 (race) | HIGH - mid-game experience |
| Ping threshold rule | P1 (overhead), P2 (spikes), P3 (jitter) | HIGH - most complex measurement |
| Browser exclusion rule | P4 (UA unreliable) | MEDIUM - consider if really needed |
| Screen size rule | P5 (confusion) | MEDIUM - well-documented solutions |
| Inactivity detection | P9 (false positive), P10 (power-saving) | HIGH - easy to get wrong |
| Multiplayer handling | P13 (stranded), P15 (state sync) | HIGH - poor UX if wrong |
| Configuration system | P17 (defaults), P18 (conflicts), P19 (callbacks) | MEDIUM - affects researcher experience |
| Monitoring/logging | P20 (no visibility) | MEDIUM - needed for iteration |

## Sources

**Measurement and Technical:**
- [Azure Speed Test - TCP vs ICMP](https://www.azurespeed.com/Azure/Latency)
- [websockets library - Keepalive documentation](https://websockets.readthedocs.io/en/stable/topics/keepalive.html)
- [MDN - Browser detection using user agent](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Browser_detection_using_the_user_agent)
- [MDN - Screen.width property](https://developer.mozilla.org/en-US/docs/Web/API/Screen/width)
- [OpenReplay - Avoiding resize event pitfalls](https://blog.openreplay.com/avoiding-resize-event-pitfalls-js/)

**Inactivity and Idle Detection:**
- [MDN - Idle Detection API](https://developer.mozilla.org/en-US/docs/Web/API/Idle_Detection_API)
- [Kirupa - Detecting user inactivity](https://www.kirupa.com/html5/detecting_if_the_user_is_idle_or_inactive.htm)
- [PixelsTech - WebSocket power-saving disconnections](https://www.pixelstech.net/article/1719122489-the-pitfall-of-websocket-disconnections-caused-by-browser-power-saving-mechanisms)

**WebSocket and Heartbeat:**
- [Socket.IO - Ping/pong sensitivity discussion](https://github.com/socketio/socket.io/discussions/4161)
- [VideoSDK - Ping pong frame WebSocket](https://www.videosdk.live/developer-hub/websocket/ping-pong-frame-websocket)

**Multiplayer Synchronization:**
- [Can Bayar - Multiplayer network synchronization](https://canbayar91.medium.com/game-mechanics-1-multiplayer-network-synchronization-46cbe21be16a)
- [Hacker News - How video games stay in sync](https://news.ycombinator.com/item?id=31512257)

**Online Research and Bias:**
- [Springer - Conducting interactive experiments online](https://link.springer.com/article/10.1007/s10683-017-9527-2)
- [PMC - What 1M participants tell us about protocols](https://pmc.ncbi.nlm.nih.gov/articles/PMC10357382/)
- [Cognitive Research Journal - Shadow biases](https://cognitiveresearchjournal.springeropen.com/articles/10.1186/s41235-023-00520-y)
- [PMC - Realistic precision in online experiments](https://pmc.ncbi.nlm.nih.gov/articles/PMC8367876/)
- [Nature - Attention check comparison Prolific vs MTurk](https://www.nature.com/articles/s41598-023-46048-5)

---

*Pitfalls research: 2026-01-21*
*Confidence: MEDIUM — WebSearch-based with verification against documented patterns*
