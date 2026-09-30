// We import the fs module (promise-based API) so we can read/write the log files
// without blocking the event loop. mkdirSync is used once at startup.
const fs = require("fs/promises");
const { mkdirSync } = require("fs");
const path = require("path");
const express = require("express");

// Create the express app.
const app = express();

/* Parse request bodies as JSON. We set `type` to accept every content type so
that clients sending `requests.post(..., data=json.dumps({...}))` work even
though that call doesn't set a JSON content-type header. */
app.use(express.json({ type: () => true }));

// The port is configurable via the PORT environment variable and defaults to 8080.
const port = process.env.PORT || 8080;

// Log files live in a dedicated logs/ directory. Absolute paths so behaviour
// doesn't depend on the current working directory.
const LOG_DIR = path.join(__dirname, "logs");
const TEXT_LOG = path.join(LOG_DIR, "text_logs.txt");
const RAW_LOG = path.join(LOG_DIR, "raw_logs.txt");

// Create the logs directory at startup if it doesn't already exist.
mkdirSync(LOG_DIR, { recursive: true });

// Escape a handful of characters so that data stored in a log file is shown as
// text and cannot inject markup into the response we render.
function escapeHtml(value) {
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

// Read a log file, returning null if it doesn't exist yet.
async function readLog(file) {
    try {
        return await fs.readFile(file, { encoding: "utf8" });
    } catch (err) {
        if (err.code === "ENOENT") {
            return null;
        }
        throw err;
    }
}

// When a GET request is made to "/" we show the contents of both log files.
app.get("/", async (req, res) => {
    try {
        const [text, raw] = await Promise.all([readLog(TEXT_LOG), readLog(RAW_LOG)]);
        const section = (label, contents) => {
            if (contents === null) {
                return `<h2>${label}</h2><p>Nothing logged yet.</p>`;
            }
            const safe = escapeHtml(contents).replace(/\n/g, "<br>");
            return `<h2>${label}</h2><p>${safe}</p>`;
        };
        res.send(
            `<h1>Logged data</h1>${section("Text data", text)}${section("Raw data", raw)}`
        );
    } catch (err) {
        console.error("Failed to read log file:", err);
        res.status(500).send("<h1>Could not read the log.</h1>");
    }
});

/* Build a POST handler that reads `field` from the JSON body and overwrites
`file` with it. Returns 400 if the field is missing or not a string. */
function makeLogHandler(field, file) {
    return async (req, res) => {
        const value = (req.body || {})[field];
        if (typeof value !== "string") {
            return res
                .status(400)
                .send(`Request body must be JSON with a string "${field}" field.`);
        }
        try {
            // Overwrite the file on every request so it only holds the latest data.
            await fs.writeFile(file, `${value}\n`);
            res.send("Successfully set the data");
        } catch (err) {
            console.error("Failed to write log file:", err);
            res.status(500).send("Could not write the data.");
        }
    };
}

// Two separate endpoints, each with its own field name and log file.
app.post("/text", makeLogHandler("textData", TEXT_LOG));
app.post("/raw", makeLogHandler("rawData", RAW_LOG));

// Handle bodies that aren't valid JSON with a clear 400 instead of a stack trace.
app.use((err, req, res, next) => {
    if (err && err.type === "entity.parse.failed") {
        return res.status(400).send("Request body must be valid JSON.");
    }
    next(err);
});

// Start the server and report the port it's listening on.
app.listen(port, () => {
    console.log(`App is listening on port ${port}`);
});
