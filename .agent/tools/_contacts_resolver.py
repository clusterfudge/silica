"""Shared contacts resolver for macOS AddressBook.

This module queries the macOS AddressBook SQLite databases to resolve
phone numbers and email addresses to contact names. It's designed to be
imported by other user tools (prefixed with _ so it's not discovered as
a standalone tool).

Usage:
    from _contacts_resolver import ContactsResolver
    resolver = ContactsResolver()
    name = resolver.resolve_handle("+15551234567")  # "John Doe"
    results = resolver.search("John")  # list of Contact dicts
"""

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


ADDRESSBOOK_DIR = Path.home() / "Library" / "Application Support" / "AddressBook"


@dataclass
class Contact:
    """A contact from the macOS AddressBook."""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    organization: Optional[str] = None
    phone_numbers: list[dict] = field(default_factory=list)
    email_addresses: list[dict] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        """Best display name for this contact."""
        parts = []
        if self.first_name:
            parts.append(self.first_name)
        if self.last_name:
            parts.append(self.last_name)
        if parts:
            return " ".join(parts)
        if self.organization:
            return self.organization
        return "Unknown"

    def to_dict(self) -> dict:
        d = {
            "display_name": self.display_name,
        }
        if self.first_name:
            d["first_name"] = self.first_name
        if self.last_name:
            d["last_name"] = self.last_name
        if self.organization:
            d["organization"] = self.organization
        if self.phone_numbers:
            d["phone_numbers"] = self.phone_numbers
        if self.email_addresses:
            d["email_addresses"] = self.email_addresses
        return d


def _normalize_phone(phone: str) -> str:
    """Strip a phone number to just digits (with leading +)."""
    if not phone:
        return ""
    digits = re.sub(r"[^\d+]", "", phone)
    # Ensure US numbers have +1 prefix
    if digits and not digits.startswith("+"):
        if len(digits) == 10:
            digits = "+1" + digits
        elif len(digits) == 11 and digits.startswith("1"):
            digits = "+" + digits
    return digits


def _get_addressbook_dbs() -> list[Path]:
    """Find all AddressBook SQLite databases (source DBs have the contacts)."""
    dbs = []
    sources_dir = ADDRESSBOOK_DIR / "Sources"
    if sources_dir.exists():
        for source in sources_dir.iterdir():
            db_path = source / "AddressBook-v22.abcddb"
            if db_path.exists():
                dbs.append(db_path)
    # Also check the main DB (usually has fewer contacts but worth checking)
    main_db = ADDRESSBOOK_DIR / "AddressBook-v22.abcddb"
    if main_db.exists():
        dbs.append(main_db)
    return dbs


def _label_clean(label: Optional[str]) -> str:
    """Clean up AddressBook label strings like '_$!<Mobile>!$_'."""
    if not label:
        return "other"
    # Strip the _$!< >!$_ wrapper
    cleaned = re.sub(r"_\$!<(.+?)>!\$_", r"\1", label)
    return cleaned.lower()


