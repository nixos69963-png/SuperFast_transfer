# SuperFast_trans
# ⚡ AirTrans – Super Fast File Transfer System

**Developer:**  *FahFah Mohamed*  
**Version:** 1.0  
**License:** MIT  
**Language:** Python 3.10+  
**Tech Stack:** FastAPI • asyncio • aiofiles • parallel TCP sockets  

---

## 📦 Overview

**AirTrans** is a next-generation **high-speed file transfer system** designed for ultra-fast data delivery using **multi-port parallel transmission**.  
Unlike traditional socket-based transfers, AirTrans splits large files into chunks and transmits them simultaneously across multiple ports — achieving blazing speeds and high reliability.

---

## 🚀 Key Features

- ⚡ **Multi-Port Parallel Transfers** – Split files across multiple TCP connections for max speed  
- 🔐 **Checksum Verification (SHA-256)** – Guaranteed integrity of each file part  
- 🧠 **Async I/O Architecture** – Fully non-blocking using `asyncio` + `aiofiles`  
- 📡 **QR Code Session Sharing** – Share transfer session metadata easily between devices  
- 🧩 **Compression Optional** – Send smaller payloads when needed  
- 🧰 **CLI Ready** – Built-in `airtrans_cli` for sending/receiving files instantly  

```

Structure :

airtrans/
├── api/
│ ├── airtrans_cli.py # Command line tool for send/receive
│ ├── apitran.py # Core logic for parallel transfers
│ └── init.py
├── app/
│ ├── main.py # FastAPI entry point
│ └── routes/
│ └── transfer.py # API routes for sessions
├── requirements.txt
└── README.md

```

```bash
cd airtrans

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

api : python3 -m api.airtrans_cli server
sender : python3 -m api.airtrans_cli send myfile.bin
reciver : will get url from send >>>
python3 -m api.airtrans_cli receive --qr '<session_json>'

```
performance of testing
so we send file 100.00 mb
____

| File Size | Connections | Avg Speed  | Transfer Time |
| --------- | ----------- | ---------- | ------------- |
| 100 MB    | 10 ports    | 39.73 MB/s | 2.3 seconds   |
| 1 GB      | 10 ports    | ~400 MB/s  | ~2.5 seconds  |

____


**MIT © 2025 — FahFah Mohamed**