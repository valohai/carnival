# Carnival

A lightweight Python-based process manager designed for Docker containers.

## Requirements

- Python 3.12+ – no external dependencies

## Installation

Standard Python installation; you can build a wheel, and then run `carnival` directly.
For development, use `uv run carnival`.

## Configuration

Configured via TOML file (can be set on the command line or via `CARNIVAL_CONFIG_TOML` env var).

### Basic Structure

```toml
[[init]]
# Initialization commands (run sequentially)
command = "mkdir"
args = ["-p", "${DATA_DIR:-/data}"]

[[service]]
# Service definitions (run in parallel)
name = "webserver"
command = "python3"
args = ["-m", "http.server", "${PORT:-8000}"]
replicas = "${NUM_WORKERS:-2}"
restart = "always"
restart-delay-ms = "${RESTART_DELAY:-1000}"  # or restart_delay_ms
restart-limit = 0  # 0 = unlimited (default); or restart_limit
stop-timeout-ms = 10000  # How long to give the process before SIGKILLing; or stop_timeout_ms
```

**Note:** Field names accept both `kebab-case` and `snake_case`.

### Environment Variables

Carnival supports environment variable interpolation in all string and numeric fields:

- `${VAR}` - Uses value from environment, or preserves `${VAR}` if not set (for runtime expansion)
- `${VAR:-default}` - Uses value from environment, or uses `default` if not set
- `$VAR` - Uses value from environment, or preserves `$VAR` if not set (for runtime expansion)

**Important:** Variables not set at config parse time are preserved for runtime expansion by the shell. This allows you to reference `CARNIVAL_*` variables in your commands:

```toml
[[service]]
name = "worker"
command = "sh"
args = ["-c", "echo \"I am $CARNIVAL_SERVICE_NAME replica $CARNIVAL_REPLICA_ID\""]
```

**Numeric fields** (`replicas`, `restart_delay_ms`) can also use environment variables:
- Accept both integer literals: `replicas = 3`
- Or expandable strings: `replicas = "${NUM_WORKERS:-2}"`

### Restart Policies

- `no` - Run once, don't restart (one-shot tasks)
- `always` - Always restart, regardless of exit code
- `on-failure` - Only restart on non-zero exit codes

### Restart Limits

Set `restart_limit = N` to limit the number of restarts. The service will run initially, then restart up to N-1 times (for a total of N runs). Default is `0` (unlimited restarts).

### Service Replicas

Set `replicas = N` to run N copies of a service. Each replica runs independently with its own restart counter.

### Service Environment Variables

Each service process automatically receives these environment variables:

- `CARNIVAL_SERVICE_NAME` - The service name from the config
- `CARNIVAL_REPLICA_ID` - Zero-based replica index (0 to N-1)
- `CARNIVAL_REPLICA_COUNT` - Total number of replicas for this service
- `CARNIVAL_RESTART_COUNT` - Number of times this service has been restarted (starts at 0)

## Example

See `examples/` for a complete working example.

## License

MIT
