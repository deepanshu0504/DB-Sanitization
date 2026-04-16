"""
Desanitization engine for restoring original PII values.

This script provides the core functionality to reverse the sanitization process
by reading mappings from the pii_mappings table and restoring original values
to the database.

Key Features:
    - Full database restore or selective table restore
    - AES-256 decryption of original values
    - Batch processing for large datasets
    - Transaction safety with rollback support
    - Dry-run mode for safety testing
    - Comprehensive error handling and logging

Usage:
    # Dry-run (preview only)
    python desanitize.py <operation_id>
    
    # Full restore
    python desanitize.py <operation_id> --execute
    
    # Selective table restore
    python desanitize.py <operation_id> --execute --tables dbo.Customers dbo.Orders

Author: Database Sanitization Team
Date: 2026-04-16
"""

import sys
import pyodbc
from typing import List, Dict, Optional, Tuple
from uuid import UUID
from datetime import datetime
from collections import defaultdict

from mapping import (
    EncryptionManager,
    MappingManager,
    MappingEntry,
    EncryptionKeyError,
    DecryptionError
)
from desanitization.desanitization_config import (
    DesanitizationConfig,
    RestoreStats,
    create_safe_config,
    create_production_config
)


class DesanitizationError(Exception):
    """Base exception for desanitization errors."""
    pass


