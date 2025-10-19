const params = new URLSearchParams(window.location.search);

const params_titleOverride = params.get("title");
const params_speakerOverride = params.get("speaker");

const $title = document.getElementById("title");
const $speaker = document.getElementById("speaker");

async function pollOnTime() {
    try {
        let url = params.get("ontime");

        if (!url) {
            return;
        }

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

(function () {
    gsap.registerPlugin(TextPlugin);
})();