class ContactsResolver:
    """Resolves phone numbers and emails to contact names.

    Lazily loads the full phone/email -> name mapping on first use,
    then serves lookups from an in-memory cache.
    """

    def __init__(self):
        self._phone_map: Optional[dict[str, str]] = None
        self._email_map: Optional[dict[str, str]] = None
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._phone_map = {}
        self._email_map = {}

        for db_path in _get_addressbook_dbs():
            try:
                conn = sqlite3.connect(f"file:///{db_path}?mode=ro", uri=True)
                cursor = conn.cursor()

                # Load phone -> name mapping
                cursor.execute("""
                    SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZORGANIZATION, p.ZFULLNUMBER
                    FROM ZABCDRECORD r
                    JOIN ZABCDPHONENUMBER p ON p.ZOWNER = r.Z_PK
                    WHERE r.Z_ENT = 22 AND p.ZFULLNUMBER IS NOT NULL
                """)
                for first, last, org, phone in cursor.fetchall():
                    name = " ".join(p for p in [first, last] if p) or org or "Unknown"
                    normalized = _normalize_phone(phone)
                    if normalized:
                        self._phone_map[normalized] = name

                # Load email -> name mapping
                cursor.execute("""
                    SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZORGANIZATION, e.ZADDRESS
                    FROM ZABCDRECORD r
                    JOIN ZABCDEMAILADDRESS e ON e.ZOWNER = r.Z_PK
                    WHERE r.Z_ENT = 22 AND e.ZADDRESS IS NOT NULL
                """)
                for first, last, org, email in cursor.fetchall():
                    name = " ".join(p for p in [first, last] if p) or org or "Unknown"
                    self._email_map[email.lower()] = name

                conn.close()
            except Exception:
                continue

        self._loaded = True

    def resolve_handle(self, handle: str) -> Optional[str]:
        """Resolve an iMessage handle (phone/email) to a contact display name.

        Args:
            handle: Phone number (any format) or email address

        Returns:
            Contact display name, or None if not found
        """
        if not handle:
            return None

        self._ensure_loaded()

        # Try email first
        if "@" in handle:
            return self._email_map.get(handle.lower())

        # Try phone number
        normalized = _normalize_phone(handle)
        if normalized in self._phone_map:
            return self._phone_map[normalized]

        # Try matching by last 10 digits (handles country code mismatches)
        digits_only = re.sub(r"\D", "", normalized)
        if len(digits_only) >= 10:
            last10 = digits_only[-10:]
            for stored_phone, name in self._phone_map.items():
                stored_digits = re.sub(r"\D", "", stored_phone)
                if len(stored_digits) >= 10 and stored_digits[-10:] == last10:
                    return name

        return None

    def resolve_handles_batch(self, handles: list[str]) -> dict[str, Optional[str]]:
        """Resolve multiple handles at once.

        Args:
            handles: List of phone numbers or email addresses

        Returns:
            Dict mapping handle -> display name (None if not found)
        """
        self._ensure_loaded()
        return {h: self.resolve_handle(h) for h in handles}

    def search(self, query: str, limit: int = 20) -> list[Contact]:
        """Search contacts by name, phone, email, or organization.

        Args:
            query: Search string (case-insensitive)
            limit: Maximum results to return

        Returns:
            List of matching Contact objects
        """
        query_lower = query.lower()
        query_digits = re.sub(r"\D", "", query)
        results = []
        seen_names = set()

        for db_path in _get_addressbook_dbs():
            try:
                conn = sqlite3.connect(f"file:///{db_path}?mode=ro", uri=True)
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT Z_PK, ZFIRSTNAME, ZLASTNAME, ZORGANIZATION
                    FROM ZABCDRECORD
                    WHERE Z_ENT = 22
                """)

                for pk, first, last, org in cursor.fetchall():
                    searchable = " ".join(
                        s for s in [first, last, org] if s
                    ).lower()

                    name_match = query_lower in searchable
                    phone_match = False
                    email_match = False

                    contact = Contact(
                        first_name=first,
                        last_name=last,
                        organization=org,
                    )

                    cursor.execute(
                        "SELECT ZFULLNUMBER, ZLABEL FROM ZABCDPHONENUMBER WHERE ZOWNER = ?",
                        (pk,),
                    )
                    for phone, label in cursor.fetchall():
                        if phone:
                            contact.phone_numbers.append({
                                "number": phone,
                                "label": _label_clean(label),
                            })
                            if query_digits and len(query_digits) >= 3:
                                phone_digits = re.sub(r"\D", "", phone)
                                if query_digits in phone_digits:
                                    phone_match = True

                    cursor.execute(
                        "SELECT ZADDRESS, ZLABEL FROM ZABCDEMAILADDRESS WHERE ZOWNER = ?",
                        (pk,),
                    )
                    for email, label in cursor.fetchall():
                        if email:
                            contact.email_addresses.append({
                                "address": email,
                                "label": _label_clean(label),
                            })
                            if query_lower in email.lower():
                                email_match = True

                    if name_match or phone_match or email_match:
                        dedup_key = contact.display_name.lower()
                        if dedup_key not in seen_names:
                            seen_names.add(dedup_key)
                            results.append(contact)
                            if len(results) >= limit:
                                conn.close()
                                return results

                conn.close()
            except Exception:
                continue

        return results

    def list_all(self, limit: int = 0) -> list[Contact]:
        """List all contacts.

        Args:
            limit: Maximum results (0 = no limit)

        Returns:
            List of Contact objects sorted by display name
        """
        results = []
        seen_names = set()

        for db_path in _get_addressbook_dbs():
            try:
                conn = sqlite3.connect(f"file:///{db_path}?mode=ro", uri=True)
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT Z_PK, ZFIRSTNAME, ZLASTNAME, ZORGANIZATION
                    FROM ZABCDRECORD
                    WHERE Z_ENT = 22
                    ORDER BY ZSORTINGFIRSTNAME, ZSORTINGLASTNAME
                """)

                for pk, first, last, org in cursor.fetchall():
                    contact = Contact(
                        first_name=first,
                        last_name=last,
                        organization=org,
                    )

                    dedup_key = contact.display_name.lower()
                    if dedup_key in seen_names:
                        continue
                    seen_names.add(dedup_key)

                    cursor.execute(
                        "SELECT ZFULLNUMBER, ZLABEL FROM ZABCDPHONENUMBER WHERE ZOWNER = ?",
                        (pk,),
                    )
                    for phone, label in cursor.fetchall():
                        if phone:
                            contact.phone_numbers.append({
                                "number": phone,
                                "label": _label_clean(label),
                            })

                    cursor.execute(
                        "SELECT ZADDRESS, ZLABEL FROM ZABCDEMAILADDRESS WHERE ZOWNER = ?",
                        (pk,),
                    )
                    for email, label in cursor.fetchall():
                        if email:
                            contact.email_addresses.append({
                                "address": email,
                                "label": _label_clean(label),
                            })

                    results.append(contact)
                    if limit and len(results) >= limit:
                        conn.close()
                        return results

                conn.close()
            except Exception:
                continue

        results.sort(key=lambda c: c.display_name.lower())
        return results
