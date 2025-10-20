const params = new URLSearchParams(window.location.search);

const params_titleOverride = params.get("title");
const params_speakerOverride = params.get("speaker");

const $title = document.getElementById("title");
const $speaker = document.getElementById("speaker");

async function pollOnTime() {
    let url = params.get("ontime");

    if (!url) {
        $title.textContent = params_titleOverride ? params_titleOverride : "";
        $speaker.textContent = params_speakerOverride ? params_speakerOverride : "";
        throw new Error("OnTime URL parameter is missing");
    }

    try {
        url = new URL("/api/poll", url).href;

        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok) {
            console.error("OnTime poll returned HTTP error:", res.status, res.statusText);
            return;
        }
        let data;
        try {
            data = await res.json();
        } catch (err) {
            console.error("Failed to parse poll response as JSON:", err);
            return;
        }

        return data;
    } catch (err) {
        console.error("OnTime poll failed:", err);
        throw err;
    }
}

async function setTextAnimated(element, override, text) {
    if (!text) {
        text = "";
    }

    if (override) {
        text = override;
    }

    // Check current content of box and only update if is new
    if (element.textContent !== text) {
        await gsap.to(element, {
            text: text,
            duration: 0.4,
            ease: "none",
        });
    }
}

// Converts time from milliseconds to a "HH:MM" view
function convertTime(ms) {
    const date = new Date(ms);
    const hours = date.getHours().toString().padStart(2, "0");
    const minutes = date.getMinutes().toString().padStart(2, "0");
    return `${hours}:${minutes}`;
}

async function replaceSessionBlock($container, event) {
    try {
        // Create temporary copy of container
        const $temp = $container.cloneNode(true);

        const $title = $temp.querySelector(".session-title");
        const $speaker = $temp.querySelector(".session-speaker");
        const $time = $temp.querySelector(".session-time");

        if (!event) {
            $temp.style.display = "none";
        } else {
            $temp.style.display = "";

            if ($title) {
                $title.textContent = (event.title) ? event.title : "";
            }

            if ($speaker) {
                if (event.custom && event.custom.Speakers) {
                    $speaker.textContent = event.custom.Speakers;
                } else {
                    $speaker.textContent = "";
                }
            }

            if ($time) {
                let newtime = "";
                if (event.timeStart) {
                    newtime += convertTime(event.timeStart);
                }
                if (event.timeEnd) {
                    newtime += " - " + convertTime(event.timeEnd);
                }
                $time.textContent = newtime;
            }

        }

        const newHtml = $temp.innerHTML;

        if ($container.innerHTML === newHtml && $temp.style.display === $container.style.display) {
            return;
        }

        const originalOpacity = window.getComputedStyle($container).opacity;

        gsap.to($container, {
            opacity: 0,
            duration: 0.2,
            height: 0,
            ease: "power2.inOut",
            onComplete() {
                $container.innerHTML = newHtml;
                $container.style.display = $temp.style.display;
                gsap.fromTo(
                    $container,
                    { opacity: 0, height: 0 },
                    { opacity: originalOpacity, height: "auto", duration: 0.2, ease: "none" }
                );
            }
        });

    } catch (err) {
        console.error("Failed to replace session block:", err);
        return;
    }
}


function updateDomWithPollData(data) {
    try {
        if (!data) {
            throw new Error("No data provided to updateDomWithPollData");
        }

        const event = data.payload.publicEventNow;
        const nextEvent = data.payload.publicEventNext;

        const $now = document.getElementById("now");
        const $next = document.getElementById("next");

        if ($title) {
            if (event.title) {
                setTextAnimated($title, params_titleOverride, event.title);
            } else {
                setTextAnimated($title, params_titleOverride, "");
            }
        }

        if ($speaker) {
            if (event.custom && event.custom.Speakers) {
                setTextAnimated($speaker, params_speakerOverride, event.custom.Speakers);
            } else {
                setTextAnimated($speaker, params_speakerOverride, "");
            }
        }

        if ($now) {
            replaceSessionBlock($now, event);
        }

        if ($next) {
            replaceSessionBlock($next, nextEvent);
        }
    } catch (err) {
        console.error("Failed to update DOM with poll data:", err);
    }
}

function setupOntimePoll() {
    const intervalMs = params.has("interval") ? parseInt(params.get("interval"), 10) : 5000;

    pollOnTime().then((data) => {
        console.log("Initial ontime data fetch:", data);
        updateDomWithPollData(data);
    }).catch((err) => { });

    setInterval(() => {
        pollOnTime().then((data) => {
            updateDomWithPollData(data);
        }).catch((err) => { });
    }, intervalMs);
}

(function () {
    gsap.registerPlugin(TextPlugin);
})();

function areDictsRoughlyEqual(arr1, arr2, epsilon = 0.05) {
    let properties_equal;

    try {
        const propToFloat = s => (typeof s === 'string' && s.trim().length > 2) ? parseFloat(s.trim().slice(0, -2)) : NaN;

        const keysBox = Object.keys(arr2);
        const oldNumsBox = _.map(keysBox, k => propToFloat(arr1[k]));
        const newNumsBox = _.map(keysBox, k => propToFloat(arr2[k]));

        const zip = rows => rows[0].map((_, c) => rows.map(row => row[c]));
        properties_equal = _.every(zip([oldNumsBox, newNumsBox]), pair => Math.abs(pair[0] - pair[1]) <= epsilon);
    } catch (e) {
        console.warn(e);
        properties_equal = _.isEqual(arr1, arr2);
    }

    return properties_equal;
}

