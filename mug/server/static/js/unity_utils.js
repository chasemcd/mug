export function startUnityScene(data) {
    $("#sceneHeader").show();
    $("#sceneSubHeader").show();
    $("#sceneBody").show();
    $("#hudText").show();

    // Insert Unity WebGL container and loader elements
    startUnityGame(data, "gameContainer");

    $("#gameContainer").show();


    $("#advanceButton").attr("disabled", true);
    $("#advanceButton").hide();

    if (data.scene_header) {
        $("#sceneHeader").show().html(data.scene_header);
    } else {
        $("#sceneHeader").hide();
    }
    if (data.scene_subheader) {
        $("#sceneSubHeader").show().html(data.scene_subheader);
    } else {
        $("#sceneSubHeader").hide();
    }
    if (data.scene_body) {
        $("#sceneBody").show().html(data.scene_body);
    } else {
        $("#sceneBody").hide();
    }


    // Initialize or increment the gym scene counter
    if (typeof window.interactiveGymGlobals === 'undefined') {
        window.interactiveGymGlobals = {};
    }

    window.interactiveGymGlobals.unityEpisodeCounter = 0;
    window.interactiveGymGlobals.unityScore = null;
    if (data.score !== null) {
        window.interactiveGymGlobals.unityScore = 0;
    }
    console.log(window.interactiveGymGlobals.unityScore);

    let hudText = '';
    if (data.num_episodes && data.num_episodes > 1) {
        hudText += `Round ${window.interactiveGymGlobals.unityEpisodeCounter + 1}/${data.num_episodes}`;
    }

    if (window.interactiveGymGlobals.unityScore !== null) {
        if (hudText) hudText += ' | ';
        hudText += `Score: ${window.interactiveGymGlobals.unityScore}`;
    }

    $("#hudText").html(hudText);

}



window.unityInstance = null; // Store Unity instance globally

// Store preload promises and instances for different builds
const unityPreloads = new Map(); // Map of build_name -> { promise, instance }

// Keep track of cached assets
const unityCachedAssets = new Map(); // Map of build_name -> {data, framework, wasm}

export function preloadUnityGame(config) {
    console.log("Preloading Unity game assets", config);
    const buildName = config.build_name;

    // Return existing cache if already downloaded
    if (unityCachedAssets.has(buildName)) {
        console.log(`Assets for ${buildName} already cached`);
        return Promise.resolve(unityCachedAssets.get(buildName));
    }

    const buildUrl = `static/web_gl/${buildName}/Build`;

    // Create promises for all asset downloads
    const assetPromises = {
        loader: fetch(buildUrl + `/${buildName}.loader.js`).then(r => r.blob()),
        data: fetch(buildUrl + `/${buildName}.data`).then(r => r.blob()),
        framework: fetch(buildUrl + `/${buildName}.framework.js`).then(r => r.blob()),
        wasm: fetch(buildUrl + `/${buildName}.wasm`).then(r => r.blob())
    };

    // Download all assets in parallel
    return Promise.all(Object.values(assetPromises))
        .then(([loaderBlob, dataBlob, frameworkBlob, wasmBlob]) => {
            // Create object URLs for the assets
            const cachedAssets = {
                loaderUrl: URL.createObjectURL(loaderBlob),
                dataUrl: URL.createObjectURL(dataBlob),
                frameworkUrl: URL.createObjectURL(frameworkBlob),
                codeUrl: URL.createObjectURL(wasmBlob),
                buildName: buildName
            };

            // Store in cache
            unityCachedAssets.set(buildName, cachedAssets);
            console.log(`Assets for ${buildName} cached successfully`);

            return cachedAssets;
        })
        .catch(error => {
            console.error(`Failed to preload ${buildName}:`, error);
            throw error;
        });
}

