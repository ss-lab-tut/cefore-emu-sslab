---
name: cefore-reference
description: |
  Reference for Cefore (Content-Centric Networking) commands, arguments, and configuration. Use this skill whenever you need to look up Cefore CLI tool syntax, daemon management commands, FIB management (cefroute), cache status (csmgrstatus, cefstatus), pub/sub commands (cefpubfile, cefsubfile), or config file parameters. Trigger on any question or task involving cefputfile, cefgetfile, cefgetchunk, cefputstream, cefgetstream, cefinfo, cefsubfile, cefpubfile, cefnetd, csmgrd, cefroute, cefstatus, csmgrstatus, cefnetd.conf, csmgrd.conf, or cefnetd.fib. Always consult this skill before writing or editing Cefore command invocations.
---

# Cefore Reference Skill

When asked about Cefore commands, their arguments, or configuration, consult the appropriate reference file(s) listed below. Read only what you need — start with the section that matches the user's question.

## Reference Files

- `references/tools.md` — All Cefore CLI tools: cefputfile, cefgetfile, cefgetchunk, cefputstream, cefgetstream, cefinfo, cefsubfile, cefpubfile
- `references/daemon.md` — Daemon management: cefnetd start/stop, cefstatus, cefroute (FIB management), csmgrd start/stop, csmgrstatus, log levels
- `references/configuration.md` — Config file parameters: cefnetd.conf, cefnetd.fib, cefnetd.key, csmgrd.conf, plugin.conf

## Quick Reference

### Most-used commands in this project

| Command | Purpose |
|---------|---------|
| `cefputfile uri -f path` | Publish file content |
| `cefgetfile uri -f path` | Retrieve file content |
| `cefpubfile uri -f path` | Publish via Reflexive Forwarding (pub/sub) |
| `cefsubfile uri -f outdir` | Subscribe via Reflexive Forwarding (pub/sub) |
| `cefroute add uri udp host` | Add FIB route entry |
| `cefroute del uri udp host` | Delete FIB route entry |
| `cefroute enable uri udp host` | Re-enable a downed face |
| `cefstatus` | Show cefnetd FIB/PIT/face status |
| `csmgrstatus [uri]` | Show cache manager status |
| `cefnetdstart [-d dir] [-p port]` | Start forwarding daemon |
| `cefnetdstop [-F]` | Stop forwarding daemon |
| `csmgrdstart [-d dir]` | Start cache manager |
| `csmgrdstop [-F]` | Stop cache manager |

### Common options (apply to most commands)

| Option | Description |
|--------|-------------|
| `-d config_file_dir` | Path to configuration directory (overrides `CEFORE_DIR`) |
| `-p port_num` | Port number (overrides `PORT_NUM` in cefnetd.conf) |

### pub/sub mode notes

- `cefsubfile -f` takes an **output directory**, not a file path. Output files are named `RNP0x<hex>.out` — names cannot be predicted in advance.
- `cefpubfile` requires Content Store enabled on the node (`CS_MODE=1` or `CS_MODE=2`).
- Success detection for cefsubfile: exit code == 0 **and** a non-empty `RNP0x*.out` file exists in the output directory.

### Default port numbers

| Daemon | Default Port |
|--------|-------------|
| cefnetd | 9695 |
| csmgrd  | 9799 |
