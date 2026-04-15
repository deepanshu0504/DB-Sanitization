#!/usr/bin/env python3
"""
Direct Desanitization Script - Multi-Level Restoration with Checkpoint Support
===============================================================================

This script provides a command-line interface for restoring original values
from sanitized data using stored mapping tables.

Features:
    - Record-level restoration by primary key
    - Column-level restoration (all records in specified columns)
    - Table-level restoration (all columns with mappings)
    - **DATABASE-LEVEL RESTORATION** (entire database with FK-safe ordering)
    - Checkpoint-based fault tolerance with resume capability
    - Circular FK dependency handling with constraint management
    - Support for single and composite primary keys
    - Batch processing for multiple records
    - Dry-run mode for safe preview
    - Transaction safety with automatic rollback
    - Progress tracking for large operations (hourly summaries)
    - Comprehensive reporting and validation
    - JSON output for automation

Usage Examples:
    # RECORD-LEVEL RESTORATION
    # Dry-run (preview only - safe default)
    python desanitize_direct.py record --table Customers --record-ids "123" "456" --dry-run
    
    # Execute restoration
    python desanitize_direct.py record --table Customers --record-ids "123" "456" --execute
    
    # Restore from specific batch
    python desanitize_direct.py record --table Users --batch-id "BATCH-20260409" --record-ids "AAA" "BBB"
    
    # Skip missing mappings instead of error
    python desanitize_direct.py record --table Orders --record-ids "999" --skip-missing
    
    # COLUMN-LEVEL RESTORATION (ALL RECORDS)
    # Preview column restoration
    python desanitize_direct.py column --table Customers --columns Email PhoneNumber --dry-run
    
    # Execute column restoration
    python desanitize_direct.py column --table Users --columns SSN DateOfBirth --execute --yes
    
    # Restore single column from specific batch
    python desanitize_direct.py column --table Employees --columns Salary --batch-id "BATCH-20260409" --execute
    
    # TABLE-LEVEL RESTORATION (ALL COLUMNS WITH MAPPINGS)
    # Preview entire table restoration
    python desanitize_direct.py table --table Customers --dry-run
    
    # Execute full table restoration
    python desanitize_direct.py table --table Customers --execute --yes
    
    # Restore table from specific batch
    python desanitize_direct.py table --table Orders --batch-id "BATCH-20260409" --execute
    
    # DATABASE-LEVEL RESTORATION (ENTIRE DATABASE)
    # Preview entire database restoration
    python desanitize_direct.py database --dry-run
    
    # Execute database restoration (FK-safe order, checkpoint tracking)
    python desanitize_direct.py database --execute --yes
    
    # Filter to specific schema
    python desanitize_direct.py database --schema-filter dbo --execute
    
    # Resume from checkpoint after failure
    python desanitize_direct.py database --resume DESAN-20260409... --execute
    
    # Strict mode (stop on first error)
    python desanitize_direct.py database --strict --execute
    
    # Parallel processing with 4 workers
    python desanitize_direct.py database --execute --parallel 4 --yes
    
    # BATCH MANAGEMENT
    # List available batches
    python desanitize_direct.py list-batches
    
    # List batches with JSON output
    python desanitize_direct.py list-batches --json-output batches.json
    
    # VALIDATION
    # Validate record restoration
    python desanitize_direct.py validate --table Customers --record-ids "123"
    
    # Validate database restoration
    python desanitize_direct.py validate --database
    
    # JSON output for automation
    python desanitize_direct.py record --table Products --record-ids "P123" --json-output results.json

Configuration:
    Uses config/pii_config.example.json for database connection settings.
    Set SQLSERVER_HOST, SQLSERVER_DB, and auth settings in config or environment.

Author: Database Sanitization Team
Date: April 13, 2026
Version: 3.0.0 (Story 6.1 - Unified CLI with Subcommand Architecture)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

import pyodbc

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from desanitization import DesanitizationEngine
from desanitization.config_models import (
    DesanitizationConfig,
    create_minimal_config,
)
from desanitization.exceptions import (
    DesanitizationError,
    MappingNotFoundError,
    PreconditionError,
)
from mapping.mapping_table_manager import MappingTableManager
from mapping.encryption_utils import MappingEncryptor
from mapping.exceptions import KeyManagementError, EncryptionError
from database.schema_inspector import SchemaInspector
from audit import AuditLogger, AuditTableMissingError
from security.access_control import AccessControl
from security.exceptions import PermissionDeniedError, RoleNotFoundError, SecurityError
from desanitization.config_models import DatabaseConfig
from pydantic import ValidationError


# ANSI color codes for terminal output
class Colors:
    """ANSI color codes for rich terminal output."""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def setup_logging(verbose: bool = False) -> logging.Logger:
    """
    Configure logging for desanitization operations.
    
    Args:
        verbose: If True, set DEBUG level; otherwise INFO
    
    Returns:
        Configured logger instance
    """
    log_level = logging.DEBUG if verbose else logging.INFO
    
    # Create logger
    logger = logging.getLogger('desanitization')
    logger.setLevel(log_level)
    
    # Console handler with formatting
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    
    return logger


def load_config(config_path: str, logger) -> DesanitizationConfig:
    """
    Load desanitization configuration from JSON file.
    
    Uses ConfigLoader for validation and environment variable overrides.
    Supports both desanitization-specific config and legacy sanitization config.
    
    Args:
        config_path: Path to configuration file
        logger: Logger instance
    
    Returns:
        Validated DesanitizationConfig object
    
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValidationError: If configuration validation fails
    """
    logger.info(f"Loading configuration from {config_path}")
    
    # Check if config file exists
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}\n"
            f"Please create config file or specify correct path with --config\n"
            f"Example: config/desanitization_config.example.json"
        )
    
    try:
        # Try loading as desanitization config first
        with open(config_path, 'r', encoding='utf-8') as f:
            config_dict = json.load(f)
        
        # Check if it's a desanitization config or legacy sanitization config
        if 'restoration' in config_dict or 'checkpoint' in config_dict:
            # Desanitization-specific config
            logger.info("Detected desanitization-specific configuration format")
            config = DesanitizationConfig(**config_dict)
        elif 'database' in config_dict:
            # Legacy sanitization config - extract database settings
            logger.info("Detected legacy sanitization configuration - extracting database settings")
            db_config = DatabaseConfig(**config_dict['database'])
            config = create_minimal_config(
                server=db_config.server,
                database=db_config.database,
                auth_type=db_config.auth_type,
                username=db_config.username,
                password=db_config.password,
                timeout=db_config.timeout,
                max_retries=db_config.max_retries,
                pool_size=db_config.pool_size,
                environment=db_config.environment
            )
            
            # Override mapping table name if specified in legacy config
            if 'mapping_capture' in config_dict:
                config.mapping.table_name = config_dict['mapping_capture'].get(
                    'table_name', config.mapping.table_name
                )
            
            # Override encryption settings if specified
            if 'mapping_encryption' in config_dict:
                config.mapping.encryption.enabled = config_dict['mapping_encryption'].get(
                    'enabled', config.mapping.encryption.enabled
                )
                config.mapping.encryption.key_env_var = config_dict['mapping_encryption'].get(
                    'key_env_var', config.mapping.encryption.key_env_var
                )
        else:
            raise ValidationError(
                "Configuration file must contain either 'database' section "
                "or desanitization-specific sections"
            )
        
        logger.info(
            f"Configuration loaded successfully: "
            f"database={config.database.database}, "
            f"mapping_table={config.mapping.table_name}, "
            f"encryption={config.mapping.encryption.enabled}"
        )
        
        return config
        
    except ValidationError as e:
        logger.error(f"Configuration validation failed: {e}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in configuration file: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error loading configuration: {e}")
        raise


def load_encryption_from_config(config: DesanitizationConfig, logger) -> Optional['MappingEncryptor']:
    """
    Load encryption configuration and initialize MappingEncryptor.
    
    Args:
        config: DesanitizationConfig instance
        logger: Logger instance
        
    Returns:
        MappingEncryptor instance if encryption enabled, None otherwise
        
    Raises:
        SystemExit: If encryption enabled but key missing or invalid
    """
    encryption_config = config.mapping.encryption
    
    if not encryption_config.enabled:
        logger.info("Encryption disabled")
        return None
    
    try:
        key_env_var = encryption_config.key_env_var
        fallback_env_vars = encryption_config.fallback_keys_env_vars
        
        encryptor = MappingEncryptor.from_environment(
            key_env_var=key_env_var,
            fallback_env_vars=fallback_env_vars if fallback_env_vars else None
        )
        
        logger.info(f"Encryption enabled (key from {key_env_var})")
        return encryptor
        
    except KeyManagementError as e:
        logger.error(f"Encryption initialization failed: {e}")
        logger.error("Cannot proceed with encryption enabled but no valid key")
        logger.error(f"Suggested action: {e.suggested_action if hasattr(e, 'suggested_action') else 'Check encryption configuration'}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected encryption error: {e}")
        sys.exit(1)


def build_connection_string(db_config: DatabaseConfig) -> str:
    """
    Build SQL Server connection string from database configuration.
    
    Args:
        db_config: DatabaseConfig instance (from DesanitizationConfig.database)
    
    Returns:
        pyodbc connection string
    """
    server = db_config.server or os.getenv('SQLSERVER_HOST', 'localhost')
    database = db_config.database or os.getenv('SQLSERVER_DB', 'TestDB')
    auth_type = db_config.auth_type or os.getenv('SQLSERVER_AUTH', 'windows')
    
    if auth_type.lower() == 'windows':
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"Trusted_Connection=yes;"
        )
    else:
        username = db_config.username or os.getenv('SQLSERVER_USER')
        password = db_config.password or os.getenv('SQLSERVER_PASSWORD')
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
        )
    
    return conn_str


def apply_cli_overrides(config: DesanitizationConfig, args: argparse.Namespace) -> DesanitizationConfig:
    """
    Apply CLI argument overrides to configuration.
    
    Implements merge priority: CLI args > config file > defaults
    
    Args:
        config: Base configuration from file
        args: Parsed command-line arguments
    
    Returns:
        Modified configuration with CLI overrides applied
    
    Example:
        >>> config = load_config("config.json", logger)
        >>> config = apply_cli_overrides(config, args)
        >>> # CLI --execute flag overrides config.restoration.dry_run
    """
    # Override dry_run mode from CLI flags
    # --execute explicitly sets dry_run=False (commit changes to database)
    # --dry-run explicitly sets dry_run=True (preview only)
    # Default when neither flag provided: dry_run=True (safe default)
    if hasattr(args, 'execute') and args.execute:
        config.restoration.dry_run = False
    elif hasattr(args, 'dry_run') and args.dry_run:
        config.restoration.dry_run = True
    else:
        # Default to dry-run when neither flag provided (safe default)
        config.restoration.dry_run = True
    
    # Override skip_verification from CLI
    if hasattr(args, 'skip_post_verification') and args.skip_post_verification:
        config.restoration.skip_verification = True
    
    # Override strict mode from CLI
    if hasattr(args, 'strict') and args.strict:
        config.restoration.strict = True
    
    # Override skip_audit from CLI
    if hasattr(args, 'skip_audit') and args.skip_audit:
        config.restoration.skip_audit = True
        config.audit.enabled = False
    
    # Override skip_missing from CLI
    if hasattr(args, 'skip_missing') and args.skip_missing:
        config.restoration.skip_missing = True
    
    # Override strict_verification from CLI
    if hasattr(args, 'strict_verification') and args.strict_verification:
        config.validation.strict_verification = True
    
    # Override parallel processing from CLI
    if hasattr(args, 'max_workers') and args.max_workers is not None:
        config.performance.enable_parallel = True
        config.performance.max_workers = args.max_workers
    elif hasattr(args, 'no_parallel') and args.no_parallel:
        config.performance.enable_parallel = False
    
    # Override rate limiting from CLI
    if hasattr(args, 'rate_limit') and args.rate_limit is not None:
        config.performance.rate_limit_ms = args.rate_limit
    
    # Override checkpoint/resume from CLI
    if hasattr(args, 'resume') and args.resume:
        config.checkpoint.operation_id = args.resume
    
    if hasattr(args, 'clear_stale_checkpoints') and args.clear_stale_checkpoints:
        config.checkpoint.clear_stale = True
    
    # Story 7.1: Override security settings from CLI
    if hasattr(args, 'security_enabled') and args.security_enabled:
        config.security.enabled = True
    
    if hasattr(args, 'allowed_roles') and args.allowed_roles:
        config.security.allowed_roles = args.allowed_roles
        # Auto-enable security if roles specified
        config.security.enabled = True
    
    if hasattr(args, 'require_role_for_dry_run') and args.require_role_for_dry_run:
        config.security.require_role_for_dry_run = True
    
    if hasattr(args, 'skip_security_check') and args.skip_security_check:
        config.security.enabled = False
    
    return config


def print_banner():
    """Print application banner."""
    print(f"\n{Colors.BOLD}{Colors.OKBLUE}")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║     Database Desanitization Engine v1.1.0                 ║")
    print("║     Record/Column/Table-Level Restoration Tool            ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print(f"{Colors.ENDC}\n")


def print_report(report, colored: bool = True) -> None:
    """
    Print desanitization report to console.
    
    Args:
        report: RestorationReport instance
        colored: If True, use ANSI colors
    """
    if colored:
        header_color = Colors.BOLD + Colors.OKCYAN
        success_color = Colors.OKGREEN
        warning_color = Colors.WARNING
        error_color = Colors.FAIL
        end_color = Colors.ENDC
    else:
        header_color = success_color = warning_color = error_color = end_color = ''
    
    print(f"\n{header_color}{'='*70}{end_color}")
    print(f"{header_color}DESANITIZATION REPORT{end_color}")
    print(f"{header_color}{'='*70}{end_color}\n")
    
    # Operation info
    print(f"{Colors.BOLD}Operation ID:{Colors.ENDC} {report.operation_id}")
    if report.audit_id:
        print(f"{Colors.BOLD}Audit Log ID:{Colors.ENDC} {report.audit_id}")
    print(f"{Colors.BOLD}Start Time:{Colors.ENDC} {report.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    if report.end_time:
        duration = (report.end_time - report.start_time).total_seconds()
        print(f"{Colors.BOLD}Duration:{Colors.ENDC} {duration:.2f} seconds")
    
    if report.dry_run:
        print(f"\n{warning_color}[DRY RUN MODE - No changes committed]{end_color}")
    
    # Summary
    print(f"\n{header_color}Summary:{end_color}")
    print(f"  Tables Affected:    {report.tables_affected}")
    print(f"  Columns Affected:   {report.columns_affected}")
    print(f"  Records Requested:  {report.records_requested}")
    print(f"  Mappings Applied:   {report.mappings_applied:,}")
    print(f"  Records Restored:   {success_color}{report.records_restored:,}{end_color}")
    
    # Show restoration efficiency and discrepancy analysis
    if report.mappings_applied > 0:
        efficiency = (report.records_restored / report.mappings_applied) * 100
        print(f"  Restoration Efficiency: {efficiency:.1f}%")
        
        if report.mappings_applied > report.records_restored:
            discrepancy = report.mappings_applied - report.records_restored
            discrepancy_pct = (discrepancy / report.mappings_applied) * 100
            
            # Count orphan-related warnings
            orphan_warnings = [w for w in report.warnings if 'deleted after sanitization' in w.lower()]
            duplicate_warnings = [w for w in report.warnings if 'duplicate mapping' in w.lower()]
            
            print(f"\n  {warning_color}⚠️ Discrepancy Detected:{end_color}")
            print(f"     Gap: {discrepancy:,} ({discrepancy_pct:.1f}%)")
            
            if orphan_warnings:
                print(f"     Likely Cause: Records deleted after sanitization")
                print(f"     Affected Tables: {len(orphan_warnings)}")
            elif duplicate_warnings:
                print(f"     Likely Cause: Duplicate mappings in mapping table")
            else:
                print(f"     Cause: Unknown - check warnings below for details")
    
    # Table details
    if report.table_details:
        print(f"\n{header_color}Column Details:{end_color}")
        for table, columns in report.table_details.items():
            print(f"  Table: {table}")
            for column, rows in columns.items():
                print(f"    └─ {column}: {rows} rows restored")
    
    # Warnings
    if report.warnings:
        print(f"\n{warning_color}Warnings:{end_color}")
        for warning in report.warnings:
            print(f"  ⚠ {warning}")
    
    # Errors
    if report.errors:
        print(f"\n{error_color}Errors:{end_color}")
        for error in report.errors:
            print(f"  ✖ {error}")
    
    # Post-Restoration Verification (Story 3.2)
    if report.post_verification_report:
        _display_verification_section(report.post_verification_report, colored)
    
    print(f"\n{header_color}{'='*70}{end_color}\n")


def _display_verification_section(verification_report, colored: bool = True) -> None:
    """
    Display post-restoration verification results in report.
    
    Args:
        verification_report: ValidationReport from verification
        colored: If True, use ANSI colors
    """
    if colored:
        header_color = Colors.BOLD + Colors.OKCYAN
        success_color = Colors.OKGREEN
        warning_color = Colors.WARNING
        error_color = Colors.FAIL
        end_color = Colors.ENDC
    else:
        header_color = success_color = warning_color = error_color = end_color = ''
    
    from validation.desanitization_validator import ValidationStatus
    
    print(f"\n{header_color}Post-Restoration Verification (Story 3.2):{end_color}")
    print(f"  Verification ID:    {verification_report.validation_id}")
    print(f"  Checks Performed:   {len(verification_report.checks)}")
    print(f"  Passed:             {success_color}{len(verification_report.passed_checks)}{end_color}")
    print(f"  Failed:             {error_color}{len(verification_report.failed_checks)}{end_color}")
    print(f"  Warnings:           {warning_color}{len(verification_report.warnings)}{end_color}")
    
    print(f"\n{header_color}  Verification Checks:{end_color}")
    
    for check in verification_report.checks:
        if check.status == ValidationStatus.PASSED:
            status_symbol = f"{success_color}✓{end_color}"
        elif check.status == ValidationStatus.FAILED:
            status_symbol = f"{error_color}✗{end_color}"
        elif check.status == ValidationStatus.WARNING:
            status_symbol = f"{warning_color}⚠{end_color}"
        else:  # SKIPPED
            status_symbol = "○"
        
        print(f"    {status_symbol} {check.check_name}: {check.message}")
        
        if check.suggested_action:
            print(f"       → {check.suggested_action}")
    
    # Overall verification status
    if verification_report.is_valid():
        print(f"\n  {success_color}✓ Verification Status: PASSED{end_color}")
    else:
        print(f"\n  {error_color}✗ Verification Status: FAILED{end_color}")
    
    print(f"\n{header_color}{'='*70}{end_color}\n")


def display_validation_report(report, colored: bool = True) -> None:
    """
    Display validation report to console with color coding.
    
    Args:
        report: ValidationReport instance
        colored: If True, use ANSI colors
    """
    if colored:
        header_color = Colors.BOLD + Colors.OKCYAN
        success_color = Colors.OKGREEN
        warning_color = Colors.WARNING
        error_color = Colors.FAIL
        end_color = Colors.ENDC
    else:
        header_color = success_color = warning_color = error_color = end_color = ''
    
    print(f"\n{header_color}{'='*70}{end_color}")
    print(f"{header_color}VALIDATION REPORT{end_color}")
    print(f"{header_color}{'='*70}{end_color}\n")
    
    # Validation info
    print(f"{Colors.BOLD}Validation ID:{Colors.ENDC} {report.validation_id}")
    print(f"{Colors.BOLD}Timestamp:{Colors.ENDC} {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{Colors.BOLD}Scope:{Colors.ENDC} {report.scope.upper()}")
    print(f"{Colors.BOLD}Target:{Colors.ENDC} {report.target_info}")
    
    # Summary
    print(f"\n{header_color}Summary:{end_color}")
    print(f"  Total Checks:       {len(report.checks)}")
    print(f"  Passed:             {success_color}{len(report.passed_checks)}{end_color}")
    print(f"  Failed:             {error_color}{len(report.failed_checks)}{end_color}")
    print(f"  Warnings:           {warning_color}{len(report.warnings)}{end_color}")
    
    # Check results
    print(f"\n{header_color}Validation Checks:{end_color}\n")
    
    from validation.desanitization_validator import ValidationStatus
    
    for check in report.checks:
        if check.status == ValidationStatus.PASSED:
            status_symbol = f"{success_color}✓{end_color}"
            status_text = f"{success_color}PASSED{end_color}"
        elif check.status == ValidationStatus.FAILED:
            status_symbol = f"{error_color}✗{end_color}"
            status_text = f"{error_color}FAILED{end_color}"
        elif check.status == ValidationStatus.WARNING:
            status_symbol = f"{warning_color}⚠{end_color}"
            status_text = f"{warning_color}WARNING{end_color}"
        else:  # SKIPPED
            status_symbol = "○"
            status_text = "SKIPPED"
        
        print(f"  {status_symbol} {Colors.BOLD}{check.check_name}:{Colors.ENDC} {status_text}")
        print(f"     {check.message}")
        
        if check.suggested_action:
            print(f"     {Colors.BOLD}→ Action:{Colors.ENDC} {check.suggested_action}")
        
        if check.details:
            print(f"     {Colors.BOLD}Details:{Colors.ENDC} {check.details}")
        
        print()  # Blank line between checks
    
    # Overall status
    if report.is_valid():
        overall_status = f"{success_color}{Colors.BOLD}✓ VALIDATION PASSED{end_color}"
        print(f"\n{overall_status} - Desanitization can proceed safely\n")
    else:
        overall_status = f"{error_color}{Colors.BOLD}✗ VALIDATION FAILED{end_color}"
        print(f"\n{overall_status} - Fix issues before desanitization\n")
    
    print(f"{header_color}{'='*70}{end_color}\n")


def confirm_operation(
    table: Optional[str] = None,
    record_count: Optional[int] = None,
    column_names: Optional[List[str]] = None,
    table_level: bool = False,
    database_level: bool = False,
    table_count: Optional[int] = None,
    dry_run: bool = False,
    yes_flag: bool = False,
    enable_parallel: bool = False,
    max_workers: Optional[int] = None,
    security_enabled: bool = False,
    security_roles: Optional[List[str]] = None
) -> bool:
    """
    Prompt user to confirm desanitization operation.
    
    Args:
        table: Table name (for table/column/record-level)
        record_count: Number of records to restore (record-level mode)
        column_names: List of column names (column-level mode)
        table_level: Whether this is table-level restoration (all columns with mappings)
        database_level: Whether this is database-level restoration (entire database)
        table_count: Number of tables for database-level restoration
        dry_run: Whether this is a dry-run
        yes_flag: If True, skip confirmation (assume yes)
        enable_parallel: Story 5.1 - Whether parallel processing is enabled
        max_workers: Story 5.1 - Number of worker threads for parallel processing
        security_enabled: Story 7.1 - Whether RBAC is enabled
        security_roles: Story 7.1 - List of allowed roles
    
    Returns:
        True if user confirms, False otherwise
    """
    if yes_flag or dry_run:
        return True
    
    print(f"\n{Colors.WARNING}{Colors.BOLD}⚠ IMPORTANT ⚠{Colors.ENDC}")
    print(f"You are about to restore original values for:")
    
    if database_level:
        # Database-level restoration
        print(f"  • Scope: {Colors.BOLD}ENTIRE DATABASE{Colors.ENDC}")
        if table_count:
            print(f"  • Tables: {Colors.BOLD}{table_count}{Colors.ENDC} table(s) with mappings")
        
        # Story 5.1: Show parallelization mode
        if enable_parallel:
            print(f"  • Processing: {Colors.OKGREEN}Parallel{Colors.ENDC} with {Colors.BOLD}{max_workers}{Colors.ENDC} worker(s)")
            print(f"    ({Colors.OKGREEN}Independent tables will be processed concurrently{Colors.ENDC})")
        else:
            print(f"  • Processing: {Colors.OKCYAN}Sequential{Colors.ENDC} (all tables processed one-by-one)")
        
        print(f"\n{Colors.WARNING}Note:{Colors.ENDC} Tables will be processed in FK dependency-safe order")
        print(f"{Colors.WARNING}      Circular dependencies will be handled with temporary constraint disabling{Colors.ENDC}")
        warning_text = "RESTORE DATABASE"
    else:
        print(f"  • Table: {Colors.BOLD}{table}{Colors.ENDC}")
        
        if table_level:
            # Table-level restoration
            print(f"  • Scope: {Colors.BOLD}ALL COLUMNS{Colors.ENDC} with mappings in the table")
            print(f"\n{Colors.WARNING}Note:{Colors.ENDC} Columns will be auto-discovered from mapping table")
        elif column_names:
            # Column-level restoration
            print(f"  • Columns: {Colors.BOLD}{', '.join(column_names)}{Colors.ENDC}")
            print(f"  • Scope: {Colors.BOLD}ALL RECORDS{Colors.ENDC} in specified columns")
        else:
            # Record-level restoration
            print(f"  • Records: {Colors.BOLD}{record_count}{Colors.ENDC}")
        
        warning_text = "yes"
    
    # Story 7.1: Display security status
    if security_enabled:
        print(f"\n{Colors.OKGREEN}Security:{Colors.ENDC} {Colors.BOLD}ENABLED{Colors.ENDC}")
        if security_roles:
            roles_display = ', '.join(security_roles[:3])
            if len(security_roles) > 3:
                roles_display += f" (+{len(security_roles)-3} more)"
            print(f"  • Allowed roles: {Colors.BOLD}{roles_display}{Colors.ENDC}")
        print(f"  • User must be member of at least one allowed role")
    else:
        print(f"\n{Colors.WARNING}Security:{Colors.ENDC} {Colors.BOLD}DISABLED{Colors.ENDC} (backward compatible mode)")
    
    print(f"\nThis operation will:")
    print(f"  1. Replace sanitized values with original values")
    print(f"  2. Commit changes to the database")
    print(f"  3. Cannot be automatically undone")
    print(f"\n{Colors.WARNING}Are you sure you want to proceed?{Colors.ENDC}")
    
    response = input(f"Type '{warning_text}' to confirm: ").strip()
    
    if database_level:
        return response == "RESTORE DATABASE"
    else:
        return response.lower() == 'yes'


def handle_show_dependencies(connection, table: Optional[str], schema: str = 'dbo', logger=None) -> None:
    """
    Display FK dependency graph for a table or all tables.
    
    Args:
        connection: Database connection
        table: Table name to analyze (None for all tables)
        schema: Schema name
        logger: Logger instance
    """
    from database.dependency_graph_builder import DependencyGraph
    
    logger = logger or logging.getLogger(__name__)
    
    print(f"\n{Colors.HEADER}{Colors.BOLD}═══ FK Dependency Analysis ═══{Colors.ENDC}\n")
    
    # Build dependency graph
    print(f"{Colors.OKCYAN}Building dependency graph...{Colors.ENDC}")
    graph = DependencyGraph(connection, logger=logger)
    graph.build_graph()
    
    print(f"  • Total tables: {len(graph.all_tables)}")
    print(f"  • Total FK relationships: {len(graph.relationships)}")
    print(f"  • Self-referencing tables: {len(graph.self_referencing_tables)}")
    
    if table:
        # Show dependencies for specific table
        qualified_name = f"[{schema}].[{table}]"
        
        if qualified_name not in graph.all_tables:
            print(f"\n{Colors.FAIL}✗ Table {qualified_name} not found in dependency graph{Colors.ENDC}")
            print(f"\n{Colors.WARNING}Available tables:{Colors.ENDC}")
            for tbl in sorted(graph.all_tables)[:20]:
                print(f"  • {tbl}")
            if len(graph.all_tables) > 20:
                print(f"  ... and {len(graph.all_tables) - 20} more")
            return
        
        deps = graph.get_dependencies(qualified_name)
        
        print(f"\n{Colors.OKGREEN}{Colors.BOLD}Dependencies for {qualified_name}:{Colors.ENDC}")
        
        if deps['parents']:
            print(f"\n{Colors.OKBLUE}Parent Tables (this table depends on):{Colors.ENDC}")
            for parent in deps['parents']:
                print(f"  ← {parent}")
        else:
            print(f"\n{Colors.OKBLUE}No parent dependencies{Colors.ENDC} (independent or root table)")
        
        if deps['children']:
            print(f"\n{Colors.WARNING}Child Tables (depend on this table):{Colors.ENDC}")
            for child in deps['children']:
                print(f"  → {child}")
        else:
            print(f"\n{Colors.OKGREEN}No child dependencies{Colors.ENDC} (leaf table)")
        
        # Check if self-referencing
        if qualified_name in graph.self_referencing_tables:
            print(f"\n{Colors.WARNING}⚠ Self-Referencing Table{Colors.ENDC}")
            print("  This table has FK references to itself")
    
    else:
        # Show overall statistics
        print(f"\n{Colors.OKGREEN}{Colors.BOLD}Dependency Graph Statistics:{Colors.ENDC}")
        
        independent = graph.get_independent_tables()
        print(f"\n{Colors.OKBLUE}Independent Tables (no FK dependencies):{Colors.ENDC} {len(independent)}")
        for tbl in independent[:10]:
            print(f"  • {tbl}")
        if len(independent) > 10:
            print(f"  ... and {len(independent) - 10} more")
        
        if graph.self_referencing_tables:
            print(f"\n{Colors.WARNING}Self-Referencing Tables:{Colors.ENDC} {len(graph.self_referencing_tables)}")
            for tbl in sorted(graph.self_referencing_tables):
                print(f"  ⟲ {tbl}")
        
        # Check for cycles
        is_cyclic = graph.is_cyclic()
        if is_cyclic:
            cycles = graph.detect_cycles()
            print(f"\n{Colors.FAIL}{Colors.BOLD}⚠ Circular Dependencies Detected:{Colors.ENDC} {len(cycles)} cycle(s)")
            for i, cycle in enumerate(cycles[:5], 1):
                cycle_str = " → ".join(cycle)
                print(f"  {i}. {cycle_str}")
            if len(cycles) > 5:
                print(f"  ... and {len(cycles) - 5} more cycles")
        else:
            print(f"\n{Colors.OKGREEN}✓ No circular dependencies{Colors.ENDC}")
    
    print()  # Empty line before exit


def handle_check_cycles(connection, logger=None) -> None:
    """
    Check for circular dependencies in database schema.
    
    Args:
        connection: Database connection
        logger: Logger instance
    """
    from database.dependency_graph_builder import DependencyGraph
    
    logger = logger or logging.getLogger(__name__)
    
    print(f"\n{Colors.HEADER}{Colors.BOLD}═══ Circular Dependency Check ═══{Colors.ENDC}\n")
    
    # Build dependency graph
    print(f"{Colors.OKCYAN}Analyzing database schema...{Colors.ENDC}")
    graph = DependencyGraph(connection, logger=logger)
    graph.build_graph()
    
    print(f"  • Total tables analyzed: {len(graph.all_tables)}")
    print(f"  • Total FK relationships: {len(graph.relationships)}")
    
    # Check for cycles
    print(f"\n{Colors.OKCYAN}Detecting circular dependencies...{Colors.ENDC}")
    is_cyclic = graph.is_cyclic()
    
    if is_cyclic:
        cycles = graph.detect_cycles()
        print(f"\n{Colors.FAIL}{Colors.BOLD}✗ CIRCULAR DEPENDENCIES FOUND{Colors.ENDC}")
        print(f"\n{Colors.WARNING}Found {len(cycles)} circular dependency cycle(s):{Colors.ENDC}\n")
        
        for i, cycle in enumerate(cycles, 1):
            cycle_str = " → ".join(cycle)
            print(f"  {i}. {cycle_str}")
        
        print(f"\n{Colors.WARNING}Impact:{Colors.ENDC}")
        print("  • Topological sort cannot be computed")
        print("  • Database-level desanitization requires special handling")
        print("  • FK constraints must be temporarily disabled for these tables")
        
        # Get strongly connected components
        sccs = graph.get_strongly_connected_components()
        if sccs:
            print(f"\n{Colors.OKCYAN}Strongly Connected Components (mutual dependencies):{Colors.ENDC}")
            for i, scc in enumerate(sccs, 1):
                print(f"  {i}. {', '.join(sorted(scc))}")
        
        print(f"\n{Colors.WARNING}Recommendation:{Colors.ENDC}")
        print("  Use constraint-aware restoration mode or process these tables")
        print("  with temporarily disabled FK constraints (Story 2.4).")
        
        sys.exit(1)  # Exit with error code
    
    else:
        print(f"\n{Colors.OKGREEN}{Colors.BOLD}✓ NO CIRCULAR DEPENDENCIES{Colors.ENDC}")
        print(f"\n{Colors.OKGREEN}Database schema is acyclic:{Colors.ENDC}")
        print("  • Topological sort can be computed")
        print("  • Safe for sequential table-by-table processing")
        print("  • Database-level desanitization is supported")
        
        # Show topological order
        try:
            sorted_tables = graph.topological_sort()
            print(f"\n{Colors.OKCYAN}Topological Order (safe restoration order):{Colors.ENDC}")
            for i, table in enumerate(sorted_tables[:10], 1):
                print(f"  {i}. {table}")
            if len(sorted_tables) > 10:
                print(f"  ... and {len(sorted_tables) - 10} more tables")
        except Exception as e:
            logger.debug(f"Could not compute topological sort: {e}")
        
        print()


def handle_list_checkpoints(conn_string: str, logger=None) -> None:
    """
    List incomplete desanitization operations that can be resumed.
    
    Args:
        conn_string: Database connection string
        logger: Logger instance
    """
    from desanitization.checkpoint_manager import CheckpointManager
    
    logger = logger or logging.getLogger(__name__)
    
    print(f"\n{Colors.HEADER}{Colors.BOLD}═══ Incomplete Desanitization Operations ═══{Colors.ENDC}\n")
    
    try:
        checkpoint_mgr = CheckpointManager(conn_string)
        
        # Validate checkpoint table exists
        try:
            checkpoint_mgr.validate_schema()
        except Exception:
            print(f"{Colors.WARNING}Checkpoint table does not exist or is invalid.{Colors.ENDC}")
            print(f"{Colors.OKCYAN}Create it with: CheckpointManager.create_table(){Colors.ENDC}\n")
            return
        
        # Get incomplete operations
        incomplete_ops = checkpoint_mgr.list_incomplete_operations(max_age_hours=24)
        
        if not incomplete_ops:
            print(f"{Colors.OKGREEN}✓ No incomplete operations found (within last 24 hours){Colors.ENDC}\n")
            return
        
        print(f"{Colors.OKCYAN}Found {len(incomplete_ops)} incomplete operation(s):{Colors.ENDC}\n")
        
        # Display details for each operation
        for idx, op_id in enumerate(incomplete_ops, 1):
            status = checkpoint_mgr.get_operation_status(op_id)
            
            if status:
                age_hours = (datetime.now() - status.started_at).total_seconds() / 3600 if status.started_at else 0
                
                print(f"{Colors.BOLD}{idx}. Operation ID:{Colors.ENDC} {op_id}")
                print(f"   Status: {status.completed_tables}/{status.total_tables} completed, "
                      f"{status.failed_tables} failed, {status.pending_tables + status.in_progress_tables} remaining")
                print(f"   Started: {status.started_at.strftime('%Y-%m-%d %H:%M:%S') if status.started_at else 'N/A'} "
                      f"({age_hours:.1f}h ago)")
                
                if status.has_failures:
                    print(f"   {Colors.WARNING}⚠ Has failures{Colors.ENDC}")
                
                print()
        
        print(f"{Colors.OKCYAN}To resume an operation:{Colors.ENDC}")
        print(f"  python desanitize_direct.py --database --resume <OPERATION_ID> --execute")
        print()
        
    except Exception as e:
        logger.error(f"Failed to list checkpoints: {e}")
        print(f"\n{Colors.FAIL}✖ Error: {e}{Colors.ENDC}\n")


def handle_clear_stale_checkpoints(conn_string: str, logger=None) -> None:
    """
    Remove checkpoint records older than 24 hours.
    
    Args:
        conn_string: Database connection string
        logger: Logger instance
    """
    from desanitization.checkpoint_manager import CheckpointManager
    
    logger = logger or logging.getLogger(__name__)
    
    print(f"\n{Colors.HEADER}{Colors.BOLD}═══ Clear Stale Checkpoints ═══{Colors.ENDC}\n")
    
    try:
        checkpoint_mgr = CheckpointManager(conn_string)
        
        # Validate checkpoint table exists
        try:
            checkpoint_mgr.validate_schema()
        except Exception:
            print(f"{Colors.WARNING}Checkpoint table does not exist or is invalid.{Colors.ENDC}")
            print(f"{Colors.OKCYAN}Nothing to clear.{Colors.ENDC}\n")
            return
        
        # Confirm cleanup
        print(f"{Colors.WARNING}This will remove checkpoint records older than 24 hours{Colors.ENDC}")
        print("(Only COMPLETED and FAILED status; PENDING/IN_PROGRESS preserved)\n")
        response = input("Type 'yes' to confirm: ").strip().lower()
        
        if response != 'yes':
            print(f"\n{Colors.WARNING}Operation cancelled.{Colors.ENDC}\n")
            return
        
        # Clear stale checkpoints
        deleted_count = checkpoint_mgr.clear_stale_checkpoints(max_age_hours=24)
        
        print(f"\n{Colors.OKGREEN}✓ Removed {deleted_count} checkpoint record(s){Colors.ENDC}\n")
        
    except Exception as e:
        logger.error(f"Failed to clear checkpoints: {e}")
        print(f"\n{Colors.FAIL}✖ Error: {e}{Colors.ENDC}\n")


def handle_list_batches(conn_string: str, json_output: bool = False, logger=None) -> None:
    """
    List available sanitization batches with metadata.
    
    Args:
        conn_string: Database connection string
        json_output: Whether to output as JSON
        logger: Logger instance
    """
    from mapping import MappingTableManager
    
    logger = logger or logging.getLogger(__name__)
    
    if not json_output:
        print(f"\n{Colors.HEADER}{Colors.BOLD}═══ Available Sanitization Batches ═══{Colors.ENDC}\n")
    
    try:
        mapping_mgr = MappingTableManager(conn_string)
        
        # Validate mapping table exists
        try:
            mapping_mgr.validate_schema()
        except Exception:
            if not json_output:
                print(f"{Colors.WARNING}Mapping table does not exist or is invalid.{Colors.ENDC}")
                print(f"{Colors.OKCYAN}Run sanitization first to create mappings.{Colors.ENDC}\n")
            else:
                print(json.dumps({"error": "Mapping table not found", "batches": []}, indent=2))
            return
        
        # List available batches
        batches = mapping_mgr.list_available_batches()
        
        if not batches:
            if not json_output:
                print(f"{Colors.WARNING}No sanitization batches found.{Colors.ENDC}")
                print(f"{Colors.OKCYAN}Run sanitization to create batches.{Colors.ENDC}\n")
            else:
                print(json.dumps({"batches": []}, indent=2))
            return
        
        # Output as JSON
        if json_output:
            batch_list = [
                {
                    "batch_id": b.batch_id,
                    "row_count": b.row_count,
                    "earliest_timestamp": b.earliest_timestamp.isoformat(),
                    "latest_timestamp": b.latest_timestamp.isoformat(),
                    "affected_tables": b.affected_tables,
                    "affected_columns": b.affected_columns
                }
                for b in batches
            ]
            print(json.dumps({"batches": batch_list}, indent=2))
            return
        
        # Display table format
        print(f"{Colors.OKCYAN}Found {len(batches)} sanitization batch(es):{Colors.ENDC}\n")
        
        for idx, batch in enumerate(batches, 1):
            # Calculate batch age
            age = datetime.now() - batch.latest_timestamp
            age_str = f"{age.days}d" if age.days > 0 else f"{age.seconds // 3600}h"
            
            print(f"{Colors.BOLD}{idx}. Batch ID:{Colors.ENDC} {batch.batch_id}")
            print(f"   Mappings: {batch.row_count:,} records")
            print(f"   Tables: {len(batch.affected_tables)} ({', '.join(batch.affected_tables[:3])}"
                  f"{'...' if len(batch.affected_tables) > 3 else ''})")
            print(f"   Columns: {len(batch.affected_columns)} unique columns")
            print(f"   Created: {batch.earliest_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Latest: {batch.latest_timestamp.strftime('%Y-%m-%d %H:%M:%S')} ({age_str} ago)")
            print()
        
        print(f"{Colors.OKCYAN}To restore from a specific batch:{Colors.ENDC}")
        print(f"  python desanitize_direct.py --table-only <TABLE> --batch-id <BATCH_ID> --execute")
        print()
        
    except Exception as e:
        logger.error(f"Failed to list batches: {e}")
        if not json_output:
            print(f"\n{Colors.FAIL}✖ Error: {e}{Colors.ENDC}\n")
        else:
            print(json.dumps({"error": str(e), "batches": []}, indent=2))


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments using subcommand architecture.
    
    Returns:
        Parsed arguments namespace with 'subcommand' field indicating mode
    """
    # Create parent parser with global arguments
    parser = argparse.ArgumentParser(
        description='Desanitize database records by restoring original values from mapping tables',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Record-level restoration (specific records by ID)
  %(prog)s record --table Customers --record-ids "123" "456" --dry-run
  %(prog)s record --table Customers --record-ids "123" "456" --execute
  %(prog)s record --table Orders --record-ids "999" --skip-missing --execute
  
  # Column-level restoration (all records in specified columns)
  %(prog)s column --table Customers --columns Email PhoneNumber --dry-run
  %(prog)s column --table Users --columns SSN DateOfBirth --execute --yes
  
  # Table-level restoration (all columns with mappings)
  %(prog)s table --table Customers --dry-run
  %(prog)s table --table Orders --execute --yes
  
  # Database-level restoration (entire database with FK-safe ordering)
  %(prog)s database --dry-run
  %(prog)s database --execute --parallel 4 --yes
  %(prog)s database --execute --resume DESAN-20260413... --yes
  
  # Batch management and validation
  %(prog)s list-batches
  %(prog)s list-batches --json-output batches.json
  %(prog)s validate --table Customers --record-ids "123"
  %(prog)s validate --database

For detailed help on each command:
  %(prog)s record --help
  %(prog)s column --help
  %(prog)s table --help
  %(prog)s database --help
        """
    )
    
    # Global arguments (apply to all subcommands)
    parser.add_argument(
        '--config',
        default='config/pii_config.example.json',
        help='Path to configuration file (default: config/pii_config.example.json)'
    )
    
    parser.add_argument(
        '--json-output',
        help='Save report as JSON to specified file'
    )
    
    parser.add_argument(
        '--no-color',
        action='store_true',
        help='Disable colored output'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging (DEBUG level)'
    )
    
    parser.add_argument(
        '--skip-audit',
        action='store_true',
        help='Skip audit logging (EMERGENCY USE ONLY - not recommended for compliance)'
    )
    
    # Security / RBAC arguments (Story 7.1)
    parser.add_argument(
        '--security-enabled',
        action='store_true',
        help='Enable role-based access control (overrides config)'
    )
    
    parser.add_argument(
        '--allowed-roles',
        nargs='+',
        metavar='ROLE',
        help='Database roles allowed to perform desanitization (e.g., DataRestorer db_owner)'
    )
    
    parser.add_argument(
        '--require-role-for-dry-run',
        action='store_true',
        help='Require role membership even for dry-run/preview operations'
    )
    
    parser.add_argument(
        '--skip-security-check',
        action='store_true',
        help='Emergency override: disable role-based access control (USE WITH EXTREME CAUTION)'
    )
    
    # Create subparsers for different operations
    subparsers = parser.add_subparsers(
        title='Available commands',
        description='Choose a desanitization operation to perform',
        dest='subcommand',
        required=True,
        help='Desanitization mode'
    )
    
    # ========================
    # RECORD SUBCOMMAND
    # ========================
    parser_record = subparsers.add_parser(
        'record',
        help='Restore original values for specific records by ID',
        description='Record-level desanitization: Restore original values for specific records identified by primary key',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run (preview only - safe default)
  %(prog)s --table Customers --record-ids "123" "456" --dry-run
  
  # Execute restoration
  %(prog)s --table Customers --record-ids "123" "456" --execute --yes
  
  # Restore from specific batch
  %(prog)s --table Users --batch-id "BATCH-20260409" --record-ids "AAA" --execute
  
  # Skip missing mappings
  %(prog)s --table Orders --record-ids "999" --skip-missing --execute
        """
    )
    
    parser_record.add_argument('--table', required=True, help='Name of table containing records to restore')
    parser_record.add_argument('--record-ids', nargs='+', required=True, 
                              help='List of record IDs to restore (space-separated)')
    parser_record.add_argument('--schema', default='dbo', help='Database schema (default: dbo)')
    parser_record.add_argument('--batch-id', help='Filter by batch ID (only restore mappings from this batch)')
    parser_record.add_argument('--dry-run', action='store_true', help='Preview changes without committing (default when --execute not provided)')
    parser_record.add_argument('--execute', action='store_true', help='Execute restoration (commits changes to database)')
    parser_record.add_argument('--skip-missing', action='store_true', help='Skip records without mappings instead of error')
    parser_record.add_argument('--skip-post-verification', action='store_true', help='Skip post-restoration verification')
    parser_record.add_argument('--strict-verification', action='store_true', help='Treat verification warnings as errors')
    parser_record.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt (automatic yes)')
    
    # ========================
    # COLUMN SUBCOMMAND
    # ========================
    parser_column = subparsers.add_parser(
        'column',
        help='Restore original values for all records in specified columns',
        description='Column-level desanitization: Restore original values for ALL records in specified columns',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview column restoration
  %(prog)s --table Customers --columns Email PhoneNumber --dry-run
  
  # Execute column restoration
  %(prog)s --table Users --columns SSN DateOfBirth --execute --yes
  
  # Restore single column from specific batch
  %(prog)s --table Employees --columns Salary --batch-id "BATCH-20260409" --execute
        """
    )
    
    parser_column.add_argument('--table', required=True, help='Name of table containing columns to restore')
    parser_column.add_argument('--columns', nargs='+', required=True, 
                              help='List of column names to restore (space-separated) - restores ALL records')
    parser_column.add_argument('--schema', default='dbo', help='Database schema (default: dbo)')
    parser_column.add_argument('--batch-id', help='Filter by batch ID (only restore mappings from this batch)')
    parser_column.add_argument('--dry-run', action='store_true', help='Preview changes without committing (default when --execute not provided)')
    parser_column.add_argument('--execute', action='store_true', help='Execute restoration (commits changes to database)')
    parser_column.add_argument('--skip-post-verification', action='store_true', help='Skip post-restoration verification')
    parser_column.add_argument('--strict-verification', action='store_true', help='Treat verification warnings as errors')
    parser_column.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt (automatic yes)')
    
    # ========================
    # TABLE SUBCOMMAND
    # ========================
    parser_table = subparsers.add_parser(
        'table',
        help='Restore original values for all columns with mappings in a table',
        description='Table-level desanitization: Restore original values for ALL columns with mappings in the specified table',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview table restoration
  %(prog)s --table Customers --dry-run
  
  # Execute full table restoration
  %(prog)s --table Orders --execute --yes
  
  # Restore table from specific batch
  %(prog)s --table Products --batch-id "BATCH-20260409" --execute
        """
    )
    
    parser_table.add_argument('--table', required=True, help='Name of table to fully restore')
    parser_table.add_argument('--schema', default='dbo', help='Database schema (default: dbo)')
    parser_table.add_argument('--batch-id', help='Filter by batch ID (only restore mappings from this batch)')
    parser_table.add_argument('--dry-run', action='store_true', help='Preview changes without committing (default when --execute not provided)')
    parser_table.add_argument('--execute', action='store_true', help='Execute restoration (commits changes to database)')
    parser_table.add_argument('--skip-post-verification', action='store_true', help='Skip post-restoration verification')
    parser_table.add_argument('--strict-verification', action='store_true', help='Treat verification warnings as errors')
    parser_table.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt (automatic yes)')
    
    # ========================
    # DATABASE SUBCOMMAND
    # ========================
    parser_database = subparsers.add_parser(
        'database',
        help='Restore original values for entire database with FK-safe ordering',
        description='Database-level desanitization: Restore original values for ALL tables with mappings using FK-safe dependency ordering',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview database restoration
  %(prog)s --dry-run
  
  # Execute database restoration (sequential mode)
  %(prog)s --execute --yes
  
  # Parallel restoration with 4 workers
  %(prog)s --execute --parallel 4 --yes
  
  # Resume from previous checkpoint
  %(prog)s --execute --resume DESAN-20260413... --yes
  
  # Incremental restoration with rate limiting
  %(prog)s --execute --date-range "2026-04-01:2026-04-13" --rate-limit 500 --yes
  
  # Filter to specific schema
  %(prog)s --execute --schema-filter sales --yes
        """
    )
    
    parser_database.add_argument('--schema', default='dbo', help='Database schema (default: dbo)')
    parser_database.add_argument('--batch-id', help='Filter by batch ID (only restore mappings from this batch)')
    parser_database.add_argument('--dry-run', action='store_true', help='Preview changes without committing (default when --execute not provided)')
    parser_database.add_argument('--execute', action='store_true', help='Execute restoration (commits changes to database)')
    parser_database.add_argument('--skip-post-verification', action='store_true', help='Skip post-restoration verification')
    parser_database.add_argument('--strict-verification', action='store_true', help='Treat verification warnings as errors')
    parser_database.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt (automatic yes)')
    
    # Database-specific options
    parser_database.add_argument('--schema-filter', help='Filter restoration to specific schema')
    parser_database.add_argument('--resume', metavar='OPERATION_ID', help='Resume from previous checkpoint')
    parser_database.add_argument('--strict', action='store_true', help='Stop on first error (default: continue-on-error)')
    
    # Story 5.1: Parallel processing
    parallel_group = parser_database.add_mutually_exclusive_group()
    parallel_group.add_argument('--parallel', type=int, metavar='N', dest='max_workers',
                               help='Enable parallel processing with N worker threads (recommended: 4-8)')
    parallel_group.add_argument('--no-parallel', action='store_true', help='Explicitly disable parallel processing')
    
    # Story 5.2: Incremental desanitization
    parser_database.add_argument('--date-range', metavar='START:END',
                                help='Filter mappings by date range (format: YYYY-MM-DD:YYYY-MM-DD)')
    parser_database.add_argument('--rate-limit', type=int, metavar='MILLISECONDS', default=0,
                                help='Rate limiting delay in milliseconds between operations (default: 0 = no limit)')
    
    # ========================
    # LIST-BATCHES SUBCOMMAND
    # ========================
    parser_batches = subparsers.add_parser(
        'list-batches',
        help='List available sanitization batches with metadata',
        description='Display all sanitization batches with row counts, affected tables/columns, and timestamps'
    )
    
    # ========================
    # VALIDATE SUBCOMMAND
    # ========================
    parser_validate = subparsers.add_parser(
        'validate',
        help='Run pre-flight validation checks without executing desanitization',
        description='Validation mode: Run pre-flight checks to verify mappings exist and schema is compatible',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate record restoration
  %(prog)s --table Customers --record-ids "123" "456"
  
  # Validate column restoration
  %(prog)s --table Users --columns SSN Email
  
  # Validate table restoration
  %(prog)s --table Orders
  
  # Validate database restoration
  %(prog)s --database
        """
    )
    
    # Validation accepts same arguments as restoration modes
    parser_validate.add_argument('--table', help='Table to validate (required unless --database)')
    parser_validate.add_argument('--record-ids', nargs='+', help='Record IDs to validate')
    parser_validate.add_argument('--columns', nargs='+', help='Columns to validate')
    parser_validate.add_argument('--database', action='store_true', help='Validate entire database')
    parser_validate.add_argument('--schema', default='dbo', help='Database schema (default: dbo)')
    parser_validate.add_argument('--batch-id', help='Filter by batch ID')
    
    # ========================
    # VALIDATE-CONFIG SUBCOMMAND
    # ========================
    parser_validate_config = subparsers.add_parser(
        'validate-config',
        help='Validate configuration file without executing any operations',
        description='Configuration validation: Load and validate configuration file with merged CLI/env overrides',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate default config
  %(prog)s
  
  # Validate specific config file
  %(prog)s --config config/desanitization_config.json
  
  # Show merged configuration (file + env + CLI overrides)
  %(prog)s --config config/my_config.json --verbose
        """
    )
    
    parser_validate_config.add_argument(
        '--show-merged',
        action='store_true',
        help='Display merged configuration (file + env vars + CLI overrides)'
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Subcommand-specific validation
    if args.subcommand == 'validate':
        # Validate mode requires table OR database
        if not args.table and not args.database:
            parser.error("validate command requires --table or --database")
    
    if args.subcommand == 'database':
        # Validate max_workers
        if hasattr(args, 'max_workers') and args.max_workers and args.max_workers < 1:
            parser.error(f"--parallel must specify at least 1 worker (got: {args.max_workers})")
        
        # Story 5.2: Validate and parse date range
        if hasattr(args, 'date_range') and args.date_range:
            try:
                from datetime import datetime
                date_parts = args.date_range.split(':')
                if len(date_parts) != 2:
                    parser.error(f"Invalid --date-range format: '{args.date_range}'. Expected: YYYY-MM-DD:YYYY-MM-DD")
                
                start_str, end_str = date_parts
                args.date_range_start = datetime.strptime(start_str.strip(), '%Y-%m-%d')
                args.date_range_end = datetime.strptime(end_str.strip(), '%Y-%m-%d')
                
                if args.date_range_start > args.date_range_end:
                    parser.error(f"Invalid --date-range: Start date must be <= end date")
            except ValueError as e:
                parser.error(f"Invalid date format in --date-range: {e}. Expected: YYYY-MM-DD:YYYY-MM-DD")
        else:
            args.date_range_start = None
            args.date_range_end = None
        
        # Validate rate limit
        if hasattr(args, 'rate_limit') and args.rate_limit < 0:
            parser.error("--rate-limit must be >= 0 (0 = no rate limiting)")
    else:
        # Set defaults for non-database subcommands
        args.date_range_start = None
        args.date_range_end = None
        if not hasattr(args, 'rate_limit'):
            args.rate_limit = 0
    
    # Handle --execute flag (overrides --dry-run) for restoration subcommands
    if hasattr(args, 'execute') and args.execute:
        args.dry_run = False
    elif not hasattr(args, 'dry_run'):
        args.dry_run = True  # Default for non-restoration subcommands
    
    return args


def main():
    """Main desanitization workflow."""
    try:
        # Parse arguments
        args = parse_arguments()
        
        # Initialize logging
        logger = setup_logging(args.verbose)
        
        # Print banner
        if not args.no_color:
            print_banner()
        
        # Load configuration
        logger.info(f"Loading configuration from: {args.config}")
        config = load_config(args.config, logger)
        
        # Apply CLI argument overrides (CLI args > config file > defaults)
        config = apply_cli_overrides(config, args)
        
        logger.info(
            f"Configuration merged: dry_run={config.restoration.dry_run}, "
            f"parallel={config.performance.enable_parallel}, "
            f"encryption={config.mapping.encryption.enabled}"
        )
        
        # Handle validate-config subcommand (early exit, no DB connection needed)
        if args.subcommand == 'validate-config':
            print(f"\n{Colors.HEADER}{Colors.BOLD}═══ Configuration Validation ═══{Colors.ENDC}\n")
            
            print(f"{Colors.OKGREEN}✓ Configuration loaded successfully{Colors.ENDC}")
            print(f"  File: {args.config}")
            print(f"  Database: {config.database.server}/{config.database.database}")
            print(f"  Mapping table: {config.mapping.schema_name}.{config.mapping.table_name}")
            print(f"  Encryption: {'Enabled' if config.mapping.encryption.enabled else 'Disabled'}")
            print(f"  Audit: {'Enabled' if config.audit.enabled else 'Disabled'}")
            print()
            
            # Show merged configuration if requested
            if args.show_merged:
                print(f"{Colors.OKCYAN}Merged Configuration (file + env + CLI overrides):{Colors.ENDC}\n")
                config_dict = config.to_dict()
                print(json.dumps(config_dict, indent=2, default=str))
                print()
            
            print(f"{Colors.OKGREEN}✓ All configuration checks passed{Colors.ENDC}\n")
            return 0
        
        # Build connection string
        conn_string = build_connection_string(config.database)
        
        # Handle list-batches subcommand (early exit, minimal DB connection needed)
        if args.subcommand == 'list-batches':
            handle_list_batches(conn_string, json_output=bool(args.json_output), logger=logger)
            return 0
        
        # Connect to database
        logger.info(f"Connecting to database: {config.database.database}")
        conn = pyodbc.connect(conn_string)
        conn.autocommit = False  # Explicit transaction control
        
        
        # Story 5.2: Display incremental desanitization settings
        if args.date_range_start:
            logger.info(
                f"{Colors.OKBLUE}Date range filtering enabled:{Colors.ENDC} "
                f"{args.date_range_start.strftime('%Y-%m-%d')} to "
                f"{args.date_range_end.strftime('%Y-%m-%d')}"
            )
        
        if config.performance.rate_limit_ms > 0:
            logger.warning(
                f"{Colors.WARNING}⚠️ Rate limiting active:{Colors.ENDC} "
                f"{config.performance.rate_limit_ms}ms delay between column restorations. "
                f"This will increase total execution time."
            )
        
        # Handle validation subcommand
        if args.subcommand == 'validate':
            from validation import DesanitizationValidator
            
            logger.info("Running validation-only mode...")
            
            # Initialize encryption if enabled
            encryptor = load_encryption_from_config(config, logger)
            
            # Initialize components needed for validation
            mapping_manager = MappingTableManager(
                connection_string=conn_string,
                table_name=config.mapping.table_name,
                encryptor=encryptor
            )
            schema_inspector = SchemaInspector(conn_string)
            
            # Create validator
            validator = DesanitizationValidator(
                connection=conn,
                mapping_manager=mapping_manager,
                schema_inspector=schema_inspector,
                logger=logger
            )
            
            # Determine scope and parameters from validate subcommand arguments
            if hasattr(args, 'database') and args.database:
                scope = 'database'
                table = None
                columns = None
                record_ids = None
            elif hasattr(args, 'columns') and args.columns:
                scope = 'column'
                table = args.table
                columns = args.columns
                record_ids = None
            elif hasattr(args, 'record_ids') and args.record_ids:
                scope = 'record'
                table = args.table
                columns = None
                record_ids = args.record_ids
            else:  # table-level
                scope = 'table'
                table = args.table
                columns = None
                record_ids = None
            
            # Run validation
            validation_report = validator.validate_desanitization(
                scope=scope,
                table=table,
                schema=args.schema,
                columns=columns,
                record_ids=record_ids,
                batch_id=getattr(args, 'batch_id', None)
            )
            
            # Display validation report
            display_validation_report(validation_report, colored=not args.no_color)
            
            # Save JSON output if requested
            if args.json_output:
                with open(args.json_output, 'w') as f:
                    json.dump(validation_report.to_dict(), f, indent=2)
                logger.info(f"Validation report saved to {args.json_output}")
            
            conn.close()
            
            # Exit with appropriate status code
            if validation_report.is_valid():
                return 0  # Success
            else:
                return 1  # Validation failed
        
        # Initialize components (for restoration operations)
        logger.info("Initializing desanitization engine...")
        
        # Initialize encryption if enabled
        encryptor = load_encryption_from_config(config, logger)
        
        mapping_manager = MappingTableManager(
            connection_string=conn_string,
            table_name=config.mapping.table_name,
            encryptor=encryptor
        )
        schema_inspector = SchemaInspector(conn_string)
        
        # Initialize DependencyGraph for database-level operations
        dependency_graph = None
        if args.subcommand == 'database':
            from database.dependency_graph_builder import DependencyGraph
            dependency_graph = DependencyGraph(conn, logger=logger)
        
        # Initialize CheckpointManager for database-level operations
        checkpoint_manager = None
        if args.subcommand == 'database':
            from desanitization.checkpoint_manager import CheckpointManager
            checkpoint_manager = CheckpointManager(conn_string)
            
            # Create checkpoint table if it doesn't exist
            try:
                if checkpoint_manager.create_table(drop_existing=False):
                    logger.info("Created checkpoint table")
                else:
                    checkpoint_manager.validate_schema()
                    logger.info("Checkpoint table exists and is valid")
            except Exception as e:
                logger.warning(f"Checkpoint table setup failed: {e}. Continuing without checkpoint support.")
                checkpoint_manager = None
        
        # Initialize Validator for pre-flight validation
        from validation import DesanitizationValidator
        validator = DesanitizationValidator(
            connection=conn,
            mapping_manager=mapping_manager,
            schema_inspector=schema_inspector,
            logger=logger
        )
        
        # Initialize AuditLogger for compliance logging
        audit_logger = None
        if not args.skip_audit:
            try:
                audit_logger = AuditLogger(conn, fallback_to_file=True)
                logger.info("Audit logging enabled")
            except AuditTableMissingError as e:
                logger.warning(
                    f"Audit logging unavailable: {e}. "
                    "Run scripts/create_audit_log_table.sql to enable audit logging."
                )
            except Exception as e:
                logger.warning(f"Audit logger initialization failed: {e}. Continuing without audit logging.")
        else:
            logger.warning(
                f"{Colors.WARNING}AUDIT LOGGING DISABLED{Colors.ENDC} - "
                "This operation will not be logged for compliance. Use --skip-audit only in emergencies."
            )
        
        # Story 7.1: Initialize AccessControl for role-based access control
        access_control = None
        if not args.skip_security_check and config.security.enabled:
            try:
                access_control = AccessControl(conn, config.security)
                logger.info(
                    f"Role-based access control enabled - "
                    f"Required roles: {config.security.allowed_roles}"
                )
            except RoleNotFoundError as e:
                logger.error(f"Security configuration error: {e}")
                print(f"\n{Colors.FAIL}✖ Configuration Error:{Colors.ENDC} {e}\n")
                return 1
            except Exception as e:
                logger.error(f"Access control initialization failed: {e}")
                print(f"\n{Colors.FAIL}✖ Security Error:{Colors.ENDC} {e}\n")
                return 1
        elif args.skip_security_check:
            logger.warning(
                f"{Colors.WARNING}⚠️  SECURITY CHECKS DISABLED{Colors.ENDC} - "
                "Role-based access control bypassed. This should ONLY be used in emergencies. "
                "All operations will be allowed regardless of user roles."
            )
        elif not config.security.enabled:
            logger.info("Security checks disabled in configuration (backward compatible mode)")
        
        engine = DesanitizationEngine(
            connection=conn,
            mapping_manager=mapping_manager,
            schema_inspector=schema_inspector,
            logger=logger,
            dependency_graph=dependency_graph,
            checkpoint_manager=checkpoint_manager,
            validator=validator,
            audit_logger=audit_logger,
            access_control=access_control,  # Story 7.1: RBAC integration
            rate_limit_ms=args.rate_limit,  # Story 5.2
            date_range_start=args.date_range_start,  # Story 5.2
            date_range_end=args.date_range_end  # Story 5.2
        )
        
        # Confirm operation based on subcommand
        if args.subcommand == 'database':
            # Database-level mode - get table count for confirmation
            if not confirm_operation(
                database_level=True,
                table_count=None,  # Will be shown during execution
                dry_run=config.restoration.dry_run,
                yes_flag=getattr(args, 'yes', False),
                enable_parallel=hasattr(args, 'max_workers') and args.max_workers is not None and not getattr(args, 'no_parallel', False),
                max_workers=getattr(args, 'max_workers', 4) if hasattr(args, 'max_workers') and args.max_workers else 4,
                security_enabled=config.security.enabled and not args.skip_security_check,
                security_roles=config.security.allowed_roles if config.security.enabled else None
            ):
                logger.info("Operation cancelled by user")
                print(f"\n{Colors.WARNING}Operation cancelled.{Colors.ENDC}\n")
                return 0
        elif args.subcommand == 'record':
            # Record-level mode
            if not confirm_operation(
                table=args.table,
                record_count=len(args.record_ids),
                dry_run=config.restoration.dry_run,
                yes_flag=getattr(args, 'yes', False),
                security_enabled=config.security.enabled and not args.skip_security_check,
                security_roles=config.security.allowed_roles if config.security.enabled else None
            ):
                logger.info("Operation cancelled by user")
                print(f"\n{Colors.WARNING}Operation cancelled.{Colors.ENDC}\n")
                return 0
        elif args.subcommand == 'column':
            # Column-level mode
            if not confirm_operation(
                table=args.table,
                column_names=args.columns,
                dry_run=config.restoration.dry_run,
                yes_flag=getattr(args, 'yes', False),
                security_enabled=config.security.enabled and not args.skip_security_check,
                security_roles=config.security.allowed_roles if config.security.enabled else None
            ):
                logger.info("Operation cancelled by user")
                print(f"\n{Colors.WARNING}Operation cancelled.{Colors.ENDC}\n")
                return 0
        elif args.subcommand == 'table':
            # Table-level mode
            if not confirm_operation(
                table=args.table,
                table_level=True,
                dry_run=config.restoration.dry_run,
                yes_flag=getattr(args, 'yes', False),
                security_enabled=config.security.enabled and not args.skip_security_check,
                security_roles=config.security.allowed_roles if config.security.enabled else None
            ):
                logger.info("Operation cancelled by user")
                print(f"\n{Colors.WARNING}Operation cancelled.{Colors.ENDC}\n")
                return 0
        
        # Execute desanitization based on subcommand
        logger.info(f"Starting {args.subcommand}-level desanitization operation...")
        print(f"\n{Colors.OKCYAN}Processing...{Colors.ENDC}")
        
        if args.subcommand == 'database':
            # Database-level desanitization with progress callback
            def progress_callback(table, current, total, records):
                pct = (current / total * 100) if total > 0 else 0
                print(
                    f"{Colors.OKCYAN}→ Table {current}/{total}: {Colors.BOLD}{table}{Colors.ENDC} "
                    f"({records:,} records, {pct:.1f}% complete){Colors.ENDC}",
                    file=sys.stderr
                )
            
            report = engine.desanitize_database(
                schema_filter=getattr(args, 'schema_filter', None),
                batch_id=getattr(args, 'batch_id', None),
                dry_run=config.restoration.dry_run,
                resume_operation_id=getattr(args, 'resume', None),
                progress_callback=progress_callback,
                strict_mode=getattr(args, 'strict', False),
                enable_parallel=hasattr(args, 'max_workers') and args.max_workers is not None and not getattr(args, 'no_parallel', False),
                max_workers=getattr(args, 'max_workers', 4) if hasattr(args, 'max_workers') and args.max_workers else 4
            )
        elif args.subcommand == 'record':
            # Record-level desanitization
            report = engine.desanitize_records(
                table=args.table,
                record_ids=args.record_ids,
                schema=args.schema,
                batch_id=getattr(args, 'batch_id', None),
                dry_run=config.restoration.dry_run,
                skip_missing=getattr(args, 'skip_missing', False),
                skip_verification=getattr(args, 'skip_post_verification', False),
                strict_verification=getattr(args, 'strict_verification', False)
            )
        elif args.subcommand == 'column':
            # Column-level desanitization with progress callback
            def progress_callback(column, current, total, records):
                print(
                    f"{Colors.OKCYAN}→ Column {current}/{total}: {Colors.BOLD}{column}{Colors.ENDC} "
                    f"({records:,} records){Colors.ENDC}",
                    file=sys.stderr
                )
            
            report = engine.desanitize_columns(
                table=args.table,
                column_names=args.columns,
                schema=args.schema,
                batch_id=getattr(args, 'batch_id', None),
                dry_run=config.restoration.dry_run,
                progress_callback=progress_callback,
                skip_verification=getattr(args, 'skip_post_verification', False),
                strict_verification=getattr(args, 'strict_verification', False)
            )
        elif args.subcommand == 'table':
            # Table-level desanitization with progress callback
            def progress_callback(column, current, total, records):
                print(
                    f"{Colors.OKCYAN}→ Column {current}/{total}: {Colors.BOLD}{column}{Colors.ENDC} "
                    f"({records:,} records){Colors.ENDC}",
                    file=sys.stderr
                )
            
            report = engine.desanitize_table(
                table=args.table,
                schema=args.schema,
                batch_id=getattr(args, 'batch_id', None),
                dry_run=config.restoration.dry_run,
                progress_callback=progress_callback,
                skip_verification=getattr(args, 'skip_post_verification', False),
                strict_verification=getattr(args, 'strict_verification', False)
            )
        else:
            # Should not reach here due to argparse validation
            raise ValueError(f"Unknown subcommand: {args.subcommand}")
        
        # Print report
        print_report(report, colored=not args.no_color)
        
        # Save JSON output if requested
        if args.json_output:
            logger.info(f"Saving report to: {args.json_output}")
            with open(args.json_output, 'w', encoding='utf-8') as f:
                json.dump(report.to_dict(), f, indent=2)
            print(f"{Colors.OKGREEN}✓ Report saved to: {args.json_output}{Colors.ENDC}\n")
        
        # Close connection
        conn.close()
        
        # Determine exit code
        if report.errors:
            logger.error("Desanitization completed with errors")
            return 1
        elif report.warnings:
            logger.warning("Desanitization completed with warnings")
            return 0
        else:
            logger.info("Desanitization completed successfully")
            if not args.dry_run:
                print(f"{Colors.OKGREEN}{Colors.BOLD}✓ Restoration completed successfully!{Colors.ENDC}\n")
            else:
                print(f"{Colors.OKCYAN}{Colors.BOLD}✓ Dry-run completed. Use --execute to apply changes.{Colors.ENDC}\n")
            return 0
    
    except MappingNotFoundError as e:
        logger.error(f"Mapping error: {e}")
        print(f"\n{Colors.FAIL}✖ Error: {e}{Colors.ENDC}\n")
        return 2
    
    except PreconditionError as e:
        logger.error(f"Precondition error: {e}")
        print(f"\n{Colors.FAIL}✖ Error: {e}{Colors.ENDC}\n")
        return 3
    
    except PermissionDeniedError as e:
        logger.error(f"Permission denied: {e}")
        print(f"\n{Colors.FAIL}✖ Permission Denied:{Colors.ENDC} {e}\n")
        if e.required_roles:
            print(f"{Colors.WARNING}Required roles:{Colors.ENDC} {', '.join(e.required_roles)}")
        if e.user_roles:
            print(f"{Colors.WARNING}Your roles:{Colors.ENDC} {', '.join(e.user_roles) if e.user_roles else '(none)'}")
        print(f"\n{Colors.OKCYAN}Contact your database administrator to grant appropriate role membership.{Colors.ENDC}\n")
        return 8  # Permission denied exit code
    
    except DesanitizationError as e:
        logger.error(f"Desanitization error: {e}")
        print(f"\n{Colors.FAIL}✖ Error: {e}{Colors.ENDC}\n")
        return 4
    
    except FileNotFoundError as e:
        logger.error(f"File error: {e}")
        print(f"\n{Colors.FAIL}✖ File Error: {e}{Colors.ENDC}\n")
        return 5
    
    except json.JSONDecodeError as e:
        logger.error(f"Configuration parse error: {e}")
        print(f"\n{Colors.FAIL}✖ Configuration Error: Invalid JSON in config file{Colors.ENDC}\n")
        return 6
    
    except pyodbc.Error as e:
        logger.error(f"Database error: {e}")
        print(f"\n{Colors.FAIL}✖ Database Error: {e}{Colors.ENDC}\n")
        return 7
    
    except KeyboardInterrupt:
        logger.info("Operation interrupted by user")
        print(f"\n\n{Colors.WARNING}Operation interrupted by user.{Colors.ENDC}\n")
        return 130
    
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        print(f"\n{Colors.FAIL}✖ Unexpected Error: {e}{Colors.ENDC}\n")
        print(f"See logs for details.\n")
        return 99


if __name__ == '__main__':
    sys.exit(main())
