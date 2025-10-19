"""
AirTrans Peer Discovery - UDP broadcast for finding nearby devices
"""

import socket
import json
import threading
import time
from typing import Dict, List, Callable, Optional
import logging

logger = logging.getLogger(__name__)


class PeerDiscovery:
    """Handle peer discovery via UDP broadcast"""
    
    BROADCAST_PORT = 37020
    DISCOVERY_MESSAGE = "AIRTRANS_DISCOVERY"
    RESPONSE_MESSAGE = "AIRTRANS_PEER"
    
    def __init__(self, device_name: str = None, api_port: int = 8000):
        self.device_name = device_name or socket.gethostname()
        self.api_port = api_port
        self.peers: Dict[str, Dict] = {}
        self.running = False
        self.listen_thread = None
        self.announce_thread = None
        
    def get_local_ip(self) -> str:
        """Get local IP address"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    def start(self, on_peer_found: Optional[Callable] = None):
        """
        Start discovery service
        
        Args:
            on_peer_found: Callback function called when new peer is discovered
        """
        if self.running:
            logger.warning("Discovery already running")
            return
        
        self.running = True
        self.on_peer_found = on_peer_found
        
        # Start listener thread
        self.listen_thread = threading.Thread(target=self._listen_for_peers, daemon=True)
        self.listen_thread.start()
        
        # Start announcer thread
        self.announce_thread = threading.Thread(target=self._announce_presence, daemon=True)
        self.announce_thread.start()
        
        logger.info(f"Peer discovery started on port {self.BROADCAST_PORT}")
    
    def stop(self):
        """Stop discovery service"""
        self.running = False
        if self.listen_thread:
            self.listen_thread.join(timeout=2)
        if self.announce_thread:
            self.announce_thread.join(timeout=2)
        logger.info("Peer discovery stopped")
    
    def _listen_for_peers(self):
        """Listen for discovery broadcasts from other peers"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', self.BROADCAST_PORT))
        sock.settimeout(1.0)
        
        logger.info(f"Listening for peers on port {self.BROADCAST_PORT}")
        
        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                message = data.decode('utf-8')
                
                if message.startswith(self.DISCOVERY_MESSAGE):
                    # Received discovery request - send response
                    self._send_peer_response(sock, addr[0])
                    
                elif message.startswith(self.RESPONSE_MESSAGE):
                    # Received peer information
                    self._process_peer_info(message, addr[0])
                    
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"Error in discovery listener: {e}")
        
        sock.close()
    
    def _send_peer_response(self, sock: socket.socket, peer_ip: str):
        """Send peer information in response to discovery"""
        peer_info = {
            'type': self.RESPONSE_MESSAGE,
            'device_name': self.device_name,
            'ip': self.get_local_ip(),
            'api_port': self.api_port,
            'timestamp': time.time()
        }
        
        response = json.dumps(peer_info)
        try:
            sock.sendto(response.encode('utf-8'), (peer_ip, self.BROADCAST_PORT))
            logger.debug(f"Sent peer response to {peer_ip}")
        except Exception as e:
            logger.error(f"Error sending peer response: {e}")
    
    def _process_peer_info(self, message: str, peer_ip: str):
        """Process received peer information"""
        try:
            # Parse JSON from message
            json_start = message.index('{')
            peer_data = json.loads(message[json_start:])
            
            peer_id = peer_data['ip']
            
            # Check if this is a new peer
            is_new = peer_id not in self.peers
            
            # Update peer information
            self.peers[peer_id] = {
                'device_name': peer_data.get('device_name', 'Unknown'),
                'ip': peer_data['ip'],
                'api_port': peer_data.get('api_port', 8000),
                'last_seen': time.time()
            }
            
            if is_new:
                logger.info(f"Discovered peer: {peer_data['device_name']} ({peer_id})")
                if self.on_peer_found:
                    self.on_peer_found(self.peers[peer_id])
            
        except Exception as e:
            logger.error(f"Error processing peer info: {e}")
    
    def _announce_presence(self):
        """Periodically broadcast discovery message"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        while self.running:
            try:
                # Send discovery broadcast
                message = f"{self.DISCOVERY_MESSAGE}:{self.device_name}"
                sock.sendto(message.encode('utf-8'), 
                           ('<broadcast>', self.BROADCAST_PORT))
                
                # Also send peer info directly
                peer_info = {
                    'type': self.RESPONSE_MESSAGE,
                    'device_name': self.device_name,
                    'ip': self.get_local_ip(),
                    'api_port': self.api_port,
                    'timestamp': time.time()
                }
                info_message = json.dumps(peer_info)
                sock.sendto(info_message.encode('utf-8'),
                           ('<broadcast>', self.BROADCAST_PORT))
                
                logger.debug("Broadcast discovery announcement")
                
            except Exception as e:
                logger.error(f"Error in announce: {e}")
            
            # Wait before next announcement
            time.sleep(5)
        
        sock.close()
    
    def get_peers(self) -> List[Dict]:
        """
        Get list of discovered peers
        
        Returns:
            List of peer dictionaries
        """
        # Remove stale peers (not seen in 30 seconds)
        current_time = time.time()
        stale_peers = [
            peer_id for peer_id, peer in self.peers.items()
            if current_time - peer['last_seen'] > 30
        ]
        
        for peer_id in stale_peers:
            logger.info(f"Removing stale peer: {peer_id}")
            del self.peers[peer_id]
        
        return list(self.peers.values())
    
    def find_peer_by_name(self, device_name: str) -> Optional[Dict]:
        """Find peer by device name"""
        for peer in self.peers.values():
            if peer['device_name'] == device_name:
                return peer
        return None


class MulticastDiscovery:
    """Alternative discovery using multicast (more reliable on some networks)"""
    
    MULTICAST_GROUP = '224.0.0.251'
    MULTICAST_PORT = 37021
    
    def __init__(self, device_name: str = None, api_port: int = 8000):
        self.device_name = device_name or socket.gethostname()
        self.api_port = api_port
        self.peers: Dict[str, Dict] = {}
        self.running = False
        
    def start(self):
        """Start multicast discovery"""
        self.running = True
        self.listen_thread = threading.Thread(target=self._listen, daemon=True)
        self.announce_thread = threading.Thread(target=self._announce, daemon=True)
        self.listen_thread.start()
        self.announce_thread.start()
        logger.info("Multicast discovery started")
    
    def stop(self):
        """Stop multicast discovery"""
        self.running = False
        if self.listen_thread:
            self.listen_thread.join(timeout=2)
        if self.announce_thread:
            self.announce_thread.join(timeout=2)
    
    def _listen(self):
        """Listen for multicast messages"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Bind to the port
        sock.bind(('', self.MULTICAST_PORT))
        
        # Join multicast group
        mreq = socket.inet_aton(self.MULTICAST_GROUP) + socket.inet_aton('0.0.0.0')
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(1.0)
        
        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                peer_info = json.loads(data.decode('utf-8'))
                
                # Don't add ourselves
                if peer_info['device_name'] != self.device_name:
                    peer_id = peer_info['ip']
                    self.peers[peer_id] = peer_info
                    self.peers[peer_id]['last_seen'] = time.time()
                    
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"Multicast listen error: {e}")
        
        sock.close()
    
    def _announce(self):
        """Announce presence via multicast"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        
        while self.running:
            try:
                peer_info = {
                    'device_name': self.device_name,
                    'ip': self._get_local_ip(),
                    'api_port': self.api_port,
                    'timestamp': time.time()
                }
                
                message = json.dumps(peer_info).encode('utf-8')
                sock.sendto(message, (self.MULTICAST_GROUP, self.MULTICAST_PORT))
                
            except Exception as e:
                logger.error(f"Multicast announce error: {e}")
            
            time.sleep(5)
        
        sock.close()
    
    def _get_local_ip(self) -> str:
        """Get local IP"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    def get_peers(self) -> List[Dict]:
        """Get discovered peers"""
        current_time = time.time()
        active_peers = [
            peer for peer in self.peers.values()
            if current_time - peer['last_seen'] < 30
        ]
        return active_peers


# Example usage
if __name__ == "__main__":
    def on_peer_discovered(peer):
        print(f"Found peer: {peer['device_name']} at {peer['ip']}")
    
    discovery = PeerDiscovery(device_name="MyDevice")
    discovery.start(on_peer_found=on_peer_discovered)
    
    try:
        print("Discovering peers... Press Ctrl+C to stop")
        while True:
            time.sleep(10)
            peers = discovery.get_peers()
            print(f"\nActive peers: {len(peers)}")
            for peer in peers:
                print(f"  - {peer['device_name']} ({peer['ip']})")
    except KeyboardInterrupt:
        print("\nStopping discovery...")
        discovery.stop()