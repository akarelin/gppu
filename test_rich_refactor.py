#!/usr/bin/env python3
"""Test script to verify Rich library refactoring of GPPU."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from gppu import (
    pcp, dpcp, pfy, Logger, TColor, init_logger,
    dict_from_yml, deepget, safe_int, console
)

def test_colors():
    """Test TColor with Rich styling."""
    print("\n=== Testing TColor with Rich ===")
    
    # Test individual colors
    pcp("BR", "Error Text", "NONE", "Normal", "BG", "Success Text")
    pcp("BY", "Warning Text", "BLUE", "Info Text")
    pcp("GRAY0", "Darkest", "GRAY1", "Dark", "GRAY2", "Medium", "GRAY3", "Light", "GRAY4", "Lightest")
    
    # Test background colors
    pcp("WRED", "White on Red", "WBLUE", "White on Blue", "WGREEN", "White on Green")
    pcp("WYELLOW", "Black on Yellow", "WPURPLE", "White on Purple")
    
    # Print color table
    print("\n=== Available Colors Table ===")
    TColor.print()

def test_pfy():
    """Test pretty formatting with Rich."""
    print("\n=== Testing pfy() with Rich ===")
    
    test_data = {
        "name": "Test App",
        "version": "1.0.0",
        "features": ["logging", "colors", "formatting"],
        "config": {
            "debug": True,
            "port": 8080,
            "database": {
                "host": "localhost",
                "port": 5432,
                "credentials": {
                    "user": "admin",
                    "password": "***"
                }
            }
        }
    }
    
    print("Pretty formatted output:")
    print(pfy(test_data))

def test_logging():
    """Test logging with Rich handler."""
    print("\n=== Testing Logger with Rich ===")
    
    # Initialize logger with trace rules
    init_logger('TestApp', trace_rules={'debug': True, 'all': False})
    
    # Test different log levels
    Logger.Debug("This is a debug message")
    Logger.Info("Application started successfully")
    Logger.Warn("This is a warning message")
    Logger.Error("This is an error message")
    
    # Test with additional arguments
    Logger.Info("Processing", "user_id=123", "status=active")
    
def test_dpcp():
    """Test dpcp with Rich formatting."""
    print("\n=== Testing dpcp() with Rich ===")
    
    # Enable tracing for this test
    init_logger('TestApp', trace_rules={'test_dpcp': True, 'all': True})
    
    def inner_function():
        dpcp("Inside inner function", "with", "multiple", "arguments")
        dpcp("BR", "Error severity", severity="Error")
        dpcp("BY", "Warning severity", severity="Warn")
        dpcp("BLUE", "Info severity", severity="Info")
    
    inner_function()

def test_mixed_usage():
    """Test mixed usage of colors and text."""
    print("\n=== Testing Mixed Usage ===")
    
    # Complex colorized output
    pcp("Starting", "BG", "OK", "NONE", "- Processing", "BY", "3", "NONE", "items")
    
    # With verbose mode
    pcp("Debug info", verbose=True, data={"key": "value", "count": 42})

def test_console_direct():
    """Test direct Rich console usage."""
    print("\n=== Testing Direct Console Usage ===")
    
    # Direct Rich console features
    console.print("Direct console output with [bold red]Rich[/bold red] markup!")
    console.print("Success!", style="bold green")
    
    # Rich table
    from rich.table import Table
    table = Table(title="Sample Data")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="magenta")
    table.add_column("Status", style="green")
    
    table.add_row("1", "Item One", "Active")
    table.add_row("2", "Item Two", "Pending")
    table.add_row("3", "Item Three", "Completed")
    
    console.print(table)

def main():
    """Run all tests."""
    print("=" * 60)
    print("GPPU Rich Library Refactoring Test Suite")
    print("=" * 60)
    
    test_colors()
    test_pfy()
    test_logging()
    test_dpcp()
    test_mixed_usage()
    test_console_direct()
    
    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()