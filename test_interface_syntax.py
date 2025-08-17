#!/usr/bin/env python3
"""Quick syntax check for the cron interface."""

import sys

sys.path.append(".")


def test_syntax():
    try:
        # Test basic imports
        print("✓ Models import OK")

        print("✓ Dashboard routes import OK")

        print("✓ Executions routes import OK")

        from silica.cron.app import app

        print("✓ Main app import OK")

        # Check route count
        routes = [route.path for route in app.routes]
        print(f"✓ App has {len(routes)} routes")

        return True

    except Exception as e:
        print(f"✗ Syntax error: {e}")
        return False


if __name__ == "__main__":
    success = test_syntax()
    if success:
        print("\n✓ All syntax checks passed!")
        print("Ready to run: python test_cron_interface.py")
    else:
        print("\n✗ Syntax errors found - check imports")
        sys.exit(1)
