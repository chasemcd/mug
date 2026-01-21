# Features Research: Participant Exclusion

**Domain:** Browser-based research experiment platforms with participant screening
**Researched:** 2026-01-21
**Confidence:** MEDIUM-HIGH (verified with official documentation and platform guides)

## Executive Summary

Research platforms implement participant screening at three levels: **pre-registration screening** (demographics/qualifications before study access), **entry-time technical checks** (device/browser validation at experiment start), and **continuous monitoring** (attention/behavior during experiment). The sophistication varies dramatically:

- **Recruitment platforms** (Prolific, MTurk, CloudResearch) excel at pre-registration demographic screening with massive filter catalogs
- **Experiment builders** (jsPsych, Gorilla, oTree) focus on entry-time technical validation with runtime behavior detection
- **Interactive Gym's use case** requires both entry checks AND continuous real-time monitoring during gameplay, plus multiplayer-specific dropout handling

**Key insight:** No existing platform handles the "multiplayer game with continuous exclusion + partner impact" case well. oTree has dropout handling for turn-based economics experiments, but real-time game scenarios need tighter monitoring. This is a differentiator opportunity.

## Table Stakes Features

Features users expect. Missing = platform unusable for serious research.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Device type detection** (mobile/desktop) | Mobile inputs differ fundamentally; many experiments require keyboard | Low | jsPsych, Gorilla have built-in. Modern devices can spoof (iPads as computers) |
| **Browser type/version check** | WebRTC/WebGL/WebAudio support varies by browser | Low | jsPsych browser-check plugin does this well |
| **Screen size minimum** | Experiments need consistent viewport; small screens break layouts | Low | jsPsych supports minimum_width/height with resize prompt |
| **Configurable rejection messages** | Researchers need to explain why participant can't continue | Low | Every platform supports custom exclusion text |
| **Consent flow integration** | IRB requires informed consent before any data collection | Medium | Must gate all screening after consent or use consent as implicit screening |
| **Pre-screening demographic filters** | Core recruitment platform functionality | Medium | Prolific has 400+ prescreeners; MTurk has qualifications; SONA has prescreen questionnaires |
| **Repeat participation prevention** | Within-subject designs need tracking; between-subjects need blocking | Medium | Session tracking, participant IDs, or browser fingerprinting |

**Implementation priority:** Device detection, browser check, and screen size are immediate needs for Interactive Gym. Consent flow already exists (StartScene). Pre-screening is handled by upstream recruitment platforms (Prolific/MTurk).

## Advanced Features (Differentiators)

Features that set product apart. Not expected, but valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Connection quality monitoring** (ping, jitter, packet loss) | Ensures valid data for latency-sensitive experiments | Medium | No existing experiment platform does this well; Interactive Gym already has WebRTC metrics |
| **Continuous real-time exclusion** | Exclude participant mid-experiment if criteria violated | High | oTree has timeout-based; jsPsych doesn't support mid-experiment exclusion |
| **Multiplayer dropout coordination** | End experiment cleanly for partner when one participant excluded | High | oTree's dropout_handling reduces timeouts; no platform handles "end for both" well |
| **Inactivity detection during gameplay** | Detect AFK participants in real-time games | Medium | oTree checks between pages; need continuous detection during game loop |
| **Fullscreen enforcement with recovery** | Prevent tab-switching during attention-critical tasks | Medium | jsPsych tracks fullscreen exit events; can prompt re-entry |
| **Tab visibility monitoring** | Detect when participant switches to other tabs | Low | Browser visibilitychange API; jsPsych records interaction data |
| **Comprehension check gating** | Block experiment continuation until instructions understood | Medium | GuidedTrack pattern: repeat instructions until quiz passed |
| **Attention check with auto-rejection** | Prolific allows rejection on 2 failed attention checks | Medium | Controversial: recent research questions validity |
| **Connection type discrimination** | Distinguish direct P2P vs TURN relay vs WebSocket fallback | Low | Interactive Gym already tracks this; can exclude TURN-only participants |
| **Custom callback exclusion rules** | Let researchers define arbitrary exclusion logic | Medium | jsPsych inclusion_function pattern is good model |

**Implementation priority:** Connection quality monitoring and multiplayer dropout coordination are the key differentiators for Interactive Gym's real-time game use case.

## Anti-Features