function setBoxes(data, animate = false) {
    const ANIMATION_DURATION = 0.5;

    if (data.big_box) {
        const $bigBox = document.getElementById('big-box');

        const old_properties = {
            width: $bigBox.style.width,
            height: $bigBox.style.height,
            marginLeft: $bigBox.style.marginLeft,
            marginTop: $bigBox.style.marginTop,
            opacity: $bigBox.style.opacity + '00',
        };

        const new_properties = {
            width: 100.0 * data.big_box * data.big_box_aspect_ratio + 'vh',
            height: 100.0 * data.big_box + 'vh',
            marginTop: (data.big_box_y) ? 100.0 * (- data.big_box_y) / 18.0 + 'vh' : '0vh',
            marginLeft: (data.big_box_x) ? 100.0 * data.big_box_x / 32.0 + 'vw' : '0vw',
            opacity: 100,
        };

        let properties_equal = areDictsRoughlyEqual(old_properties, new_properties);
        const box_invisible = (data.big_box <= 0.01 || data.big_box == null || data.big_box >= 9.999);

        console.log(
            `Updating big box: old_properties=${JSON.stringify(old_properties)}, new_properties=${JSON.stringify(new_properties)}, ` +
            `properties_equal=${properties_equal}, box_invisible=${box_invisible}, animate=${animate}`
        )

        if (animate && !properties_equal) {
            gsap.to($bigBox.style, {
                opacity: 0,
                duration: ANIMATION_DURATION / 2,
                ease: "power2.inOut",
                onComplete() {
                    if (!box_invisible) {
                        $bigBox.style.width = new_properties.width;
                        $bigBox.style.height = new_properties.height;
                        $bigBox.style.marginLeft = new_properties.marginLeft;
                        $bigBox.style.marginTop = new_properties.marginTop;

                        gsap.to($bigBox.style, {
                            opacity: 1,
                            duration: ANIMATION_DURATION / 2,
                            ease: "power2.inOut",
                        });
                    }
                }
            });
        } else {
            $bigBox.style.width = new_properties.width;
            $bigBox.style.height = new_properties.height;
            $bigBox.style.marginLeft = new_properties.marginLeft;
            $bigBox.style.marginTop = new_properties.marginTop;

            if (box_invisible) {
                $bigBox.style.opacity = 0;
            } else {
                $bigBox.style.opacity = 1;
            }
        }
    }

    // ATEM box parameters
    // Position: X from -32 to 32 (0 means center at center)
    // Position: Y from -18 to 18 (0 means center at center)
    // Size: from 0 to 1
    //
    // Crop:
    // Top-Bottom: 0-18
    // Left-Right: 0-32
    //
    // Application order: Crop -> Size -> Position

    let boxes = data.boxes;

    if (!boxes || boxes.length === 0 || boxes.length === undefined || boxes.length === null) {
        boxes = [];
    }

    boxes.forEach((params, index) => {
        const $box = document.getElementById(`box-${index + 1}`);

        console.log(`Updating box ${index + 1} with params:`, params);

        x = params[0];
        y = params[1];
        size = params[2];
        crop_top = params[3];
        crop_bottom = params[4];
        crop_left = params[5];
        crop_right = params[6];

        let left_edge_at = crop_left / 32.0 * size + (1 - size) / 2.0 + x / 32.0;
        let width = size - (crop_left + crop_right) / 32.0 * size;

        let top_edge_at = crop_top / 18.0 * size + (1 - size) / 2.0 - y / 18.0;
        let height = size - (crop_top + crop_bottom) / 18.0 * size;

        const old_properties = {
            left: $box.style.left,
            top: $box.style.top,
            width: $box.style.width,
            height: $box.style.height,
            opacity: $box.style.opacity + '00',
        };

        const new_properties = {
            left: (left_edge_at * 100).toFixed(4) + 'vw',
            top: (top_edge_at * 100).toFixed(4) + 'vh',
            width: (width - 0.002).toFixed(4) * 100 + 'vw',
            height: (height - 0.002).toFixed(4) * 100 + 'vh',
            opacity: '100',
        };

        let properties_equal = areDictsRoughlyEqual(old_properties, new_properties);
        const box_invisible = (size <= 0.01 || size == null || size >= 99.9);

        console.log(
            `Updating box ${index + 1}: properties_equal=${properties_equal}, box_invisible=${box_invisible}, animate=${animate}`
        )

        if (animate && !properties_equal) {
            gsap.to($box.style, {
                opacity: 0,
                duration: ANIMATION_DURATION / 2,
                ease: "power2.inOut",
                onComplete() {
                    if (!box_invisible) {
                        $box.style.left = new_properties.left;
                        $box.style.top = new_properties.top;
                        $box.style.width = new_properties.width;
                        $box.style.height = new_properties.height;

                        gsap.to($box.style, {
                            opacity: 1,
                            duration: ANIMATION_DURATION / 2,
                            ease: "power2.inOut",
                        });
                    }
                }
            });
        } else {
            $box.style.left = new_properties.left;
            $box.style.top = new_properties.top;
            $box.style.width = new_properties.width;
            $box.style.height = new_properties.height;
            if (box_invisible) {
                $box.style.opacity = 0;
            } else {
                $box.style.opacity = 1;
            }
        }


        const nld_properties = {
            left: $box.style.left,
            top: $box.style.top,
            width: $box.style.width,
            height: $box.style.height,
        };

    });


    if (data.boxes && data.boxes.length < 4) {
        for (let i = data.boxes.length; i < 4; i++) {
            const $box = document.getElementById(`box-${i + 1}`);
            if (animate) {
                gsap.to($box.style, {
                    opacity: 0,
                    duration: ANIMATION_DURATION / 2,
                    ease: "power2.inOut",
                });
            } else {
                $box.style.opacity = 0;
            }
        }
    }
}
