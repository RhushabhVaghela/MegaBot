import argparse
import os
import shutil
import zlib

from cryptography.fernet import Fernet


def restore_backup(backup_path: str, output_path: str, encryption_key: str):
    """Decrypt and decompress a MegaBot memory backup."""
    try:
        if not os.path.exists(backup_path):
            print(f"Error: Backup file not found: {backup_path}")
            return

        fernet = Fernet(
            encryption_key.encode()
            if isinstance(encryption_key, str)
            else encryption_key
        )

        print(f"Reading encrypted backup: {backup_path}...")
        with open(backup_path, "rb") as f:
            encrypted_data = f.read()

        print("Decrypting data...")
        compressed_data = fernet.decrypt(encrypted_data)

        print("Decompressing data...")
        data = zlib.decompress(compressed_data)

        # Ensure target directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        # If output file exists, create a safety copy of IT first
        if os.path.exists(output_path):
            safety_copy = f"{output_path}.old"
            shutil.copy2(output_path, safety_copy)
            print(f"Existing database backed up to: {safety_copy}")

        print(f"Restoring to: {output_path}...")
        with open(output_path, "wb") as f:
            f.write(data)

        print("✅ Restore completed successfully.")

    except Exception as e:
        print(f"❌ Restore failed: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore MegaBot Memory Backup")
    parser.add_argument("backup", help="Path to the .enc backup file")
    parser.add_argument(
        "--output",
        default="megabot_memory.db",
        help="Path to restore the database to (default: megabot_memory.db)",
    )
    parser.add_argument(
        "--key", help="Encryption key (overrides MEGABOT_BACKUP_KEY env var)"
    )

    args = parser.parse_args()

    key = args.key or os.environ.get("MEGABOT_BACKUP_KEY")
    if not key:
        print(
            "Error: No encryption key provided. Use --key or set MEGABOT_BACKUP_KEY environment variable."
        )
    else:
        restore_backup(args.backup, args.output, key)
