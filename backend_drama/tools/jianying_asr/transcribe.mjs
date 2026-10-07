#!/usr/bin/env node
/**
 * JianYing ASR bridge for backend_drama.
 *
 * Usage:
 *   node transcribe.mjs --input /path/source.mp4 --out /path/source.srt [--timeout-ms 600000]
 *
 * Uses the jianying-subtitle library API (not the CLI) so progress and
 * errors stay machine-readable. Prints exactly one JSON line to stdout:
 *   {"ok":true,"cues":N,"duration_ms":M,"srt_path":"...","asr_seconds":S}
 * or on failure:
 *   {"ok":false,"code":"...","message":"..."}
 * Progress goes to stderr as JSON lines (never parsed as result).
 *
 * Exit codes: 0 ok, 1 usage, 2 install/import, 3 upload, 4 asr, 5 timeout,
 * 6 invalid output, 7 unsupported language.
 */
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--input") out.input = argv[++i];
    else if (a === "--out") out.out = argv[++i];
    else if (a === "--timeout-ms") out.timeoutMs = Number(argv[++i]);
  }
  return out;
}

function fail(code, message, exitCode) {
  process.stdout.write(JSON.stringify({ ok: false, code, message }) + "\n");
  process.exit(exitCode);
}

const args = parseArgs(process.argv);
if (!args.input || !args.out) {
  console.error("usage: transcribe.mjs --input <media> --out <file.srt> [--timeout-ms N]");
  process.exit(1);
}
if (!fs.existsSync(args.input)) fail("INPUT_MISSING", `input not found: ${args.input}`, 1);
const timeoutMs = Number.isFinite(args.timeoutMs) && args.timeoutMs > 0 ? args.timeoutMs : 600000;

let lib;
try {
  lib = await import("jianying-subtitle");
} catch (e) {
  fail("JIANYING_INSTALL_FAILED", `cannot import jianying-subtitle: ${e?.message || e}`, 2);
}
const { transcribe, toSrt } = lib;
if (typeof transcribe !== "function" || typeof toSrt !== "function") {
  fail("JIANYING_INSTALL_FAILED", "jianying-subtitle API mismatch (need transcribe/toSrt)", 2);
}

const started = Date.now();
const deadline = setTimeout(() => {
  fail("JIANYING_TIMEOUT", `ASR exceeded ${timeoutMs}ms`, 5);
}, timeoutMs + 30000);

// transcribe() takes audio only: extract the audio track first.
// AAC source -> stream-copy to .m4a (instant, lossless); otherwise WAV.
function extractAudio(videoPath) {
  const dir = path.dirname(videoPath);
  const base = path.basename(videoPath, path.extname(videoPath));
  for (const [ext, extra] of [[".m4a", ["-c:a", "copy"]], [".wav", []]]) {
    const out = path.join(dir, `${base}.extracted${ext}`);
    try {
      execFileSync(
        "ffmpeg",
        ["-v", "error", "-y", "-i", videoPath, ...extra, out],
        { timeout: 120000 },
      );
      const st = fs.statSync(out);
      if (st.size > 0) return out;
      fs.rmSync(out, { force: true });
    } catch {
      // try next format
    }
  }
  return null;
}

let audioInput = args.input;
let extractedTmp = null;
if (!/\.(mp3|wav|flac|m4a)$/i.test(args.input)) {
  process.stderr.write(JSON.stringify({ progress: 1, message: "extracting audio" }) + "\n");
  extractedTmp = extractAudio(args.input);
  if (!extractedTmp) {
    clearTimeout(deadline);
    fail("JIANYING_UPLOAD_FAILED", "could not extract audio track", 3);
  }
  audioInput = extractedTmp;
}

let segments;
try {
  try {
    segments = await transcribe({
      input: audioInput,
      queryTimeoutMs: timeoutMs,
      onProgress: (percent, message) => {
        process.stderr.write(JSON.stringify({ progress: percent, message }) + "\n");
      },
    });
  } finally {
    if (extractedTmp) fs.rmSync(extractedTmp, { force: true });
  }
} catch (e) {
  const msg = e?.message || String(e);
  clearTimeout(deadline);
  if (/upload/i.test(msg)) fail("JIANYING_UPLOAD_FAILED", msg.slice(0, 500), 3);
  fail("JIANYING_ASR_FAILED", msg.slice(0, 500), 4);
}
clearTimeout(deadline);

if (!Array.isArray(segments) || segments.length === 0) {
  fail("ASR_INVALID_SRT", "ASR returned zero segments", 6);
}

let srt;
try {
  srt = toSrt(segments);
} catch (e) {
  fail("ASR_INVALID_SRT", `toSrt failed: ${e?.message || e}`, 6);
}
if (typeof srt !== "string" || !srt.trim()) {
  fail("ASR_INVALID_SRT", "empty SRT output", 6);
}
fs.writeFileSync(args.out, srt, "utf8");

const asrSeconds = (Date.now() - started) / 1000;
process.stdout.write(JSON.stringify({
  ok: true,
  cues: segments.length,
  duration_ms: Math.max(0, ...segments.map((s) => s?.endMs ?? s?.end_ms ?? 0)),
  srt_path: args.out,
  asr_seconds: Math.round(asrSeconds * 10) / 10,
}) + "\n");
process.exit(0);
