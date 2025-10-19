"""
AirTrans Configuration Settings
"""

import os
from pathlib import Path


class Config:
    """Base configuration"""
    
    # Application
    APP_NAME = "AirTrans"
    VERSION = "1.0.0"
    DEBUG = os.getenv("AIRTRANS_DEBUG", "False").lower() == "true"
    
    # API Server
    API_HOST = os.getenv("AIRTRANS_API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("AIRTRANS_API_PORT", "8000"))
    
    # Transfer Settings
    BASE_PORT = int(os.getenv("AIRTRANS_BASE_PORT", "5001"))
    MAX_PORTS = int(os.getenv("AIRTRANS_MAX_PORTS", "32"))
    DEFAULT_NUM_PARTS = int(os.getenv("AIRTRANS_NUM_PARTS", "8"))
    
    # Optimal chunk size (100MB default)
    TARGET_CHUNK_SIZE = int(os.getenv("AIRTRANS_CHUNK_SIZE", str(100 * 1024 * 1024)))
    
    # Transfer timeout in seconds
    TRANSFER_TIMEOUT = int(os.getenv("AIRTRANS_TIMEOUT", "300"))
    
    # File paths
    TEMP_DIR = Path(os.getenv("AIRTRANS_TEMP_DIR", "/tmp/airtrans"))
    DOWNLOAD_DIR = Path(os.getenv("AIRTRANS_DOWNLOAD_DIR", str(Path.home() / "Downloads" / "AirTrans")))
    
    # Create directories if they don't exist
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    
    # Compression
    ENABLE_COMPRESSION = os.getenv("AIRTRANS_COMPRESSION", "False").lower() == "true"
    COMPRESSION_THRESHOLD = int(os.getenv("AIRTRANS_COMPRESSION_THRESHOLD", str(10 * 1024 * 1024)))  # 10MB
    
    # Security
    CHECKSUM_ALGORITHM = os.getenv("AIRTRANS_CHECKSUM", "sha256")
    VERIFY_CHECKSUMS = True
    
    # Discovery
    DISCOVERY_PORT = int(os.getenv("AIRTRANS_DISCOVERY_PORT", "37020"))
    MULTICAST_GROUP = os.getenv("AIRTRANS_MULTICAST_GROUP", "224.0.0.251")
    MULTICAST_PORT = int(os.getenv("AIRTRANS_MULTICAST_PORT", "37021"))
    DISCOVERY_INTERVAL = int(os.getenv("AIRTRANS_DISCOVERY_INTERVAL", "5"))  # seconds
    PEER_TIMEOUT = int(os.getenv("AIRTRANS_PEER_TIMEOUT", "30"))  # seconds
    
    # Performance
    BUFFER_SIZE = int(os.getenv("AIRTRANS_BUFFER_SIZE", str(1024 * 1024)))  # 1MB
    MAX_CONCURRENT_TRANSFERS = int(os.getenv("AIRTRANS_MAX_TRANSFERS", "5"))
    TCP_NODELAY = True  # Disable Nagle's algorithm for lower latency
    TCP_QUICKACK = True  # Enable TCP quick ack
    
    # Logging
    LOG_LEVEL = os.getenv("AIRTRANS_LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("AIRTRANS_LOG_FILE", None)
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # QR Code
    QR_ERROR_CORRECTION = "L"  # L, M, Q, H
    QR_BOX_SIZE = 10
    QR_BORDER = 4
    
    # Session management
    SESSION_TIMEOUT = int(os.getenv("AIRTRANS_SESSION_TIMEOUT", "3600"))  # 1 hour
    MAX_SESSIONS = int(os.getenv("AIRTRANS_MAX_SESSIONS", "100"))
    
    # Network
    MAX_RETRIES = int(os.getenv("AIRTRANS_MAX_RETRIES", "3"))
    RETRY_DELAY = int(os.getenv("AIRTRANS_RETRY_DELAY", "5"))  # seconds
    CONNECTION_TIMEOUT = int(os.getenv("AIRTRANS_CONN_TIMEOUT", "10"))  # seconds
    
    @classmethod
    def get_optimal_parts(cls, filesize: int) -> int:
        """Calculate optimal number of parts based on file size"""
        if filesize < cls.TARGET_CHUNK_SIZE:
            return 1
        
        num_parts = min(cls.MAX_PORTS, max(1, filesize // cls.TARGET_CHUNK_SIZE))
        return num_parts
    
    @classmethod
    def format_bytes(cls, size: int) -> str:
        """Format bytes into human-readable string"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"
    
    @classmethod
    def validate(cls):
        """Validate configuration"""
        errors = []
        
        if cls.BASE_PORT < 1024 or cls.BASE_PORT > 65535 - cls.MAX_PORTS:
            errors.append(f"Invalid BASE_PORT: {cls.BASE_PORT}")
        
        if cls.MAX_PORTS < 1 or cls.MAX_PORTS > 64:
            errors.append(f"Invalid MAX_PORTS: {cls.MAX_PORTS}")
        
        if cls.DEFAULT_NUM_PARTS < 1 or cls.DEFAULT_NUM_PARTS > cls.MAX_PORTS:
            errors.append(f"Invalid DEFAULT_NUM_PARTS: {cls.DEFAULT_NUM_PARTS}")
        
        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")
        
        return True


class DevelopmentConfig(Config):
    """Development environment configuration"""
    DEBUG = True
    LOG_LEVEL = "DEBUG"


class ProductionConfig(Config):
    """Production environment configuration"""
    DEBUG = False
    LOG_LEVEL = "INFO"
    VERIFY_CHECKSUMS = True


class TestConfig(Config):
    """Test environment configuration"""
    DEBUG = True
    TEMP_DIR = Path("/tmp/airtrans_test")
    DOWNLOAD_DIR = Path("/tmp/airtrans_test/downloads")
    LOG_LEVEL = "DEBUG"


# Select config based on environment
ENV = os.getenv("AIRTRANS_ENV", "development").lower()

if ENV == "production":
    config = ProductionConfig()
elif ENV == "test":
    config = TestConfig()
else:
    config = DevelopmentConfig()

# Validate on import
config.validate()


# Export commonly used settings
API_HOST = config.API_HOST
API_PORT = config.API_PORT
BASE_PORT = config.BASE_PORT
DEFAULT_NUM_PARTS = config.DEFAULT_NUM_PARTS
TEMP_DIR = config.TEMP_DIR
DOWNLOAD_DIR = config.DOWNLOAD_DIR