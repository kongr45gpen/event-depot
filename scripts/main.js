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
    
function updateDomWithPollData(data) {
    try {
        if (!data) {
            throw new Error("No data provided to updateDomWithPollData");
        }

        const event = data.payload.eventNow;

        if (event.title) {
            setTextAnimated($title, params_titleOverride, event.title);
        } else {
            setTextAnimated($title, params_titleOverride, "");
        }


        if (event.custom && event.custom.Speakers) {
            setTextAnimated($speaker, params_speakerOverride, event.custom.Speakers);
        } else {
            setTextAnimated($speaker, params_speakerOverride, "");
        }
    } catch (err) {
        console.error("Failed to update DOM with poll data:", err);
    }
}

(function () {
    gsap.registerPlugin(TextPlugin);
})();