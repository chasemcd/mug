/**
 * Seeded Random Number Generator for Multiplayer Synchronization
 *
 * Uses Mulberry32 algorithm - fast, high-quality PRNG suitable for games.
 * All clients with same seed will generate identical random sequences.
 *
 * Reference: https://github.com/bryc/code/blob/master/jshash/PRNGs.md
 */

export class SeededRandom {
    constructor(seed) {
        // Ensure seed is a 32-bit unsigned integer
        this.seed = seed >>> 0;
        this.originalSeed = this.seed;
    }

    /**
     * Generate next random float in range [0, 1)
     * Mulberry32 algorithm - one of the fastest high-quality PRNGs
     */
    random() {
        let t = this.seed += 0x6D2B79F5;
        t = Math.imul(t ^ t >>> 15, t | 1);
        t ^= t + Math.imul(t ^ t >>> 7, t | 61);
        return ((t ^ t >>> 14) >>> 0) / 4294967296;
    }

    /**
     * Generate random integer in range [min, max)
     */
    randomInt(min, max) {
        return Math.floor(this.random() * (max - min)) + min;
    }

    /**
     * Reset to original seed (useful for episode resets)
     */
    reset() {
        this.seed = this.originalSeed;
    }

    /**
     * Get current seed state (for debugging/verification)
     */
    getState() {
        return this.seed;
    }
}

// Global singleton for multiplayer mode
let globalMultiplayerRNG = null;
let isMultiplayerMode = false;

/**
 * Initialize multiplayer RNG with shared seed
 * Must be called by all clients with same seed before game starts
 */
export function initMultiplayerRNG(seed) {
    globalMultiplayerRNG = new SeededRandom(seed);
    isMultiplayerMode = true;
    console.log(`[SeededRandom] Initialized with seed: ${seed}`);
}

/**
 * Disable multiplayer RNG (fall back to Math.random)
 */
export function disableMultiplayerRNG() {
    globalMultiplayerRNG = null;
    isMultiplayerMode = false;
    console.log(`[SeededRandom] Disabled, using Math.random()`);
}

/**
 * Get random value - uses seeded RNG in multiplayer, Math.random() otherwise
 */
export function getRandom() {
    return isMultiplayerMode ? globalMultiplayerRNG.random() : Math.random();
}

/**
 * Check if multiplayer mode is active
 */
export function isMultiplayer() {
    return isMultiplayerMode;
}

/**
 * Reset RNG to original seed (for episode boundaries)
 */
export function resetMultiplayerRNG() {
    if (globalMultiplayerRNG) {
        globalMultiplayerRNG.reset();
        console.log(`[SeededRandom] Reset to original seed`);
    }
}

/**
 * Get RNG state for debugging
 */
export function getRNGState() {
    return globalMultiplayerRNG ? globalMultiplayerRNG.getState() : null;
}