Features to explicitly NOT build. Common mistakes in this domain.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Duplicate all Prolific/MTurk prescreeners** | Recruitment platforms already do this; duplicating creates maintenance burden and sync issues | Accept that pre-screening is upstream; focus on technical criteria they can't check |
| **Auto-rejection on first attention check failure** | Research shows 61% of failures may be deliberate non-compliance, not inattention; false positives harm data quality | Use attention checks for flagging, not auto-exclusion; require 2+ failures |
| **Silent exclusion without explanation** | Participants deserve to know why they can't continue; platforms like Prolific require explanation | Always show configurable message explaining exclusion reason |
| **Server-side browser fingerprinting for repeat detection** | Privacy concerns, GDPR issues, fingerprints change with browser updates | Use recruitment platform's built-in repeat detection (Prolific tracks this) |
| **Complex rule engine with AND/OR/NOT operators** | Over-engineering; researchers want simple "check A, check B" not SQL-style predicates | Simple list of rules, all must pass; complex logic can use custom callbacks |
| **Blocking based on ISP/geolocation** | False positives (VPN users, travelers); CloudResearch found this unreliable alone | Combine with other signals if needed; don't use as sole criterion |
| **Mandatory fullscreen for all experiments** | Some experiments don't need it; Safari has keyboard issues in fullscreen; creates friction | Make fullscreen optional, configurable per experiment |
| **Webcam/microphone permission blocking** | Many experiments don't need A/V; prompting for unused permissions is bad UX | Only check when experiment actually uses these features |

## Platform Comparison

### Prolific

**Type:** Recruitment platform (participants pre-registered)
**Screening approach:** Pre-registration demographic filters

**Features:**
- 400+ prescreening criteria (demographics, health, personality, etc.)
- In-study custom screening (August 2025) with auto screen-out payment
- Quota studies with demographic balancing (up to 120 strata)
- "Exceptionally fast" submission detection for quality flagging
- Attention check policy: can reject on 2 failed valid checks

**Strengths:** Massive prescreener library, participant quality vetting, handles payment for screen-outs
**Weaknesses:** Technical checks (device, browser, connection) must be done in your experiment

