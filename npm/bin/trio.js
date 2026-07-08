#!/usr/bin/env node
// trio.ai npm launcher — bootstraps Python + triobot and forwards to `python -m trio`.
// trio is a Python application; this wrapper gives it an `npm install -g trio-ai` /
// `npx trio-ai` install path. It does NOT reimplement trio in Node — it locates a
// compatible Python, ensures the `triobot` package is installed, then execs the CLI.
//
// Copyright (c) 2026 Karan Garg. Licensed under MIT.

"use strict";

const { spawnSync } = require("child_process");

const MIN_MAJOR = 3;
const MIN_MINOR = 10;
const PKG = "triobot";

function quiet(cmd, args) {
  try {
    return spawnSync(cmd, args, { encoding: "utf8", windowsHide: true });
  } catch (_) {
    return { status: 1, stdout: "", stderr: "" };
  }
}

// Return an argv array [exe, ...preArgs] for a Python >= 3.10, or null.
// Honors the TRIO_PYTHON env var (e.g. a venv interpreter) if it points at a
// compatible Python.
function findPython() {
  const probe = "import sys;print(sys.version_info[0]*100+sys.version_info[1])";

  const forced = (process.env.TRIO_PYTHON || "").trim();
  const candidates = forced
    ? [forced.split(/\s+/)]
    : process.platform === "win32"
    ? [["py", "-3"], ["python"], ["python3"]]
    : [["python3"], ["python"]];

  for (const cand of candidates) {
    const [exe, ...pre] = cand;
    const r = quiet(exe, [...pre, "-c", probe]);
    if (r.status === 0) {
      const v = parseInt(String(r.stdout).trim(), 10);
      if (!Number.isNaN(v) && v >= MIN_MAJOR * 100 + MIN_MINOR) return cand;
    }
  }
  return null;
}

function isPkgInstalled(py) {
  const [exe, ...pre] = py;
  return quiet(exe, [...pre, "-m", "pip", "show", PKG]).status === 0;
}

function installPkg(py) {
  const [exe, ...pre] = py;
  process.stderr.write(`[trio] Installing ${PKG} (first run, one time)...\n`);
  const r = spawnSync(exe, [...pre, "-m", "pip", "install", "--upgrade", PKG], {
    stdio: "inherit",
    windowsHide: true,
  });
  return r.status === 0;
}

function die(msg) {
  process.stderr.write(`\n[trio] ${msg}\n`);
  process.exit(1);
}

function main() {
  const py = findPython();
  if (!py) {
    die(
      `Python ${MIN_MAJOR}.${MIN_MINOR}+ is required but was not found.\n` +
        "        Install it from https://www.python.org/downloads/ and re-run.\n" +
        "        (trio.ai is a Python application; npm only launches it.)"
    );
  }

  if (!isPkgInstalled(py) && !installPkg(py)) {
    die(
      `Could not install ${PKG} automatically.\n` +
        `        Try manually:  ${py.join(" ")} -m pip install ${PKG}`
    );
  }

  const [exe, ...pre] = py;
  const child = spawnSync(exe, [...pre, "-m", "trio", ...process.argv.slice(2)], {
    stdio: "inherit",
    windowsHide: true,
  });
  process.exit(child.status === null ? 1 : child.status);
}

main();