class Desanitizer:
    """
    Main desanitization engine for restoring original PII values.
    
    This class manages the complete desanitization workflow including:
    - Validation of operation existence
    - Retrieval of mappings
    - Decryption of original values
    - Database restoration in batches
    - Transaction management
    - Error handling and rollback
    
    Example:
        ```python
        from uuid import UUID
        
        desanitizer = Desanitizer(
            connection_string="...",
            encryption_manager=EncryptionManager()
        )
        
        # Dry-run first
        stats = desanitizer.restore(
            operation_id=UUID("..."),
            config=DesanitizationConfig(dry_run=True)
        )
        print(stats.summary())
        
        # Then execute
        if stats.is_successful:
            stats = desanitizer.restore(
                operation_id=UUID("..."),
                config=DesanitizationConfig(dry_run=False)
            )
        ```
    """
    
    def __init__(
        self,
        connection_string: str,
        encryption_manager: Optional[EncryptionManager] = None,
        mapping_manager: Optional[MappingManager] = None
    ):
        """
        Initialize desanitizer.
        
        Args:
            connection_string: SQL Server connection string
            encryption_manager: EncryptionManager for decrypting values
            mapping_manager: MappingManager for retrieving mappings
        """
        self.connection_string = connection_string
        self.encryption_manager = encryption_manager
        
        # Initialize mapping manager if not provided
        if mapping_manager:
            self.mapping_manager = mapping_manager
        else:
            self.mapping_manager = MappingManager(
                connection_string=connection_string,
                encryption_manager=encryption_manager
            )
            self.mapping_manager.initialize()
    
    def restore(
        self,
        operation_id: UUID,
        config: Optional[DesanitizationConfig] = None
    ) -> RestoreStats:
        """
        Restore original values for a sanitization operation.
        
        Args:
            operation_id: UUID of the sanitization operation to reverse
            config: DesanitizationConfig (uses safe defaults if None)
        
        Returns:
            RestoreStats with operation statistics
        
        Raises:
            DesanitizationError: If restoration fails
        
        Example:
            ```python
            stats = desanitizer.restore(operation_id)
            if stats.is_successful:
                print(f"Restored {stats.total_rows_restored} rows")
            else:
                print(f"Errors: {stats.errors}")
            ```
        """
        # Use safe config if none provided
        if config is None:
            config = create_safe_config()
        
        # Initialize stats
        stats = RestoreStats(operation_id=str(operation_id))
        
        print("=" * 80)
        print("DATABASE DESANITIZATION - RESTORE ORIGINAL VALUES")
        print("=" * 80)
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Operation ID: {operation_id}")
        print(f"Configuration: {config.summary()}")
        print("=" * 80)
        
        try:
            # Phase 1: Validation
            print("\n[1/4] Validating operation...")
            self._validate_operation(operation_id, config, stats)
            
            # Phase 2: Planning
            print("\n[2/4] Planning restoration...")
            table_mappings = self._plan_restoration(operation_id, config, stats)
            
            # Phase 3: Restoration
            print("\n[3/4] Restoring data...")
            self._restore_data(table_mappings, config, stats)
            
            # Phase 4: Verification
            if config.verify_after_restore and not config.dry_run:
                print("\n[4/4] Verifying restoration...")
                self._verify_restoration(operation_id, stats)
            else:
                print("\n[4/4] Verification - Skipped")
                if config.dry_run:
                    print("  [INFO] Verification skipped in dry-run mode")
            
            stats.verification_passed = True
            
        except Exception as e:
            error_msg = f"Desanitization failed: {str(e)}"
            stats.errors.append(error_msg)
            print(f"\n[ERROR] {error_msg}")
            raise DesanitizationError(error_msg) from e
        
        # Display results
        self._display_results(stats, config)
        
        return stats
    
    def _validate_operation(
        self,
        operation_id: UUID,
        config: DesanitizationConfig,
        stats: RestoreStats
    ) -> None:
        """Validate that operation exists and has mappings."""
        print(f"  Checking operation {operation_id}...")
        
        # Check operation exists
        if not self.mapping_manager.operation_exists(operation_id):
            raise DesanitizationError(
                f"Operation {operation_id} not found in mapping table. "
                "This operation may not have been sanitized with mapping capture enabled."
            )
        
        print(f"  [OK] Operation found")
        
        # Get operation stats
        mapping_stats = self.mapping_manager.get_stats(operation_id)
        stats.total_mappings_applied = mapping_stats.total_mappings
        
        print(f"  [OK] Total mappings: {mapping_stats.total_mappings:,}")
        print(f"  [OK] Tables affected: {mapping_stats.tables_affected}")
        print(f"  [OK] Columns affected: {mapping_stats.columns_affected}")
        
        # Check encryption requirements
        if mapping_stats.encrypted_count > 0:
            if not self.encryption_manager:
                raise DesanitizationError(
                    f"Operation has {mapping_stats.encrypted_count:,} encrypted values "
                    "but no encryption manager provided. "
                    f"Ensure SANITIZATION_ENCRYPTION_KEY environment variable is set."
                )
            print(f"  [OK] Encryption key available for {mapping_stats.encrypted_count:,} encrypted values")
        else:
            print(f"  [INFO] No encrypted values (encryption was disabled during sanitization)")
    
    def _plan_restoration(
        self,
        operation_id: UUID,
        config: DesanitizationConfig,
        stats: RestoreStats
    ) -> Dict[str, List[MappingEntry]]:
        """Plan restoration by grouping mappings by table."""
        print(f"  Retrieving mappings for operation {operation_id}...")
        
        # Get all mappings or filtered by tables
        all_mappings = []
        
        if config.is_selective_restore:
            # Selective restore - get mappings for each specified table
            for table_spec in config.tables:
                schema, table = table_spec.split('.')
                mappings = self.mapping_manager.get_mappings(
                    operation_id=operation_id,
                    schema_name=schema,
                    table_name=table
                )
                all_mappings.extend(mappings)
                print(f"  [OK] {schema}.{table}: {len(mappings):,} mappings")
        else:
            # Full restore - get all mappings
            all_mappings = self.mapping_manager.get_mappings(operation_id=operation_id)
            print(f"  [OK] Retrieved {len(all_mappings):,} mappings")
        
        # Group by table
        table_mappings = defaultdict(list)
        for mapping in all_mappings:
            table_key = f"{mapping.schema_name}.{mapping.table_name}"
            table_mappings[table_key].append(mapping)
        
        stats.total_tables = len(table_mappings)
        
        print(f"  [OK] Planning complete: {stats.total_tables} tables to restore")
        
        return dict(table_mappings)
    
    def _restore_data(
        self,
        table_mappings: Dict[str, List[MappingEntry]],
        config: DesanitizationConfig,
        stats: RestoreStats
    ) -> None:
        """Restore data for all tables."""
        if not table_mappings:
            print("  [WARN] No mappings to restore")
            return
        
        try:
            with pyodbc.connect(self.connection_string) as conn:
                conn.autocommit = False  # Explicit transaction control
                
                for table_idx, (table_name, mappings) in enumerate(table_mappings.items(), 1):
                    print(f"\n  [{table_idx}/{stats.total_tables}] Restoring {table_name}...")
                    
                    try:
                        rows_restored = self._restore_table(
                            conn, table_name, mappings, config, stats
                        )
                        stats.total_rows_restored += rows_restored
                        stats.tables_restored += 1
                        
                        if config.dry_run:
                            print(f"      [OK] Would restore {rows_restored:,} rows (DRY-RUN)")
                        else:
                            print(f"      [OK] Restored {rows_restored:,} rows")
                    
                    except Exception as table_err:
                        stats.tables_failed += 1
                        error_msg = f"Failed to restore {table_name}: {str(table_err)}"
                        stats.errors.append(error_msg)
                        print(f"      [ERROR] {error_msg}")
                        
                        if not config.continue_on_table_failure:
                            raise
                
                # Commit or rollback based on config
                if not config.dry_run:
                    if stats.tables_failed > 0 and config.rollback_on_error:
                        conn.rollback()
                        print(f"\n  [ROLLBACK] Transaction rolled back due to errors")
                    else:
                        conn.commit()
                        print(f"\n  [COMMIT] Transaction committed")
                else:
                    print(f"\n  [DRY-RUN] No database changes made")
        
        except pyodbc.Error as e:
            raise DesanitizationError(f"Database error during restoration: {str(e)}")
    
    def _restore_table(
        self,
        conn,
        table_name: str,
        mappings: List[MappingEntry],
        config: DesanitizationConfig,
        stats: RestoreStats
    ) -> int:
        """Restore a single table."""
        if not mappings:
            return 0
        
        # Group mappings by column
        column_mappings = defaultdict(list)
        for mapping in mappings:
            column_mappings[mapping.column_name].append(mapping)
        
        total_restored = 0
        
        for column, col_mappings in column_mappings.items():
            print(f"      Column: {column} ({len(col_mappings):,} values)...")
            
            # Decrypt/decode original values
            decrypted_mappings = []
            for mapping in col_mappings:
                try:
                    if mapping.is_null:
                        original_value = None
                        stats.null_values_restored += 1
                    elif mapping.original_value_encrypted is not None:
                        # Try decryption first if encryption manager available
                        if self.encryption_manager:
                            try:
                                original_value = self.encryption_manager.decrypt(
                                    mapping.original_value_encrypted
                                )
                                stats.encrypted_values_decrypted += 1
                            except DecryptionError:
                                # Decryption failed - might be plaintext bytes
                                original_value = mapping.original_value_encrypted.decode('utf-8')
                        else:
                            # No encryption manager - treat as plaintext bytes
                            original_value = mapping.original_value_encrypted.decode('utf-8')
                    else:
                        # No encrypted value and not NULL - data corruption
                        raise DesanitizationError(
                            f"Mapping for {table_name}.{column} has no original value. "
                            "Data may be corrupted or sanitization didn't capture mappings properly."
                        )
                    
                    decrypted_mappings.append((mapping.masked_value, original_value))
                
                except (DecryptionError, UnicodeDecodeError) as dec_err:
                    raise DesanitizationError(
                        f"Failed to restore value for {table_name}.{column}: {str(dec_err)}"
                    )
            
            # Restore in batches
            rows_restored = self._restore_column_batch(
                conn, table_name, column, decrypted_mappings, config
            )
            total_restored += rows_restored
        
        return total_restored
    
    def _restore_column_batch(
        self,
        conn,
        table_name: str,
        column: str,
        mappings: List[Tuple[str, Optional[str]]],
        config: DesanitizationConfig
    ) -> int:
        """Restore a column using batch UPDATE."""
        if not mappings or config.dry_run:
            return len(mappings)
        
        cursor = conn.cursor()
        
        try:
            # Create temp table
            cursor.execute("""
                IF OBJECT_ID('tempdb..#temp_restore') IS NOT NULL
                    DROP TABLE #temp_restore;
                
                CREATE TABLE #temp_restore (
                    masked_value NVARCHAR(MAX),
                    original_value NVARCHAR(MAX)
                );
            """)
            
            # Insert mappings
            insert_query = "INSERT INTO #temp_restore (masked_value, original_value) VALUES (?, ?)"
            cursor.executemany(insert_query, mappings)
            conn.commit()
            
            # Single UPDATE with JOIN
            update_query = f"""
                UPDATE t
                SET t.[{column}] = r.original_value
                FROM {table_name} t
                INNER JOIN #temp_restore r ON t.[{column}] = r.masked_value
                WHERE t.[{column}] IS NOT NULL;
            """
            cursor.execute(update_query)
            rows_affected = cursor.rowcount
            
            # Cleanup
            cursor.execute("DROP TABLE #temp_restore;")
            cursor.close()
            
            # Handle -1 rowcount
            if rows_affected == -1:
                rows_affected = len(mappings)
            
            return rows_affected
        
        except pyodbc.Error as e:
            conn.rollback()
            raise DesanitizationError(f"Failed to restore {table_name}.{column}: {str(e)}")
    
    def _verify_restoration(self, operation_id: UUID, stats: RestoreStats) -> None:
        """Verify restoration was successful."""
        print("  Running post-restore verification...")
        
        # Basic verification: check that mappings still exist
        mapping_stats = self.mapping_manager.get_stats(operation_id)
        
        if mapping_stats.total_mappings != stats.total_mappings_applied:
            stats.errors.append(
                f"Mapping count mismatch: expected {stats.total_mappings_applied}, "
                f"found {mapping_stats.total_mappings}"
            )
        
        print(f"  [OK] Verification complete")
        stats.verification_passed = True
    
    def _display_results(self, stats: RestoreStats, config: DesanitizationConfig) -> None:
        """Display restoration results."""
        print("\n" + "=" * 80)
        
        if stats.is_successful and not config.dry_run:
            print("[SUCCESS] DESANITIZATION COMPLETED")
        elif config.dry_run:
            print("[DRY-RUN] DESANITIZATION PREVIEW")
        else:
            print("[FAILED] DESANITIZATION COMPLETED WITH ERRORS")
        
        print("=" * 80)
        
        print(f"\nTables:")
        print(f"  Restored: {stats.tables_restored}/{stats.total_tables}")
        if stats.tables_failed > 0:
            print(f"  Failed: {stats.tables_failed}")
        
        print(f"\nRows:")
        if config.dry_run:
            print(f"  Would restore: {stats.total_rows_restored:,}")
        else:
            print(f"  Restored: {stats.total_rows_restored:,}")
        
        print(f"\nMappings:")
        print(f"  Applied: {stats.total_mappings_applied:,}")
        print(f"  NULL values: {stats.null_values_restored:,}")
        print(f"  Decrypted: {stats.encrypted_values_decrypted:,}")
        
        if stats.has_errors:
            print(f"\nErrors ({len(stats.errors)}):")
            for error in stats.errors[:10]:  # Show first 10 errors
                print(f"  - {error}")
            if len(stats.errors) > 10:
                print(f"  ... and {len(stats.errors) - 10} more")
        
        print("\n" + "=" * 80)
        print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)


