# Pi Thermostat Development Rules

## Critical Rule: Always Fix Windows Line Endings for Bash Scripts

**Problem:** When creating or editing bash scripts (`.sh` files) on Windows and transferring them to Linux/Pi, the shebang line and newlines get corrupted with Windows CRLF (`\r\n`) line endings instead of Unix LF (`\n`). This causes:
- `sudo: script.sh: command not found` errors
- Shebang interpretation failures
- Script execution failures

**Solution - Always apply this fix before running bash scripts on Linux:**

```bash
# Option 1: Convert line endings when copying to Pi
dos2unix ~/pi-thermo/script.sh

# Option 2: If dos2unix not available, use sed
sed -i 's/\r$//' ~/pi-thermo/script.sh

# Option 3: Run script with bash explicitly (works even with corrupted shebang)
bash ~/pi-thermo/script.sh
```

**When to apply:**
- ✅ After any `.sh` script file is created or modified on Windows
- ✅ Before transferring `.sh` files to Pi via SCP
- ✅ Before running any bash scripts on the Pi
- ✅ After copying installation/setup scripts

**Best practice workflow:**
1. Create/edit script on Windows
2. Before SCP: Fix line endings locally
   ```bash
   sed -i 's/\r$//' path/to/script.sh
   ```
3. SCP to Pi
4. On Pi: Verify and run
   ```bash
   bash script.sh
   ```

**Prevention tips:**
- Configure git to auto-convert line endings:
  ```bash
  git config --global core.autocrlf input
  ```
- Use VS Code setting: `"files.eol": "\n"`
- Always explicitly use `bash script.sh` instead of `./script.sh` as fallback

## Related Rules
- Follow GPIO cleanup requirement for relay OFF
- Always build error handling and logs into code
- Always use all logs at your disposal to diagnose issues
