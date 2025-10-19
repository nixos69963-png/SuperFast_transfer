#!/usr/bin/env python3
"""
AirTrans CLI - Command-line interface for ultra-fast file transfers
"""

import asyncio
import argparse
import sys
import json
from pathlib import Path
from typing import Optional
import logging
from tqdm import tqdm
import requests

from api.apitran import AirTransSender, AirTransReceiver
from api.discovery import PeerDiscovery
from api.utils import (
    FileChunker, ChecksumManager, CompressionManager, 
    TransferMetadata, format_size, calculate_optimal_chunks
)
from config.settings import config

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT
)
logger = logging.getLogger(__name__)


class AirTransCLI:
    """Command-line interface for AirTrans"""
    
    def __init__(self):
        self.discovery = None
        self.api_base = f"http://{config.API_HOST}:{config.API_PORT}"
    
    async def send_file(self, filepath: str, num_parts: Optional[int] = None, 
                       compression: bool = False, no_qr: bool = False):
        """Send a file"""
        filepath = Path(filepath)
        
        if not filepath.exists():
            print(f"❌ Error: File not found: {filepath}")
            return
        
        filesize = filepath.stat().st_size
        print(f"\n📤 Preparing to send: {filepath.name}")
        print(f"   Size: {format_size(filesize)}")
        
        # Calculate optimal parts if not specified
        if num_parts is None:
            num_parts = calculate_optimal_chunks(filesize)
            print(f"   Auto-selected {num_parts} parallel connections")
        
        # Compress if requested and file is large enough
        if compression and filesize > config.COMPRESSION_THRESHOLD:
            print(f"   Compressing with LZ4...")
            compressed_path = CompressionManager.compress_file(str(filepath))
            filepath = Path(compressed_path)
            print(f"   Compressed to: {format_size(filepath.stat().st_size)}")
        
        # Create transfer session via API
        try:
            response = requests.post(f"{self.api_base}/create-session", json={
                'filepath': str(filepath),
                'num_parts': num_parts,
                'base_port': config.BASE_PORT,
                'compression': compression
            })
            
            if response.status_code != 201:
                print(f"❌ Error creating session: {response.json().get('error')}")
                return
            
            session_data = response.json()
            session_id = session_data['session_id']
            metadata = session_data['metadata']
            
            print(f"\n✅ Session created: {session_id}")
            print(f"   Transfer ports: {metadata['ports'][0]} - {metadata['ports'][-1]}")
            
            # Display QR code URL
            if not no_qr:
                qr_url = f"{self.api_base}/qr/{session_id}"
                print(f"\n📱 QR Code available at: {qr_url}")
                print(f"   Open this URL in a browser and scan with receiver")
                # Also print the metadata directly for easier CLI testing
                print(f"\n📋 For testing, use this command on the receiver:")
                print(f"   python -m api.airtrans_cli receive --qr '{json.dumps(metadata)}'")

            
            # Start transfer
            print(f"\n🚀 Starting transfer...")
            sender = AirTransSender(str(filepath), num_parts, config.BASE_PORT)
            
            # Show progress
            with tqdm(total=filesize, unit='B', unit_scale=True, desc="Sending") as pbar:
                # Run transfer (this will block until receivers connect)
                result = await sender.send_file()
                pbar.update(filesize)
            
            print(f"\n✅ Transfer complete!")
            print(f"   Average speed: {result['avg_speed_mbps']:.2f} MB/s")
            print(f"   Time elapsed: {result['elapsed']:.2f} seconds")
            print(f"   Checksum: {result['checksum'][:16]}...")
            
        except requests.RequestException as e:
            print(f"❌ API Error: {e}")
        except Exception as e:
            logger.exception("Error during send")
            print(f"❌ Transfer failed: {e}")
    
    async def receive_file(self, sender_ip: Optional[str] = None, 
                          qr_data: Optional[str] = None,
                          metadata_file: Optional[str] = None):
        """Receive a file"""
        metadata = None
        
        # Get metadata from various sources
        if metadata_file:
            print(f"📄 Reading metadata from: {metadata_file}")
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
        elif qr_data:
            print(f"📱 Using QR data...")
            metadata = json.loads(qr_data)
        else:
            print("❌ Error: Must provide either --qr, --metadata, or scan QR code")
            return
        
        if not sender_ip:
            sender_ip = metadata.get('ip')
        
        if not sender_ip:
            print("❌ Error: Sender IP not found in metadata")
            return
        
        print(f"\n📥 Preparing to receive: {metadata['filename']}")
        print(f"   From: {sender_ip}")
        print(f"   Size: {format_size(metadata['filesize'])}")
        print(f"   Parts: {metadata['num_parts']}")
        
        # Join session via API
        try:
            response = requests.post(f"{self.api_base}/join-session", json={
                'metadata': metadata
            })
            
            if response.status_code != 200:
                print(f"❌ Error joining session: {response.json().get('error')}")
                return
            
            session_data = response.json()
            session_id = session_data['session_id']
            
            print(f"✅ Joined session: {session_id}")
            
            # Start receiving
            print(f"\n🚀 Starting download...")
            receiver = AirTransReceiver(metadata, str(config.DOWNLOAD_DIR))
            
            # Show progress
            with tqdm(total=metadata['filesize'], unit='B', unit_scale=True, desc="Receiving") as pbar:
                last_transferred = 0
                
                # Start async receive task
                receive_task = asyncio.create_task(receiver.receive_file(sender_ip))
                
                # Update progress
                while not receive_task.done():
                    await asyncio.sleep(0.5)
                    current = receiver.session.bytes_transferred
                    pbar.update(current - last_transferred)
                    last_transferred = current
                
                output_path = await receive_task
                pbar.update(metadata['filesize'] - last_transferred)
            
            # Complete session
            requests.post(f"{self.api_base}/complete/{session_id}", json={
                'output_path': output_path,
                'checksum': metadata['checksum']
            })
            
            print(f"\n✅ Download complete!")
            print(f"   Saved to: {output_path}")
            
            # Decompress if needed
            if metadata.get('compression'):
                print(f"   Decompressing...")
                decompressed = CompressionManager.decompress_file(output_path)
                print(f"   Decompressed to: {decompressed}")
            
        except requests.RequestException as e:
            print(f"❌ API Error: {e}")
        except Exception as e:
            logger.exception("Error during receive")
            print(f"❌ Download failed: {e}")
    
    def discover_peers(self, timeout: int = 30):
        """Discover nearby peers"""
        print(f"🔍 Discovering peers for {timeout} seconds...")
        print("   Press Ctrl+C to stop\n")
        
        discovered_peers = []
        
        def on_peer_found(peer):
            discovered_peers.append(peer)
            print(f"✅ Found: {peer['device_name']} ({peer['ip']}:{peer['api_port']})")
        
        discovery = PeerDiscovery()
        discovery.start(on_peer_found=on_peer_found)
        
        try:
            import time
            time.sleep(timeout)
        except KeyboardInterrupt:
            print("\n")
        finally:
            discovery.stop()
        
        print(f"\n📊 Discovery complete: {len(discovered_peers)} peer(s) found")
        
        return discovered_peers
    
    def checksum(self, filepath: str):
        """Calculate file checksum"""
        filepath = Path(filepath)
        if not filepath.exists():
            print(f"❌ File not found: {filepath}")
            return
        
        print(f"🔐 Calculating checksum for: {filepath.name}")
        checksum = ChecksumManager.calculate_file_checksum(str(filepath))
        print(f"   SHA256: {checksum}")
        
        return checksum
    
    def split(self, filepath: str, num_parts: int, output_dir: Optional[str] = None):
        """Split file into chunks"""
        filepath = Path(filepath)
        if not filepath.exists():
            print(f"❌ File not found: {filepath}")
            return
        
        print(f"✂️  Splitting: {filepath.name}")
        print(f"   Into {num_parts} parts")
        
        chunks = FileChunker.split_file(str(filepath), num_parts, output_dir)
        
        print(f"\n✅ Created {len(chunks)} chunks:")
        for chunk in chunks:
            size = Path(chunk).stat().st_size
            print(f"   {Path(chunk).name} - {format_size(size)}")
    
    def merge(self, chunk_dir: str, output_file: str, num_parts: int):
        """Merge file chunks"""
        chunk_dir = Path(chunk_dir)
        if not chunk_dir.exists():
            print(f"❌ Directory not found: {chunk_dir}")
            return
        
        print(f"🔗 Merging {num_parts} chunks from: {chunk_dir}")
        
        output_path = FileChunker.merge_chunks(str(chunk_dir), output_file, num_parts)
        
        print(f"✅ Merged file: {output_path}")
        print(f"   Size: {format_size(Path(output_path).stat().st_size)}")
    
    def server(self, host: Optional[str] = None, port: Optional[int] = None):
        """Start API server"""
        from .app import app as flask_app
        
        host = host or config.API_HOST
        port = port or config.API_PORT
        
        print(f"🚀 Starting AirTrans API Server")
        print(f"   Host: {host}")
        print(f"   Port: {port}")
        print(f"   API: http://{host}:{port}")
        print(f"\n   Press Ctrl+C to stop\n")
        
        flask_app.run(host=host, port=port, debug=config.DEBUG)


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="AirTrans - Ultra-fast file transfer system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Send a file
  airtrans send video.mp4
  airtrans send large_file.zip --split 16 --compress
  
  # Receive a file
  airtrans receive --qr '{"ip":"192.168.1.10",...}'
  airtrans receive --metadata transfer.json
  
  # Discover peers
  airtrans discover
  
  # Start API server
  airtrans server
  
  # Utilities
  airtrans checksum file.bin
  airtrans split file.bin 8
  airtrans merge ./file.parts output.bin 8
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands', required=True)
    
    # Send command
    send_parser = subparsers.add_parser('send', help='Send a file')
    send_parser.add_argument('filepath', help='File to send')
    send_parser.add_argument('--split', type=int, help='Number of parts (auto if not specified)')
    send_parser.add_argument('--compress', action='store_true', help='Compress file before sending')
    send_parser.add_argument('--no-qr', action='store_true', help='Skip QR code generation')
    
    # Receive command
    recv_parser = subparsers.add_parser('receive', help='Receive a file')
    recv_parser.add_argument('--ip', help='Sender IP address (optional, overrides metadata)')
    recv_group = recv_parser.add_mutually_exclusive_group(required=True)
    recv_group.add_argument('--qr', help='QR code data (JSON string)')
    recv_group.add_argument('--metadata', help='Metadata JSON file')
    
    # Discover command
    disc_parser = subparsers.add_parser('discover', help='Discover nearby peers')
    disc_parser.add_argument('--timeout', type=int, default=30, help='Discovery timeout (seconds)')
    
    # Server command
    serv_parser = subparsers.add_parser('server', help='Start API server')
    serv_parser.add_argument('--host', help='Server host')
    serv_parser.add_argument('--port', type=int, help='Server port')
    
    # Checksum command
    check_parser = subparsers.add_parser('checksum', help='Calculate file checksum')
    check_parser.add_argument('filepath', help='File to checksum')
    
    # Split command
    split_parser = subparsers.add_parser('split', help='Split file into chunks')
    split_parser.add_argument('filepath', help='File to split')
    split_parser.add_argument('parts', type=int, help='Number of parts')
    split_parser.add_argument('--output', help='Output directory')
    
    # Merge command
    merge_parser = subparsers.add_parser('merge', help='Merge file chunks')
    merge_parser.add_argument('chunk_dir', help='Directory containing chunks')
    merge_parser.add_argument('output', help='Output file path')
    merge_parser.add_argument('parts', type=int, help='Number of parts')
    
    args = parser.parse_args()
    
    cli = AirTransCLI()
    
    try:
        if args.command == 'send':
            asyncio.run(cli.send_file(
                args.filepath, 
                args.split, 
                args.compress,
                args.no_qr
            ))
        
        elif args.command == 'receive':
            asyncio.run(cli.receive_file(
                args.ip,
                args.qr,
                args.metadata
            ))
        
        elif args.command == 'discover':
            cli.discover_peers(args.timeout)
        
        elif args.command == 'server':
            cli.server(args.host, args.port)
        
        elif args.command == 'checksum':
            cli.checksum(args.filepath)
        
        elif args.command == 'split':
            cli.split(args.filepath, args.parts, args.output)
        
        elif args.command == 'merge':
            cli.merge(args.chunk_dir, args.output, args.parts)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.exception("Unexpected error")
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
