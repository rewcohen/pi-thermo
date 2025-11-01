# Contributing to Pi Thermostat

## Getting Started

1. Clone the repository
2. Copy files to your Pi's `~/pi-thermo` directory
3. Run the installer: `bash ~/pi-thermo/install_complete.sh`

## Important Development Rules

### Line Endings (Critical!)
This project works with both Windows and Linux. Git is configured to automatically handle line endings via `.gitattributes`, but be aware:

- **Bash scripts** (`.sh`) must use Unix LF line endings
- **Python scripts** (`.py`) should use Unix LF line endings
- Git will auto-convert on commit thanks to `.gitattributes`

If you edit files on Windows, ensure your editor uses LF line endings:
- VS Code: Set `"files.eol": "\n"` in settings.json
- Notepad++: Edit → EOL Conversion → Unix (LF)

### Error Handling
- Always include try-except blocks in Python code
- Log all errors with context
- Implement graceful degradation when components fail

### Logging
- Use Python's `logging` module
- Log sensor readings at DEBUG level
- Log state changes (heating ON/OFF) at INFO level
- Log errors with full tracebacks at ERROR level

### GPIO and Relay Control
- **Critical:** GPIO cleanup MUST be called to turn OFF the relay
- Always implement cleanup() in finally blocks
- Never leave GPIO in an unknown state

## Development Workflow

1. **Make changes** to your feature/bugfix
2. **Test locally** on your Pi:
   ```bash
   source ~/pi-thermo-env/bin/activate
   python3 ~/pi-thermo/thermostat.py
   ```
3. **Check logs** for any errors:
   ```bash
   tail -f ~/pi-thermo/thermo.log
   ```
4. **Commit with clear messages:**
   ```bash
   git add .
   git commit -m "Add feature: description of what changed"
   git push
   ```

## Code Style

- Follow PEP 8 for Python
- Use type hints where applicable
- Keep functions focused and modular
- Add docstrings to all functions

## Testing

- Test on actual Raspberry Pi hardware
- Verify OLED display updates
- Check web interface responsiveness
- Monitor heating cycles via event log

## Reporting Issues

Include:
- Error message or behavior description
- Recent log entries (`thermo.log`)
- Hardware setup (Pi model, sensor type, relay pin)
- Steps to reproduce

## Feature Requests

Describe:
- What you want to add
- Why it would be useful
- How it fits with existing functionality
