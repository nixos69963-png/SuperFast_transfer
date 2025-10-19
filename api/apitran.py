"""
AirTrans Transfer Engine - High-Speed Multi-Port TCP File Transfer
Supports parallel chunk transfers with asyncio for maximum throughput
"""

import asyncio
import time
import hashlib
import msgpack
from pathlib import Path
from typing import List, Dict, Tuple
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TransferSession:
    """Manages a single file transfer session with metadata"""
    def __init__(self, filename: str, filesize: int, num_parts: int, ports: List[int], checksum: str = ""):
        self.filename = filename
        self.filesize = filesize
        self.num_parts = num_parts
        self.ports = ports
        self.checksum = checksum
        self.progress = {i: 0 for i in range(num_parts)}
        self.start_time = None
        self.bytes_transferred = 0


class AirTransSender:
    """High-speed sender using asyncio for parallel TCP transfers"""
    
    def __init__(self, filepath: str, num_parts: int = 8, base_port: int = 5001):
        self.filepath = Path(filepath)
        self.num_parts = num_parts
        self.base_port = base_port
        self.ports = [base_port + i for i in range(num_parts)]
        self.filesize = self.filepath.stat().st_size
        self.session = None
        
    async def send_chunk(self, chunk_data: bytes, port: int, chunk_id: int) -> Tuple[int, float]:
        """Send a single chunk over TCP on specified port"""
        server = await asyncio.start_server(
            lambda r, w: self._handle_client(r, w, chunk_data, chunk_id),
            '0.0.0.0', port
        )
        
        addr = server.sockets[0].getsockname()
        logger.info(f"Chunk {chunk_id} server started on {addr}")
        
        async with server:
            await server.serve_forever()
    
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, 
                            chunk_data: bytes, chunk_id: int):
        """Handle incoming connection and send chunk data"""
        addr = writer.get_extra_info('peername')
        logger.info(f"Client connected from {addr} for chunk {chunk_id}")
        
        try:
            # Send chunk metadata first
            metadata = {
                'chunk_id': chunk_id,
                'size': len(chunk_data),
                'checksum': hashlib.sha256(chunk_data).hexdigest()
            }
            packed_meta = msgpack.packb(metadata)
            writer.write(len(packed_meta).to_bytes(4, 'big'))
            writer.write(packed_meta)
            await writer.drain()
            
            # Send chunk data in blocks
            block_size = 1024 * 1024  # 1MB blocks
            start_time = time.time()
            
            for i in range(0, len(chunk_data), block_size):
                block = chunk_data[i:i + block_size]
                writer.write(block)
                await writer.drain()
                
                self.session.bytes_transferred += len(block)
                self.session.progress[chunk_id] = i + len(block)
                
            elapsed = time.time() - start_time
            speed_mbps = (len(chunk_data) / elapsed) / (1024 * 1024)
            logger.info(f"Chunk {chunk_id} sent: {len(chunk_data)} bytes in {elapsed:.2f}s ({speed_mbps:.2f} MB/s)")
            
            writer.close()
            await writer.wait_closed()
            
        except Exception as e:
            logger.error(f"Error sending chunk {chunk_id}: {e}")
    
    async def send_file(self) -> Dict:
        """Main method to split and send file over multiple ports"""
        logger.info(f"Starting transfer of {self.filepath.name} ({self.filesize} bytes)")
        
        # Read and split file
        with open(self.filepath, 'rb') as f:
            file_data = f.read()
        
        file_checksum = hashlib.sha256(file_data).hexdigest()
        chunk_size = self.filesize // self.num_parts
        chunks = []
        
        for i in range(self.num_parts):
            start = i * chunk_size
            end = start + chunk_size if i < self.num_parts - 1 else self.filesize
            chunks.append(file_data[start:end])
        
        self.session = TransferSession(
            self.filepath.name, self.filesize, self.num_parts, self.ports, file_checksum
        )
        self.session.start_time = time.time()
        
        # Create server tasks for each chunk
        tasks = [
            asyncio.create_task(self.send_chunk(chunk, port, i))
            for i, (chunk, port) in enumerate(zip(chunks, self.ports))
        ]
        
        # Wait for all transfers to complete (with timeout)
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=300)
        except asyncio.TimeoutError:
            logger.error("Transfer timed out")
        
        elapsed = time.time() - self.session.start_time
        avg_speed = (self.filesize / elapsed) / (1024 * 1024)
        
        return {
            'filename': self.filepath.name,
            'filesize': self.filesize,
            'ports': self.ports,
            'num_parts': self.num_parts,
            'checksum': file_checksum,
            'elapsed': elapsed,
            'avg_speed_mbps': avg_speed
        }