// Modified startUnityGame to use cached assets
function startUnityGame(config, elementId) {
    const buildName = config.build_name;
    const cachedAssets = unityCachedAssets.get(buildName);

    if (!cachedAssets) {
        console.error(`No cached assets found for ${buildName}. Call preloadUnityGame() first.`);
        return;
    }

    console.log(`Starting Unity game with cached assets: ${buildName}`);

    $(`#${elementId}`).html(`
        <div id="unity-container" class="unity-desktop">
            <canvas id="unity-canvas" tabindex="-1"></canvas>
            <div id="unity-loading-bar">
                <div id="unity-logo"></div>
                <div id="unity-progress-bar-empty">
                    <div id="unity-progress-bar-full"></div>
                </div>
            </div>
            <div id="unity-warning"> </div>
            <div id="unity-footer">
                <div id="unity-webgl-logo"></div>
                <div id="unity-fullscreen-button"></div>
            </div>
        </div>`);

    const canvas = document.querySelector("#unity-canvas");
    const loadingBar = document.querySelector("#unity-loading-bar");
    const progressBarFull = document.querySelector("#unity-progress-bar-full");
    const fullscreenButton = document.querySelector("#unity-fullscreen-button");

    if (/iPhone|iPad|iPod|Android/i.test(navigator.userAgent)) {
        canvas.className = "unity-mobile";
    } else {
        canvas.style.width = `${config.width}px`;
        canvas.style.height = `${config.height}px`;
    }

    const unityConfig = {
        dataUrl: cachedAssets.dataUrl,
        frameworkUrl: cachedAssets.frameworkUrl,
        codeUrl: cachedAssets.codeUrl,
        streamingAssetsUrl: "StreamingAssets",
        companyName: "DefaultCompany",
        productName: buildName,
        productVersion: "1.0",
    };

    loadingBar.style.display = "block";

    const script = document.createElement("script");
    script.src = cachedAssets.loaderUrl;
    script.onload = () => {
        createUnityInstance(canvas, unityConfig, (progress) => {
            progressBarFull.style.width = 100 * progress + "%";
        }).then((instance) => {
            window.unityInstance = instance;
            loadingBar.style.display = "none";
            fullscreenButton.onclick = () => {
                window.unityInstance.SetFullscreen(1);
            };
        }).catch((message) => {
            alert(message);
        });
    };

    document.body.appendChild(script);
}

export function shutdownUnityGame() {
    if (window.unityInstance) {
        try {
            // First remove any event listeners and disable the fullscreen button
            const fullscreenButton = document.querySelector("#unity-fullscreen-button");
            if (fullscreenButton) {
                fullscreenButton.onclick = null;
            }

            // Attempt to quit the Unity instance with a timeout
            const quitPromise = window.unityInstance.Quit();
            const timeoutPromise = new Promise((_, reject) =>
                setTimeout(() => reject(new Error('Unity quit timeout')), 5000));

            Promise.race([quitPromise, timeoutPromise])
                .then(() => {
                    cleanupUnityResources();
                })
                .catch((e) => {
                    console.warn("Error or timeout shutting down Unity instance:", e);
                    cleanupUnityResources();
                });
        } catch (e) {
            console.warn("Error during Unity shutdown:", e);
            cleanupUnityResources();
        }
    }
}

function cleanupUnityResources() {
    // Clear the Unity instance
    window.unityInstance = null;

    // Force garbage collection if possible
    if (window.gc) {
        window.gc();
    }

    console.log("Unity WebGL cleanup completed");
}

export function terminateUnityScene(data) {
  // In the Static and Start scenes, we only show
  // the advanceButton, sceneHeader, and sceneBody
  $("#sceneHeader").show();
  $("#sceneSubHeader").show();

  $("#sceneBody").show();

  $("#advanceButton").attr("disabled", false);
  $("#advanceButton").show();

  $("#sceneHeader").html(data.scene_header);
  $("#sceneSubHeader").html(data.scene_subheader);
  $("#sceneBody").html(data.scene_body);

};