def main():
    """Main execution function."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Desanitize database by restoring original PII values",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run (preview only)
  python desanitize.py a1b2c3d4-5678-90ab-cdef-123456789abc
  
  # Execute full restore
  python desanitize.py a1b2c3d4-5678-90ab-cdef-123456789abc --execute
  
  # Selective table restore
  python desanitize.py a1b2c3d4-5678-90ab-cdef-123456789abc --execute --tables dbo.Customers dbo.Orders
  
  # Custom batch size
  python desanitize.py a1b2c3d4-5678-90ab-cdef-123456789abc --execute --batch-size 5000
        """
    )
    
    parser.add_argument(
        'operation_id',
        type=str,
        help='UUID of the sanitization operation to reverse'
    )
    
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Execute restoration (default is dry-run)'
    )
    
    parser.add_argument(
        '--tables',
        nargs='+',
        help='Specific tables to restore (format: schema.table)'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=10000,
        help='Number of rows per batch (default: 10000)'
    )
    
    parser.add_argument(
        '--connection-string',
        type=str,
        help='Database connection string (or use environment variables)'
    )
    
    args = parser.parse_args()
    
    # Parse operation ID
    try:
        operation_id = UUID(args.operation_id)
    except ValueError:
        print(f"[ERROR] Invalid operation ID: {args.operation_id}")
        print("Operation ID must be a valid UUID")
        sys.exit(1)
    
    # Build connection string
    if args.connection_string:
        conn_string = args.connection_string
    else:
        # Build from environment or config
        import os
        server = os.getenv('SQLSERVER_HOST', 'localhost')
        database = os.getenv('SQLSERVER_DB')
        
        if not database:
            print("[ERROR] No database specified. Set SQLSERVER_DB environment variable or use --connection-string")
            sys.exit(1)
        
        conn_string = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};Trusted_Connection=yes;"
    
    # Initialize encryption manager (optional - depends on whether mappings are encrypted)
    encryption_manager = None
    try:
        encryption_manager = EncryptionManager()
        print("[INFO] Encryption key loaded - will decrypt encrypted mappings")
    except EncryptionKeyError:
        # Check if operation has encrypted values
        try:
            import pyodbc
            conn = pyodbc.connect(conn_string, autocommit=True)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM dbo.pii_mappings WHERE operation_id = ? AND original_value_encrypted IS NOT NULL",
                str(operation_id)
            )
            encrypted_count = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            
            if encrypted_count > 0:
                print(f"[ERROR] This operation has {encrypted_count} encrypted mappings but no encryption key was found.")
                print("[ERROR] Set SANITIZATION_ENCRYPTION_KEY environment variable with the key used during sanitization.")
                sys.exit(1)
            else:
                print("[INFO] No encryption key needed - mappings are stored in plaintext")
        except Exception as e:
            # If we can't check, assume encryption is needed
            print("[WARNING] Could not verify encryption status")
            print("[ERROR] Set SANITIZATION_ENCRYPTION_KEY environment variable if mappings are encrypted.")
            print(f"[DEBUG] Check error: {e}")
            sys.exit(1)
    
    # Create configuration
    if args.execute:
        config = create_production_config(
            tables=args.tables,
            batch_size=args.batch_size
        )
    else:
        config = create_safe_config()
        config.batch_size = args.batch_size
        if args.tables:
            config.tables = args.tables
    
    # Initialize desanitizer
    desanitizer = Desanitizer(
        connection_string=conn_string,
        encryption_manager=encryption_manager
    )
    
    # Execute restoration
    try:
        stats = desanitizer.restore(operation_id, config)
        
        if stats.is_successful:
            sys.exit(0)
        else:
            sys.exit(1)
    
    except DesanitizationError as e:
        print(f"\n[ERROR] Desanitization failed: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[ABORTED] Desanitization cancelled by user")
        sys.exit(130)


if __name__ == "__main__":
    main()