class AirTransReceiver:
    """High-speed receiver using asyncio for parallel TCP downloads"""
    
    def __init__(self, metadata: Dict, output_dir: str = "/tmp/airtrans"):
        self.metadata = metadata
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.chunks = {}
        self.session = TransferSession(
            metadata['filename'],
            metadata['filesize'],
            metadata['num_parts'],
            metadata['ports'],
            metadata['checksum']
        )
    
    async def receive_chunk(self, ip: str, port: int, chunk_id: int):
        """Receive a single chunk from sender"""
        try:
            reader, writer = await asyncio.open_connection(ip, port)
            logger.info(f"Connected to {ip}:{port} for chunk {chunk_id}")
            
            # Read metadata
            meta_len = int.from_bytes(await reader.readexactly(4), 'big')
            meta_data = await reader.readexactly(meta_len)
            metadata = msgpack.unpackb(meta_data)
            
            chunk_size = metadata['size']
            chunk_checksum = metadata['checksum']
            
            # Read chunk data
            chunk_data = bytearray()
            bytes_received = 0
            start_time = time.time()
            
            while bytes_received < chunk_size:
                block = await reader.read(1024 * 1024)  # 1MB blocks
                if not block:
                    break
                chunk_data.extend(block)
                bytes_received += len(block)
                self.session.bytes_transferred += len(block)
                self.session.progress[chunk_id] = bytes_received
            
            # Verify checksum
            received_checksum = hashlib.sha256(chunk_data).hexdigest()
            if received_checksum != chunk_checksum:
                raise ValueError(f"Chunk {chunk_id} checksum mismatch!")
            
            self.chunks[chunk_id] = bytes(chunk_data)
            
            elapsed = time.time() - start_time
            speed_mbps = (chunk_size / elapsed) / (1024 * 1024)
            logger.info(f"Chunk {chunk_id} received: {chunk_size} bytes in {elapsed:.2f}s ({speed_mbps:.2f} MB/s)")
            
            writer.close()
            await writer.wait_closed()
            
        except Exception as e:
            logger.error(f"Error receiving chunk {chunk_id}: {e}")
            raise
    
    async def receive_file(self, sender_ip: str) -> str:
        """Main method to receive all chunks and reassemble file"""
        logger.info(f"Starting download from {sender_ip}")
        self.session.start_time = time.time()
        
        # Create receive tasks for all chunks
        tasks = [
            asyncio.create_task(self.receive_chunk(sender_ip, port, i))
            for i, port in enumerate(self.metadata['ports'])
        ]
        
        # Wait for all downloads to complete
        await asyncio.gather(*tasks)
        
        # Reassemble file
        output_path = self.output_dir / self.metadata['filename']
        with open(output_path, 'wb') as f:
            for i in range(self.metadata['num_parts']):
                f.write(self.chunks[i])
        
        # Verify final file
        with open(output_path, 'rb') as f:
            file_checksum = hashlib.sha256(f.read()).hexdigest()
        
        if file_checksum != self.metadata['checksum']:
            raise ValueError("Final file checksum mismatch!")
        
        elapsed = time.time() - self.session.start_time
        avg_speed = (self.metadata['filesize'] / elapsed) / (1024 * 1024)
        
        logger.info(f"Transfer complete! Average speed: {avg_speed:.2f} MB/s")
        logger.info(f"File saved to: {output_path}")
        
        return str(output_path)


# CLI Interface
async def send_mode(filepath: str, num_parts: int = 8):
    """Send file in sender mode"""
    sender = AirTransSender(filepath, num_parts)
    metadata = await sender.send_file()
    print(f"\n✅ Transfer metadata:")
    print(f"   Filename: {metadata['filename']}")
    print(f"   Ports: {metadata['ports']}")
    print(f"   Checksum: {metadata['checksum']}")
    print(f"   Speed: {metadata['avg_speed_mbps']:.2f} MB/s")
    return metadata


async def receive_mode(sender_ip: str, metadata: Dict):
    """Receive file in receiver mode"""
    receiver = AirTransReceiver(metadata)
    output_path = await receiver.receive_file(sender_ip)
    print(f"\n✅ File received: {output_path}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Send: python apitran.py send <filepath> [--split N]")
        print("  Receive: python apitran.py receive <sender_ip> <metadata_json>")
        sys.exit(1)
    
    mode = sys.argv[1]
    
    if mode == "send":
        filepath = sys.argv[2]
        num_parts = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[3] == "--split" else 8
        asyncio.run(send_mode(filepath, num_parts))
    elif mode == "receive":
        sender_ip = sys.argv[2]
        # metadata would come from QR code in real implementation
        print("Receive mode requires metadata from QR code")
    else:
        print(f"Unknown mode: {mode}")