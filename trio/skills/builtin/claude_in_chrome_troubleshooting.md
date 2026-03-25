---
name: trio-in-chrome-troubleshooting
description: Diagnose and fix Trio in Chrome MCP extension connectivity issues. Use when mcp__claude-in-chrome__* tools fail, return "Browser extension is not connected", or behave erratically.
risk: unknown
source: builtin
---

# Trio in Chrome MCP Troubleshooting

Use this skill when Trio in Chrome MCP tools fail to connect or work unreliably.

## When to Use
- `mcp__claude-in-chrome__*` tools fail with "Browser extension is not connected"
- Browser automation works erratically or times out
- After updating Trio or Trio.app
- When switching between Trio CLI and Trio.app (Cowork)
- Native host process is running but MCP tools still fail

## When NOT to Use

- **Linux or Windows users** - This skill covers macOS-specific paths and tools (`~/Library/Application Support/`, `osascript`)
- General Chrome automation issues unrelated to the Trio extension
- Trio.app desktop issues (not browser-related)
- Network connectivity problems
- Chrome extension installation issues (use Chrome Web Store support)

## The Trio.app vs Trio Conflict (Primary Issue)

**Background:** When Trio.app added Cowork support (browser automation from the desktop app), it introduced a competing native messaging host that conflicts with Trio CLI.

### Two Native Hosts, Two Socket Formats

| Component | Native Host Binary | Socket Location |
|-----------|-------------------|-----------------|
| **Trio.app (Cowork)** | `/Applications/Trio.app/Contents/Helpers/chrome-native-host` | `/tmp/trio-mcp-browser-bridge-$USER/<PID>.sock` |
| **Trio CLI** | `~/.local/share/trio/versions/<version> --chrome-native-host` | `$TMPDIR/trio-mcp-browser-bridge-$USER` (single file) |

### Why They Conflict

1. Both register native messaging configs in Chrome:
   - `com.trio.claude_browser_extension.json` → Trio.app helper
   - `com.trio.claude_code_browser_extension.json` → Trio wrapper

2. Chrome extension requests a native host by name
3. If the wrong config is active, the wrong binary runs
4. The wrong binary creates sockets in a format/location the MCP client doesn't expect
5. Result: "Browser extension is not connected" even though everything appears to be running

### The Fix: Disable Trio.app's Native Host

**If you use Trio CLI for browser automation (not Cowork):**

```bash
# Disable the Trio.app native messaging config
mv ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.trio.claude_browser_extension.json \
   ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.trio.claude_browser_extension.json.disabled

# Ensure the Trio config exists and points to the wrapper
cat ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.trio.claude_code_browser_extension.json
```

**If you use Cowork (Trio.app) for browser automation:**

```bash
# Disable the Trio native messaging config
mv ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.trio.claude_code_browser_extension.json \
   ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.trio.claude_code_browser_extension.json.disabled
```

**You cannot use both simultaneously.** Pick one and disable the other.

### Toggle Script

Add this to `~/.zshrc` or run directly:

```bash
chrome-mcp-toggle() {
    local CONFIG_DIR=~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts
    local CLAUDE_APP="$CONFIG_DIR/com.trio.claude_browser_extension.json"
    local CLAUDE_CODE="$CONFIG_DIR/com.trio.claude_code_browser_extension.json"

    if [[ -f "$CLAUDE_APP" && ! -f "$CLAUDE_APP.disabled" ]]; then
        # Currently using Trio.app, switch to Trio
        mv "$CLAUDE_APP" "$CLAUDE_APP.disabled"
        [[ -f "$CLAUDE_CODE.disabled" ]] && mv "$CLAUDE_CODE.disabled" "$CLAUDE_CODE"
        echo "Switched to Trio CLI"
        echo "Restart Chrome and Trio to apply"
    elif [[ -f "$CLAUDE_CODE" && ! -f "$CLAUDE_CODE.disabled" ]]; then
        # Currently using Trio, switch to Trio.app
        mv "$CLAUDE_CODE" "$CLAUDE_CODE.disabled"
        [[ -f "$CLAUDE_APP.disabled" ]] && mv "$CLAUDE_APP.disabled" "$CLAUDE_APP"
        echo "Switched to Trio.app (Cowork)"
        echo "Restart Chrome to apply"
    else
        echo "Current state unclear. Check configs:"
        ls -la "$CONFIG_DIR"/com.trio*.json* 2>/dev/null
    fi
}
```

Usage: `chrome-mcp-toggle` then restart Chrome (and Trio if switching to CLI).

## Quick Diagnosis

```bash
# 1. Which native host binary is running?
ps aux | grep chrome-native-host | grep -v grep
# Trio.app: /Applications/Trio.app/Contents/Helpers/chrome-native-host
# Trio: ~/.local/share/trio/versions/X.X.X --chrome-native-host

# 2. Where is the socket?
# For Trio (single file in TMPDIR):
ls -la "$(getconf DARWIN_USER_TEMP_DIR)/trio-mcp-browser-bridge-$USER" 2>&1

# For Trio.app (directory with PID files):
ls -la /tmp/trio-mcp-browser-bridge-$USER/ 2>&1

# 3. What's the native host connected to?
lsof -U 2>&1 | grep trio-mcp-browser-bridge

# 4. Which configs are active?
ls ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.trio*.json
```

