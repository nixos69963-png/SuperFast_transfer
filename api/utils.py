"""
AirTrans Utilities - File chunking, merging, compression, and integrity checks
"""

import hashlib
import lz4.frame
from pathlib import Path
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class FileChunker:
    """Handles splitting large files into chunks"""
    
    @staticmethod
    def split_file(filepath: str, num_parts: int, output_dir: Optional[str] = None) -> List[str]:
        """
        Split a file into N equal parts
        
        Args:
            filepath: Path to the file to split
            num_parts: Number of chunks to create
            output_dir: Directory to save chunks (defaults to filepath.parts/)
        
        Returns:
            List of chunk file paths
        """
        filepath = Path(filepath)
        filesize = filepath.stat().st_size
        
        if output_dir is None:
            output_dir = filepath.parent / f"{filepath.stem}.parts"
        else:
            output_dir = Path(output_dir)
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        chunk_size = filesize // num_parts
        chunk_paths = []
        
        logger.info(f"Splitting {filepath.name} ({filesize} bytes) into {num_parts} parts")
        
        with open(filepath, 'rb') as infile:
            for i in range(num_parts):
                chunk_path = output_dir / f"{filepath.stem}.part{i:04d}"
                
                # Calculate size for this chunk
                current_chunk_size = chunk_size
                if i == num_parts - 1:
                    # Last chunk gets any remaining bytes
                    current_chunk_size = filesize - (chunk_size * (num_parts - 1))
                
                # Read and write chunk
                chunk_data = infile.read(current_chunk_size)
                with open(chunk_path, 'wb') as outfile:
                    outfile.write(chunk_data)
                
                chunk_paths.append(str(chunk_path))
                logger.info(f"Created chunk {i}: {chunk_path.name} ({len(chunk_data)} bytes)")
        
        return chunk_paths
    
    @staticmethod
    def merge_chunks(chunk_dir: str, output_filepath: str, num_parts: int) -> str:
        """
        Merge file chunks back into a single file
        
        Args:
            chunk_dir: Directory containing chunk files
            output_filepath: Path where merged file should be saved
            num_parts: Number of chunks to merge
        
        Returns:
            Path to the merged file
        """
        chunk_dir = Path(chunk_dir)
        output_path = Path(output_filepath)
        
        logger.info(f"Merging {num_parts} chunks into {output_path.name}")
        
        with open(output_path, 'wb') as outfile:
            for i in range(num_parts):
                # Find chunk file
                chunk_files = list(chunk_dir.glob(f"*.part{i:04d}"))
                if not chunk_files:
                    raise FileNotFoundError(f"Chunk {i} not found in {chunk_dir}")
                
                chunk_path = chunk_files[0]
                with open(chunk_path, 'rb') as infile:
                    chunk_data = infile.read()
                    outfile.write(chunk_data)
                    logger.info(f"Merged chunk {i}: {chunk_path.name}")
        
        logger.info(f"Merge complete: {output_path}")
        return str(output_path)


class ChecksumManager:
    """Handles file integrity verification"""
    
    @staticmethod
    def calculate_file_checksum(filepath: str, algorithm: str = 'sha256') -> str:
        """
        Calculate checksum for entire file
        
        Args:
            filepath: Path to file
            algorithm: Hash algorithm (sha256, sha1, md5)
        
        Returns:
            Hex digest of the hash
        """
        hash_obj = hashlib.new(algorithm)
        
        with open(filepath, 'rb') as f:
            # Read in chunks to handle large files
            for chunk in iter(lambda: f.read(8192), b''):
                hash_obj.update(chunk)
        
        return hash_obj.hexdigest()
    
    @staticmethod
    def calculate_chunk_checksums(filepath: str, num_parts: int) -> List[str]:
        """
        Calculate checksums for each chunk of a file
        
        Returns:
            List of checksums, one per chunk
        """
        filesize = Path(filepath).stat().st_size
        chunk_size = filesize // num_parts
        checksums = []
        
        with open(filepath, 'rb') as f:
            for i in range(num_parts):
                current_chunk_size = chunk_size
                if i == num_parts - 1:
                    current_chunk_size = filesize - (chunk_size * (num_parts - 1))
                
                chunk_data = f.read(current_chunk_size)
                checksum = hashlib.sha256(chunk_data).hexdigest()
                checksums.append(checksum)
        
        return checksums
    
    @staticmethod
    def verify_file(filepath: str, expected_checksum: str, algorithm: str = 'sha256') -> bool:
        """
        Verify file integrity against expected checksum
        
        Returns:
            True if checksums match, False otherwise
        """
        actual_checksum = ChecksumManager.calculate_file_checksum(filepath, algorithm)
        match = actual_checksum == expected_checksum
        
        if match:
            logger.info(f"✓ Checksum verified: {filepath}")
        else:
            logger.error(f"✗ Checksum mismatch for {filepath}")
            logger.error(f"  Expected: {expected_checksum}")
            logger.error(f"  Got:      {actual_checksum}")
        
        return match


