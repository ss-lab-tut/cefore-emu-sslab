# Repository Guidelines

## Project Structure & Module Organization
- Python entry points live at the repo root. Key scripts include `simple-three-nodes-two-switch.py` (3-node demo) and `five-node-two-switch.py` (larger topology). `main.py` is a small wrapper or entry point.
- Host-specific Cefore configs live in `h0/`, `h1/`, `h2/` (e.g., `cefnetd.conf`, `cefnetd.fib`, `conpubd.conf`, `csmgrd.conf`, `plugin.conf`, and key material).
- `sample-putfile` is the sample payload used by `cefputfile` in the demos.
- Runtime logs and output files are written to the repo root (e.g., `h0-cefnetd-log`, `cefputfile-log`, `cefgetfile-log`, `recvfile_at_h0`).

## Build, Test, and Development Commands
- `sudo python3 simple-three-nodes-two-switch.py`: Launch the 3-node Mininet topology (consumer, router, publisher) and run a put/get demo.
- `sudo python3 five-node-two-switch.py`: Launch the larger demo topology.
- `mininet> exit`: Quit the Mininet CLI and stop the emulation.
- Prereqs are external: install Cefore and Mininet 2.3.x on Ubuntu 22.04 (see `README.md`).

## Coding Style & Naming Conventions
- Python scripts are plain, script-style modules. Prefer 4-space indents and keep formatting consistent with the file you edit.
- Function names are mixed case (e.g., `setIpAddr`, `setFib`); match existing patterns within each script.
- Host directories are named `h0`, `h1`, `h2` and should map 1:1 to the topology definitions.

## Testing Guidelines
- No automated test framework is present. Validate changes by running a demo script and checking for successful content retrieval (`recvfile_at_h0`) plus clean daemon logs.
- If you add tests, document how to run them and keep the command in this file.

## Commit & Pull Request Guidelines
- Git history does not show a formal convention. Use concise, imperative subjects (e.g., "Update h1 routing rules") and mention the topology or config scope when relevant.
- PRs should describe topology changes, list updated config files, and include a short reproduction checklist (commands and expected artifacts).

## Security & Configuration Notes
- `h*/default-private-key` contains private key material. Treat it as sensitive and avoid sharing in logs or tickets.
- Running the scripts requires root privileges; use trusted environments only.
