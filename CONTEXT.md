# CeforeEmu Context

CeforeEmu emulates Content-Centric Networking (Cefore) deployments on Mininet. This glossary fixes the project-specific language so code and future architecture reviews stay consistent. General programming concepts are intentionally excluded.

## Command execution

**CommandRunner**:
The single seam through which every command sent to a Mininet host (or the root namespace) is executed. Owns argv execution, output redirection, and the lifecycle of long-running processes. Has two adapters: a real Mininet-backed one and a recording fake for tests.
_Avoid_: shell helper, exec wrapper, "host.cmd()" path

**CommandResult**:
The value a CommandRunner returns for a finished command: `returncode`, `stdout`, `stderr`, `timed_out`, `cancelled`, `log_path`. Deadline/cancellation is expressed through the `timed_out`/`cancelled` flags, not through a sentinel returncode.
_Avoid_: output, return tuple, proc result

**CommandHandle**:
The token a CommandRunner returns for a still-running command. Callers wait/poll/terminate/kill it through the runner; they never hold a raw `Popen`.
_Avoid_: proc, process handle, popen object

## Host identity

**Node name**:
The canonical identifier of a host in runner and config interfaces — the string `"h{idx}"` (e.g. `"h3"`). This is the one identity used everywhere; integer host indices are an internal/topology detail, not an interface identity.
_Avoid_: host index, idx, host id (as an interface argument)

**Root sentinel**:
The reserved Node name that tells the CommandRunner to execute in the root namespace (plain subprocess) instead of a host netns. Used by bridge/external-network setup.
_Avoid_: root ns flag, "root" special case
