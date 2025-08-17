#!/usr/bin/env python3
"""Test the new timezone and scheduling preview features."""

import uvicorn
from datetime import datetime, timezone
from silica.cron.app import app
from silica.cron.scheduler import scheduler


def test_timezone_features():
    print("🕐 Testing Timezone & Scheduling Features")
    print("=" * 50)

    # Test cron validation
    test_expressions = [
        "0 9 * * *",  # Daily at 9 AM
        "*/15 * * * *",  # Every 15 minutes
        "0 0 * * 1",  # Weekly Monday
        "invalid cron",  # Invalid
    ]

    for expr in test_expressions:
        valid, error = scheduler.validate_cron_expression(expr)
        if valid:
            next_runs = scheduler.get_next_runs(expr, 3)
            print(f"✓ '{expr}' - Valid")
            for i, run in enumerate(next_runs, 1):
                local_time = run.astimezone()
                print(f"  {i}. {local_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        else:
            print(f"✗ '{expr}' - Invalid: {error}")
        print()

    print("🌐 UTC Implementation Details:")
    print(f"• Server UTC time: {datetime.now(timezone.utc).isoformat()}")
    print(f"• Local system time: {datetime.now().isoformat()}")
    print()

    print("🎯 New Features Added:")
    print("• UTC timezone handling throughout")
    print("• Real-time cron expression validation")
    print("• Next 5 runs preview when creating jobs")
    print("• 'Next Run' column in job listings")
    print("• Timezone documentation in help page")
    print("• Visual feedback for valid/invalid cron expressions")
    print()

    print("Starting web interface on http://localhost:8080")
    print("Try creating a new job to see the scheduling preview!")


if __name__ == "__main__":
    test_timezone_features()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8080,
        reload=False,
        log_level="info",
    )
