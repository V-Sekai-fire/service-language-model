"""Shared setup for `pixi run serve`: ensure an API key exists and pick a free port.

Writes the key into `.env` (creating it if needed) and the chosen port into `.port`.
Run before launching llama-server; the server reads the port from `.port`.
"""
import os
import secrets
import socket

HOST = "127.0.0.1"
PORT_START = 9931
PORT_RANGE = 10000

MODEL = "./models/Ternary-Bonsai-2-27B-Uncensored-Heretic-v2-PQ2_0.gguf"
DRAFT = "./models/Qwen3.8-27B-DFlash2-Q4_K_M.gguf"
SLOT_DIR = "./llama-slots"


def _free(p):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("0.0.0.0", p))
        s.close()
        return True
    except OSError:
        return False


def ensure_key():
    env_file = ".env"
    key = os.environ.get("LLAMA_API_KEY")
    if key or not os.path.exists(env_file):
        key = secrets.token_hex(16)
        with open(env_file, "a") as f:
            f.write(f"LLAMA_API_KEY={key}\n")
        print(f"Generated new LLAMA_API_KEY in {env_file}")
    else:
        with open(env_file, "r") as f:
            for line in f:
                if line.strip().startswith("LLAMA_API_KEY="):
                    key = line.strip().split("=", 1)[1].strip(" \t\"'")
                    break
        print(f"Loaded LLAMA_API_KEY from {env_file}")
    return key


def pick_port():
    port = next(p for p in range(PORT_START, PORT_START + PORT_RANGE) if _free(p))
    with open(".port", "w") as f:
        f.write(str(port))
    print(f"Serving on port {port}")
    return port


def serve_cmd(binary):
    """Full llama-server command, defined once for all platforms."""
    return [
        binary,
        "-m", MODEL,
        "-md", DRAFT,
        "--spec-type", "draft-dflash",
        "--spec-draft-n-max", "7",
        "--reasoning-preserve",
        "--slot-save-path", SLOT_DIR,
        "--cors-origins", "*",
        "--api-key", "",
        "-ngl", "99",
        "-ngld", "99",
        "-sm", "layer",
        "-c", "242144",
        "-b", "4096",
        "-ub", "1024",
        "-ctk", "q8_0",
        "-ctv", "q8_0",
        "-t", "8",
        "-np", "1",
        "-fa", "on",
        "--no-repack",
        "--repeat-penalty", "1.0",
        "--temp", "0.65",
        "--host", HOST,
        "--port", "0",
    ]


if __name__ == "__main__":
    key = ensure_key()
    pick_port()
    print(f"LLAMA_API_KEY={key}")