## Critical Insight

**MCP connects at startup.** If the browser bridge wasn't ready when Trio started, the connection will fail for the entire session. The fix is usually: ensure Chrome + extension are running with correct config, THEN restart Trio.

## Full Reset Procedure (Trio CLI)

```bash
# 1. Ensure correct config is active
mv ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.trio.claude_browser_extension.json \
   ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.trio.claude_browser_extension.json.disabled 2>/dev/null

# 2. Update the wrapper to use latest Trio version
cat > ~/.trio/chrome/chrome-native-host << 'EOF'
#!/bin/bash
LATEST=$(ls -t ~/.local/share/trio/versions/ 2>/dev/null | head -1)
exec "$HOME/.local/share/trio/versions/$LATEST" --chrome-native-host
EOF
chmod +x ~/.trio/chrome/chrome-native-host

# 3. Kill existing native host and clean sockets
pkill -f chrome-native-host
rm -rf /tmp/trio-mcp-browser-bridge-$USER/
rm -f "$(getconf DARWIN_USER_TEMP_DIR)/trio-mcp-browser-bridge-$USER"

# 4. Restart Chrome
osascript -e 'quit app "Google Chrome"' && sleep 2 && open -a "Google Chrome"

# 5. Wait for Chrome, click Trio extension icon

# 6. Verify correct native host is running
ps aux | grep chrome-native-host | grep -v grep
# Should show: ~/.local/share/trio/versions/X.X.X --chrome-native-host

# 7. Verify socket exists
ls -la "$(getconf DARWIN_USER_TEMP_DIR)/trio-mcp-browser-bridge-$USER"

# 8. Restart Trio
```

## Other Common Causes

### Multiple Chrome Profiles

If you have the Trio extension installed in multiple Chrome profiles, each spawns its own native host and socket. This can cause confusion.

**Fix:** Only enable the Trio extension in ONE Chrome profile.

### Multiple Trio Sessions

Running multiple Trio instances can cause socket conflicts.

**Fix:** Only run one Trio session at a time, or use `/mcp` to reconnect after closing other sessions.

### Hardcoded Version in Wrapper

The wrapper at `~/.trio/chrome/chrome-native-host` may have a hardcoded version that becomes stale after updates.

**Diagnosis:**
```bash
cat ~/.trio/chrome/chrome-native-host
# Bad: exec "/Users/.../.local/share/trio/versions/2.0.76" --chrome-native-host
# Good: Uses $(ls -t ...) to find latest
```

**Fix:** Use the dynamic version wrapper shown in the Full Reset Procedure above.

### TMPDIR Not Set

Trio expects `TMPDIR` to be set to find the socket.

```bash
# Check
echo $TMPDIR
# Should show: /var/folders/XX/.../T/

# Fix: Add to ~/.zshrc
export TMPDIR="${TMPDIR:-$(getconf DARWIN_USER_TEMP_DIR)}"
```

## Diagnostic Deep Dive

```bash
echo "=== Native Host Binary ==="
ps aux | grep chrome-native-host | grep -v grep

echo -e "\n=== Socket (Trio location) ==="
ls -la "$(getconf DARWIN_USER_TEMP_DIR)/trio-mcp-browser-bridge-$USER" 2>&1

echo -e "\n=== Socket (Trio.app location) ==="
ls -la /tmp/trio-mcp-browser-bridge-$USER/ 2>&1

echo -e "\n=== Native Host Open Files ==="
pgrep -f chrome-native-host | xargs -I {} lsof -p {} 2>/dev/null | grep -E "(sock|trio-mcp)"

echo -e "\n=== Active Native Messaging Configs ==="
ls ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.trio*.json 2>/dev/null

echo -e "\n=== Custom Wrapper Contents ==="
cat ~/.trio/chrome/chrome-native-host 2>/dev/null || echo "No custom wrapper"

echo -e "\n=== TMPDIR ==="
echo "TMPDIR=$TMPDIR"
echo "Expected: $(getconf DARWIN_USER_TEMP_DIR)"
```

## File Reference

| File | Purpose |
|------|---------|
| `~/.trio/chrome/chrome-native-host` | Custom wrapper script for Trio |
| `/Applications/Trio.app/Contents/Helpers/chrome-native-host` | Trio.app (Cowork) native host |
| `~/.local/share/trio/versions/<version>` | Trio binary (run with `--chrome-native-host`) |
| `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.trio.claude_browser_extension.json` | Config for Trio.app native host |
| `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.trio.claude_code_browser_extension.json` | Config for Trio native host |
| `$TMPDIR/trio-mcp-browser-bridge-$USER` | Socket file (Trio) |
| `/tmp/trio-mcp-browser-bridge-$USER/<PID>.sock` | Socket files (Trio.app) |

## Summary

1. **Primary issue:** Trio.app (Cowork) and Trio use different native hosts with incompatible socket formats
2. **Fix:** Disable the native messaging config for whichever one you're NOT using
3. **After any fix:** Must restart Chrome AND Trio (MCP connects at startup)
4. **One profile:** Only have Trio extension in one Chrome profile
5. **One session:** Only run one Trio instance

---

*Original skill by [@jeffzwang](https://github.com/jeffzwang) from [@ExaAILabs](https://github.com/ExaAILabs). Enhanced and updated for current versions of Trio Desktop and Trio.*