class CompressionManager:
    """Handles optional file compression using LZ4 for speed"""
    
    @staticmethod
    def compress_file(filepath: str, output_path: Optional[str] = None) -> str:
        """
        Compress file using LZ4 (fast compression)
        
        Args:
            filepath: Path to file to compress
            output_path: Output path (defaults to filepath.lz4)
        
        Returns:
            Path to compressed file
        """
        filepath = Path(filepath)
        if output_path is None:
            output_path = filepath.with_suffix(filepath.suffix + '.lz4')
        else:
            output_path = Path(output_path)
        
        logger.info(f"Compressing {filepath.name} with LZ4")
        
        with open(filepath, 'rb') as infile:
            with lz4.frame.open(output_path, 'wb') as outfile:
                # Compress in chunks
                while True:
                    chunk = infile.read(1024 * 1024)  # 1MB chunks
                    if not chunk:
                        break
                    outfile.write(chunk)
        
        original_size = filepath.stat().st_size
        compressed_size = output_path.stat().st_size
        ratio = (1 - compressed_size / original_size) * 100
        
        logger.info(f"Compression complete: {original_size} → {compressed_size} bytes ({ratio:.1f}% reduction)")
        
        return str(output_path)
    
    @staticmethod
    def decompress_file(filepath: str, output_path: Optional[str] = None) -> str:
        """
        Decompress LZ4 file
        
        Args:
            filepath: Path to compressed file
            output_path: Output path (defaults to removing .lz4 extension)
        
        Returns:
            Path to decompressed file
        """
        filepath = Path(filepath)
        if output_path is None:
            output_path = filepath.with_suffix('')
        else:
            output_path = Path(output_path)
        
        logger.info(f"Decompressing {filepath.name}")
        
        with lz4.frame.open(filepath, 'rb') as infile:
            with open(output_path, 'wb') as outfile:
                while True:
                    chunk = infile.read(1024 * 1024)
                    if not chunk:
                        break
                    outfile.write(chunk)
        
        logger.info(f"Decompression complete: {output_path}")
        
        return str(output_path)
    
    @staticmethod
    def compress_data(data: bytes) -> bytes:
        """Compress bytes in memory"""
        return lz4.frame.compress(data)
    
    @staticmethod
    def decompress_data(data: bytes) -> bytes:
        """Decompress bytes in memory"""
        return lz4.frame.decompress(data)


class TransferMetadata:
    """Helper for creating and parsing transfer metadata"""
    
    @staticmethod
    def create_metadata(filepath: str, ip: str, ports: List[int], 
                       num_parts: int, use_compression: bool = False) -> Dict:
        """
        Create metadata dictionary for transfer session
        
        Returns:
            Dictionary containing all transfer information
        """
        filepath = Path(filepath)
        filesize = filepath.stat().st_size
        checksum = ChecksumManager.calculate_file_checksum(str(filepath))
        chunk_checksums = ChecksumManager.calculate_chunk_checksums(str(filepath), num_parts)
        
        metadata = {
            'filename': filepath.name,
            'filesize': filesize,
            'ip': ip,
            'ports': ports,
            'num_parts': num_parts,
            'checksum': checksum,
            'chunk_checksums': chunk_checksums,
            'compression': use_compression,
            'version': '1.0'
        }
        
        return metadata
    
    @staticmethod
    def validate_metadata(metadata: Dict) -> bool:
        """
        Validate metadata has all required fields
        
        Returns:
            True if valid, False otherwise
        """
        required_fields = ['filename', 'filesize', 'ip', 'ports', 'num_parts', 'checksum']
        
        for field in required_fields:
            if field not in metadata:
                logger.error(f"Missing required field: {field}")
                return False
        
        if not isinstance(metadata['ports'], list) or len(metadata['ports']) != metadata['num_parts']:
            logger.error("Invalid ports configuration")
            return False
        
        return True


def format_size(size_bytes: int) -> str:
    """Format bytes into human-readable string"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def calculate_optimal_chunks(filesize: int, target_chunk_size: int = 100 * 1024 * 1024) -> int:
    """
    Calculate optimal number of chunks based on file size
    
    Args:
        filesize: File size in bytes
        target_chunk_size: Target size per chunk (default 100MB)
    
    Returns:
        Recommended number of chunks (1-32)
    """
    num_chunks = max(1, min(32, filesize // target_chunk_size))
    return num_chunks


# Example usage
if __name__ == "__main__":
    # Test file operations
    test_file = "test_large_file.bin"
    
    # Create a test file
    print(f"Creating test file: {test_file}")
    with open(test_file, 'wb') as f:
        f.write(b'X' * (100 * 1024 * 1024))  # 100MB test file
    
    # Calculate checksum
    print("\nCalculating checksum...")
    checksum = ChecksumManager.calculate_file_checksum(test_file)
    print(f"SHA256: {checksum}")
    
    # Split file
    print("\nSplitting file...")
    chunks = FileChunker.split_file(test_file, num_parts=4)
    print(f"Created {len(chunks)} chunks")
    
    # Merge file
    print("\nMerging file...")
    merged = FileChunker.merge_chunks("test_large_file.parts", "test_merged.bin", 4)
    
    # Verify
    print("\nVerifying...")
    is_valid = ChecksumManager.verify_file(merged, checksum)
    print(f"Verification: {'PASSED' if is_valid else 'FAILED'}")