**Sources:** [Prolific Prescreening](https://researcher-help.prolific.com/en/article/58ef2f), [In-Study Screening](https://researcher-help.prolific.com/en/articles/445165-can-i-screen-participants-within-my-study)

### MTurk / CloudResearch

**Type:** Recruitment platform with qualification system
**Screening approach:** Qualifications (system + custom) and vetted participant lists

**Features:**
- System qualifications: HIT approval rate, # HITs approved, Masters status
- Custom qualifications with qualification tests
- CloudResearch Approved Participants (vetted for attention/engagement)
- Sentry: Pre-survey behavioral + technological vetting
- Suspicious geolocation blocking
- 50+ panel criteria for demographic targeting

**Strengths:** Experience-based qualifications (10K+ approved HITs), CloudResearch's patented vetting
**Weaknesses:** Custom qualifications require API (not in UI), qualification request system is broken

**Sources:** [MTurk Qualifications](https://docs.aws.amazon.com/AWSMechTurk/latest/AWSMechanicalTurkRequester/SelectingEligibleWorkers.html), [CloudResearch Data Quality](https://www.cloudresearch.com/resources/blog/new-tools-improve-research-data-quality-mturk/)

### jsPsych

**Type:** Experiment framework (JavaScript)
**Screening approach:** Browser-check plugin at experiment start

**Features:**
- Browser type and version detection
- Mobile device detection
- Screen size requirements with resize prompts
- WebAudio API support check
- Fullscreen API support check
- Display refresh rate measurement
- Webcam/microphone availability detection
- Custom inclusion_function for arbitrary logic
- Custom exclusion_message based on which criterion failed
- Interaction data recording (fullscreen exit, tab blur events)

**Strengths:** Well-designed plugin API, comprehensive browser feature detection
**Weaknesses:** Mid-experiment exclusion not supported (only at trial boundaries), mobile exclusion has known bugs on tablets

**Code pattern:**
```javascript
var trial = {
  type: jsPsychBrowserCheck,
  inclusion_function: (data) => {
    return data.browser == 'chrome' && data.mobile === false
  },
  exclusion_message: (data) => {
    if(data.mobile){
      return '<p>You must use a desktop/laptop computer.</p>';
    } else if(data.browser !== 'chrome'){
      return '<p>You must use Chrome.</p>'
    }
  }
};
```

**Sources:** [jsPsych Browser Check Plugin](https://www.jspsych.org/v7/plugins/browser-check/), [Browser Device Support](https://www.jspsych.org/v8/overview/browser-device-support/)

### oTree

**Type:** Experiment framework (Python, focused on economics/game theory)
**Screening approach:** Timeout-based dropout detection, consent-based filtering

**Features:**
- Activity detection: participants asked "are you still there?" after inactivity
- Tab-switching detection: excludes participants who switch tabs on wait pages
- Timeout-based dropout marking (timeout_happened flag)
- Consent app filtering with group_by_arrival_time
- Participant labels for duplicate participation prevention
- PARTICIPANT_FIELDS for storing screening data across apps

**Multiplayer dropout handling (third-party):**
- Dynamically reduces timeouts to 1 second when dropout detected
- Time-limited group matching (create single-player group if match timeout)
- Reduces wait time from 90+ seconds to ~32 seconds

**Strengths:** Built for multiplayer economics experiments, good dropout handling patterns
**Weaknesses:** Page-based checking (not continuous), no real-time game support

**Sources:** [oTree Wait Pages](https://otree.readthedocs.io/en/latest/multiplayer/waitpages.html), [oTree Dropout Handling](https://github.com/chkgk/dropout_handling)

### Gorilla Experiment Builder

**Type:** No-code experiment builder (web-based)
**Screening approach:** Recruitment requirements + experiment tree reject nodes

**Features:**
- Device type restrictions (mobile/tablet/desktop)
- Browser type restrictions
- Location restrictions
- Connection speed restrictions
- Reject nodes in experiment tree for early screening
- Rejection statuses: Rejected, RejectedManual, RejectedTimeLimit, RejectedQuality, RejectedOverQuota
- Custom eligibility questions with branching

**Strengths:** Visual experiment builder, granular rejection status tracking
**Weaknesses:** Device spoofing (iPads identifying as computers) requires additional verification

**Sources:** [Gorilla Recruitment Requirements](https://support.gorilla.sc/support/launching-your-study/recruitment-requirements)

### Pavlovia

**Type:** Experiment hosting platform (PsychoPy/jsPsych/lab.js)
**Screening approach:** Inherits from experiment framework used

**Features:**
- Automatically saves frame rate and OS
- Touch screen support via Mouse component
- Integrates with Prolific screening
- URL parameters for condition assignment
- Git-based project management

**Strengths:** Supports multiple experiment frameworks, good PsychoPy integration
**Weaknesses:** No built-in screening; relies on underlying framework (jsPsych, etc.)

**Sources:** [Pavlovia Integration](https://researcher-help.prolific.com/en/articles/445190-pavlovia-integration-guide)

### SONA Systems

**Type:** University participant pool management
**Screening approach:** Prescreen questionnaire with eligibility restrictions

**Features:**
- Custom prescreen questionnaires
- Restrictions based on single items or computed scores
- Multiple criteria with logical AND
- Real-time participant count for restrictions
- Per-study restriction settings
- Opt-out options for sensitive questions

**Strengths:** Designed for university subject pools, handles course credit
**Weaknesses:** Limited to demographics/questionnaire data, no technical checks

**Sources:** [SONA Prescreen Restrictions](https://www.sona-systems.com/researcher/prescreen-participation-restrictions/)

## Feature Dependencies

```
Pre-experiment (before game starts):
  Consent → Browser Check → Connection Quality Check → Entry Allowed

Entry checks:
  ├── Device type (mobile/desktop)
  ├── Browser type/version
  ├── Screen size
  ├── WebRTC support
  └── Connection quality (ping test)

Continuous monitoring (during game):
  ├── Inactivity detection → Exclusion trigger
  ├── Connection quality degradation → Exclusion trigger
  ├── Tab visibility → Warning/Exclusion trigger
  └── Fullscreen exit → Warning/Recovery prompt

Multiplayer coordination:
  Player A excluded → Notify Player B → End game for both → Collect partial data
```

## Recommendations for Interactive Gym

### Phase 1: Entry Screening (Table Stakes)

**Priority: HIGH** — Without these, researchers won't trust data quality

1. **Device type detection** — Exclude mobile unless explicitly allowed
2. **Browser check** — Require WebRTC-capable browsers (Chrome, Firefox, Edge)
3. **Screen size minimum** — Configurable per experiment
4. **Configurable rejection messages** — Each rule has its own message

### Phase 2: Connection Quality (Differentiator)

**Priority: HIGH** — This is where Interactive Gym can excel

1. **Ping threshold check at entry** — "Your connection is too slow for this experiment"
2. **Connection type detection** — Already exists; expose as exclusion criterion
3. **Continuous latency monitoring** — Exclude if ping degrades past threshold
4. **Packet loss detection** — WebRTC stats API provides this

### Phase 3: Behavior Monitoring (Differentiator)

**Priority: MEDIUM** — Important for data quality, complex to implement

1. **Inactivity detection** — No inputs for N seconds triggers warning, then exclusion
2. **Tab visibility monitoring** — Record or warn on tab switches
3. **Disconnect pattern detection** — Multiple reconnects may indicate unstable environment

### Phase 4: Multiplayer Coordination (Critical Differentiator)

**Priority: HIGH** — No other platform does this well

1. **Partner notification on exclusion** — "Your partner has been disconnected"
2. **Clean game termination** — Save partial data, record exclusion reason
3. **Exclusion propagation** — Both players see appropriate message
4. **Partial data handling** — Don't discard valid data before exclusion

### Architecture Recommendation

```
ExclusionRule interface:
  - name: string
  - checkAtEntry: boolean
  - checkContinuously: boolean
  - check(context): { passed: boolean, reason?: string }
  - getMessage(): string

Built-in rules:
  - PingThresholdRule(maxPing: number)
  - BrowserRequirementRule(allowed: string[])
  - ScreenSizeRule(minWidth: number, minHeight: number)
  - InactivityRule(timeoutSeconds: number)
  - DeviceTypeRule(allowMobile: boolean)

Custom rules:
  - CustomCallbackRule(fn: (context) => { passed, reason })

Exclusion flow:
  1. Entry: Run all checkAtEntry rules
  2. Game loop: Run all checkContinuously rules each tick (or interval)
  3. Exclusion: Stop game, notify all players, collect partial data
```

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| Platform capabilities | HIGH | Verified with official documentation for jsPsych, oTree, Gorilla, Prolific |
| Attention check research | MEDIUM | Academic literature reviewed, but recommendations still evolving |
| Multiplayer dropout patterns | MEDIUM | oTree patterns verified; real-time game scenarios less documented |
| Connection quality thresholds | LOW | Gaming industry has standards (50-100ms acceptable), but research experiments may differ |

## Open Questions

1. **What ping threshold makes data invalid?** Gaming suggests >100ms is problematic, but research experiments may have different tolerances
2. **Should inactivity warning precede exclusion?** Prolific policy requires warning before rejection in some cases
3. **How to handle "border" cases?** Participant with 95ms ping when threshold is 100ms — binary or gradual?
4. **Partial data retention policy?** If participant excluded at minute 3 of 5, is that data usable?

## Sources

### Recruitment Platforms
- [Prolific Prescreening](https://researcher-help.prolific.com/en/article/58ef2f)
- [Prolific In-Study Screening](https://researcher-help.prolific.com/en/articles/445165-can-i-screen-participants-within-my-study)
- [Prolific Attention Check Policy](https://researcher-help.prolific.com/en/articles/445153-prolific-s-attention-and-comprehension-check-policy)
- [MTurk Qualification Requirements](https://docs.aws.amazon.com/AWSMechTurk/latest/AWSMturkAPI/ApiReference_QualificationRequirementDataStructureArticle.html)
- [CloudResearch Data Quality](https://www.cloudresearch.com/resources/blog/new-tools-improve-research-data-quality-mturk/)
- [SONA Prescreen Restrictions](https://www.sona-systems.com/researcher/prescreen-participation-restrictions/)

### Experiment Frameworks
- [jsPsych Browser Check Plugin](https://www.jspsych.org/v7/plugins/browser-check/)
- [jsPsych Browser Device Support](https://www.jspsych.org/v8/overview/browser-device-support/)
- [jsPsych Fullscreen Plugin](https://www.jspsych.org/v7/plugins/fullscreen/)
- [oTree Wait Pages](https://otree.readthedocs.io/en/latest/multiplayer/waitpages.html)
- [oTree Dropout Handling (third-party)](https://github.com/chkgk/dropout_handling)
- [Gorilla Recruitment Requirements](https://support.gorilla.sc/support/launching-your-study/recruitment-requirements)
- [Pavlovia Integration Guide](https://researcher-help.prolific.com/en/articles/445190-pavlovia-integration-guide)

### Research Literature
- [Attention Checks Review and Recommendations](https://www.researchgate.net/publication/376340288_Attention_checks_and_how_to_use_them_Review_and_practical_recommendations)
- [Statistical Analysis of Studies with Attention Checks (2025)](https://journals.sagepub.com/doi/full/10.1177/25152459251338041)
- [Reducing Dropouts in Online Experiments](https://www.playstudies.com/reducing-dropouts-in-online-experiments/)
- [Dropout Analysis R Package](https://link.springer.com/article/10.3758/s13428-025-02730-2)

### Technical References
- [Ping and Latency in Gaming](https://www.bandwidthplace.com/article/ping-latency-in-gaming)
- [Chrome Idle Detection API](https://developer.chrome.com/docs/capabilities/web-apis/idle-detection)
- [Browser Fingerprinting Survey](https://www.researchgate.net/publication/332873650_Browser_Fingerprinting_A_survey)
