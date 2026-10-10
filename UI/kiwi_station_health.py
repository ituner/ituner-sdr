#!/usr/bin/env python3
"""Retired receiver health checker: deliberately performs no network I/O.

Browsing uses cached directory metadata. Only user-selected listening/decoder
sessions open receiver streams. Kept as a harmless entry point for old installs.
"""

def main():
    print("Receiver availability checks are disabled; no receivers contacted.")

if __name__ == "__main__":
    main()
