## now_then.html

### HTML parameters

- `ontime`: Provide a URL to an OnTime instance to update parameters live (e.g. `https://10.10.10.10:4001`)

- `interval`: Polling interval (in ms) used for remote lookups

- `title`: Override the title shown in the header

- `speaker`: Override the speaker shown in the header

- `hidebar`: Hides the right sidebar and its content

- `winmusic`: URL to POST to for current music metadata. The page will POST to this URL and display the returned fields in the "Now Playing" block.
	- Example: `?winmusic=http://127.0.0.1:5000/nowplaying`

- `winmusic-interval`: Override `interval` for winmusic

## streaming.html

### HTML parameters

- `ontime`: Provide a URL to an OnTime instance to update parameters live (e.g. `https://10.10.10.10:4001`)


- `noboxes`: Disables the small boxes

- `big_box`: Override big box size (0 - 1)

- `big_box_aspect_ratio`: Override big box aspect ratio (e.g. 1.3334 or 1.7778)

- `boxes`: Comma-separated list or JSON describing the mini boxes; format expected by the JS `setBoxes()` function ([x,y,size,maskTop,maskBottom,maskLeft,maskRight]).

- `big_box_x` / `big_box_y`: Numeric offsets to shift the big box's position horizontally/vertically (BMD considers one unit of space to be 60 pixels, so for 1080p: X: -32..32, Y: -18..18).
