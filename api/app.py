"""
AirTrans Flask API - REST endpoints for QR generation, session management, and transfer control
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import qrcode
import json
import uuid
from pathlib import Path
from typing import Dict
import io
import socket
import logging

from api.utils import TransferMetadata, ChecksumManager, format_size

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory session storage (use Redis in production)
sessions: Dict[str, Dict] = {}


def get_local_ip() -> str:
    """Get local IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'AirTrans API',
        'version': '1.0'
    })


@app.route('/create-session', methods=['POST'])
def create_session():
    """
    Create a new transfer session and generate QR code
    
    Expected JSON body:
    {
        "filepath": "/path/to/file.mp4",
        "num_parts": 8,
        "base_port": 5001,
        "compression": false
    }
    
    Returns:
    {
        "session_id": "uuid",
        "metadata": {...},
        "qr_code_url": "/qr/<session_id>"
    }
    """
    try:
        data = request.get_json()
        
        # Validate input
        if 'filepath' not in data:
            return jsonify({'error': 'filepath is required'}), 400
        
        filepath = Path(data['filepath'])
        if not filepath.exists():
            return jsonify({'error': f'File not found: {filepath}'}), 404
        
        # Extract parameters
        num_parts = data.get('num_parts', 8)
        base_port = data.get('base_port', 5001)
        use_compression = data.get('compression', False)
        
        # Generate ports
        ports = [base_port + i for i in range(num_parts)]
        
        # Get local IP
        ip = get_local_ip()
        
        # Create metadata
        metadata = TransferMetadata.create_metadata(
            str(filepath), ip, ports, num_parts, use_compression
        )
        
        # Generate session ID
        session_id = str(uuid.uuid4())
        
        # Store session
        sessions[session_id] = {
            'metadata': metadata,
            'status': 'pending',
            'created_at': None,
            'progress': {i: 0 for i in range(num_parts)},
            'filepath': str(filepath)
        }
        
        logger.info(f"Created session {session_id} for {filepath.name}")
        
        return jsonify({
            'session_id': session_id,
            'metadata': metadata,
            'qr_code_url': f'/qr/{session_id}',
            'filesize_human': format_size(metadata['filesize'])
        }), 201
        
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/qr/<session_id>', methods=['GET'])
def generate_qr_code(session_id: str):
    """
    Generate QR code image for a session
    
    Returns PNG image of QR code containing transfer metadata
    """
    if session_id not in sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    try:
        session = sessions[session_id]
        metadata = session['metadata']
        
        # Create QR code with metadata as JSON
        qr_data = json.dumps(metadata)
        
        qr = qrcode.QRCode(
            version=None,  # Auto-size
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Save to bytes buffer
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        return send_file(img_buffer, mimetype='image/png')
        
    except Exception as e:
        logger.error(f"Error generating QR code: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/join-session', methods=['POST'])
def join_session():
    """
    Receiver joins a session using scanned QR metadata
    
    Expected JSON body:
    {
        "metadata": {...}  // Parsed from QR code
    }
    
    Returns:
    {
        "session_id": "uuid",
        "status": "ready",
        "instructions": "..."
    }
    """
    try:
        data = request.get_json()
        
        if 'metadata' not in data:
            return jsonify({'error': 'metadata is required'}), 400
        
        metadata = data['metadata']
        
        # Validate metadata
        if not TransferMetadata.validate_metadata(metadata):
            return jsonify({'error': 'Invalid metadata'}), 400
        
        # Create receiver session
        session_id = str(uuid.uuid4())
        sessions[session_id] = {
            'metadata': metadata,
            'status': 'ready',
            'role': 'receiver',
            'progress': {i: 0 for i in range(metadata['num_parts'])}
        }
        
        logger.info(f"Receiver joined session {session_id}")
        
        return jsonify({
            'session_id': session_id,
            'status': 'ready',
            'sender_ip': metadata['ip'],
            'ports': metadata['ports'],
            'filename': metadata['filename'],
            'filesize': metadata['filesize'],
            'instructions': f"Ready to receive {metadata['filename']} from {metadata['ip']}"
        }), 200
        
    except Exception as e:
        logger.error(f"Error joining session: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/progress/<session_id>', methods=['GET'])
def get_progress(session_id: str):
    """
    Get real-time progress for a transfer session
    
    Returns:
    {
        "session_id": "uuid",
        "status": "transferring",
        "progress": {...},
        "total_transferred": 12345,
        "percentage": 45.2
    }
    """
    if session_id not in sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    session = sessions[session_id]
    metadata = session['metadata']
    total_transferred = sum(session['progress'].values())
    percentage = (total_transferred / metadata['filesize']) * 100
    
    return jsonify({
        'session_id': session_id,
        'status': session['status'],
        'progress': session['progress'],
        'total_transferred': total_transferred,
        'filesize': metadata['filesize'],
        'percentage': round(percentage, 2),
        'num_parts': metadata['num_parts']
    })


@app.route('/update-progress/<session_id>', methods=['POST'])
def update_progress(session_id: str):
    """
    Update progress for a specific chunk
    
    Expected JSON body:
    {
        "chunk_id": 0,
        "bytes_transferred": 12345
    }
    """
    if session_id not in sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    try:
        data = request.get_json()
        chunk_id = data.get('chunk_id')
        bytes_transferred = data.get('bytes_transferred')
        
        if chunk_id is None or bytes_transferred is None:
            return jsonify({'error': 'chunk_id and bytes_transferred required'}), 400
        
        session = sessions[session_id]
        session['progress'][chunk_id] = bytes_transferred
        
        # Check if all chunks complete
        metadata = session['metadata']
        total_transferred = sum(session['progress'].values())
        
        if total_transferred >= metadata['filesize']:
            session['status'] = 'completed'
        else:
            session['status'] = 'transferring'
        
        return jsonify({'status': 'updated'})
        
    except Exception as e:
        logger.error(f"Error updating progress: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/complete/<session_id>', methods=['POST'])
def complete_transfer(session_id: str):
    """
    Mark transfer as complete and verify integrity
    
    Expected JSON body:
    {
        "output_path": "/path/to/received/file",
        "checksum": "sha256..."
    }
    
    Returns:
    {
        "status": "verified",
        "checksum_match": true
    }
    """
    if session_id not in sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    try:
        data = request.get_json()
        output_path = data.get('output_path')
        received_checksum = data.get('checksum')
        
        session = sessions[session_id]
        expected_checksum = session['metadata']['checksum']
        
        # Verify checksum if file path provided
        checksum_match = None
        if output_path:
            checksum_match = ChecksumManager.verify_file(output_path, expected_checksum)
        elif received_checksum:
            checksum_match = received_checksum == expected_checksum
        
        session['status'] = 'completed' if checksum_match else 'failed'
        
        return jsonify({
            'status': session['status'],
            'checksum_match': checksum_match,
            'expected_checksum': expected_checksum
        })
        
    except Exception as e:
        logger.error(f"Error completing transfer: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/sessions', methods=['GET'])
def list_sessions():
    """List all active sessions"""
    session_list = []
    for sid, session in sessions.items():
        session_list.append({
            'session_id': sid,
            'filename': session['metadata']['filename'],
            'filesize': session['metadata']['filesize'],
            'status': session['status'],
            'num_parts': session['metadata']['num_parts']
        })
    
    return jsonify({'sessions': session_list, 'count': len(session_list)})


@app.route('/session/<session_id>', methods=['DELETE'])
def delete_session(session_id: str):
    """Delete a session"""
    if session_id not in sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    del sessions[session_id]
    logger.info(f"Deleted session {session_id}")
    
    return jsonify({'status': 'deleted'})


@app.route('/session/<session_id>', methods=['GET'])
def get_session(session_id: str):
    """Get detailed session information"""
    if session_id not in sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    session = sessions[session_id]
    return jsonify({
        'session_id': session_id,
        'metadata': session['metadata'],
        'status': session['status'],
        'progress': session['progress']
    })


# QR Scanner helper endpoint
@app.route('/scan-qr', methods=['POST'])
def scan_qr():
    """
    Parse QR code data from uploaded image
    
    Expected: multipart/form-data with 'image' file
    
    Returns parsed metadata
    """
    try:
        from PIL import Image
        from pyzbar.pyzbar import decode
        
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        img = Image.open(file.stream)
        
        # Decode QR code
        decoded_objects = decode(img)
        
        if not decoded_objects:
            return jsonify({'error': 'No QR code found in image'}), 400
        
        qr_data = decoded_objects[0].data.decode('utf-8')
        metadata = json.loads(qr_data)
        
        return jsonify({
            'success': True,
            'metadata': metadata
        })
        
    except ImportError:
        return jsonify({
            'error': 'QR scanning requires pillow and pyzbar packages',
            'install': 'pip install pillow pyzbar'
        }), 501
    except Exception as e:
        logger.error(f"Error scanning QR: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    logger.info("Starting AirTrans API server...")
    logger.info(f"Local IP: {get_local_ip()}")
    app.run(host='0.0.0.0', port=8000, debug=True)