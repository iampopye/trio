#!/usr/bin/env node
// Best-effort postinstall: try to pre-install triobot so the first `trio` run is fast.
// This NEVER fails the npm install — if Python or pip is missing, the bin launcher
// handles it at runtime with a clearer message.
//
// Copyright (c) 2026 Karan Garg. Licensed under MIT.

"use strict";

const { spawnSync } = require("child_process");

// Skip in CI / when explicitly disabled.
if (process.env.TRIO_SKIP_POSTINSTALL === "1") {
  process.exit(0);
}

function quiet(cmd, args) {
  try {
    return spawnSync(cmd, args, { encoding: "utf8", windowsHide: true });
  } catch (_) {
    return { status: 1 };
  }
}

function findPython() {
  const candidates =
    process.platform === "win32"
      ? [["py", "-3"], ["python"], ["python3"]]
      : [["python3"], ["python"]];
  const probe = "import sys;print(sys.version_info[0]*100+sys.version_info[1])";
  for (const cand of candidates) {
    const [exe, ...pre] = cand;
    const r = quiet(exe, [...pre, "-c", probe]);
    if (r.status === 0 && parseInt(String(r.stdout).trim(), 10) >= 310) return cand;
  }
  return null;
}

const py = findPython();
if (!py) {
  process.stderr.write(
    "[trio] Note: Python 3.10+ not found yet. It will be needed the first time you run `trio`.\n"
  );
  process.exit(0);
}

const [exe, ...pre] = py;
if (quiet(exe, [...pre, "-m", "pip", "show", "triobot"]).status !== 0) {
  process.stderr.write("[trio] Pre-installing triobot...\n");
  spawnSync(exe, [...pre, "-m", "pip", "install", "--upgrade", "triobot"], {
    stdio: "inherit",
    windowsHide: true,
  });
}

process.exit(0);
