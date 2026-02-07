# MegaBot: Platform Compatibility Guide

MegaBot is designed to be cross-platform, leveraging Python and Node.js to run on almost any modern operating system.

## 🐧 Linux (Native)
Linux is the primary development target.
- **Recommended Distros**: Ubuntu 22.04+, Arch, Debian.
- **Setup**: Use the `setup.sh` script to install all dependencies.
- **Paths**: Standard Linux paths work out of the box.

## 🍎 macOS (Native)
MegaBot works perfectly on macOS.
- **Silicon Support**: Full support for M1/M2/M3 chips.
- **Setup**: `brew install python nodejs` followed by `pip install -r requirements.txt`.

## 🪟 Windows (Native & WSL)
### native Windows
1. Install Python 3.13 and Node.js from their respective websites.
2. Run `pip install -r requirements.txt`.
3. **Note**: Update `mega-config.yaml` to use Windows-style paths (e.g., `D:\\Agents and other repos`).

### WSL2 (Recommended for Windows)
MegaBot runs exceptionally well inside WSL2 (Ubuntu).
- Access your Windows drives via `/mnt/c/` or `/mnt/d/`.
- This provides the closest experience to a native Linux environment.

## 🐳 Docker (Any Platform)
Docker is the easiest way to run MegaBot without cluttering your host system.
```bash
cp mega-config.yaml.template mega-config.yaml
docker-compose up --build
```
This will start both the backend and frontend in a single isolated environment.

## 🖥️ Virtual Machines
MegaBot has low overhead and can run inside any VM with at least 4GB of RAM.
- Ensure the VM has network access to your local LLM provider (Ollama) if it is running on the host machine.
