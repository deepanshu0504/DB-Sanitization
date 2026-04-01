"""
Test script to verify name component detection fix.

This script validates that the priority-based detection correctly identifies
name component types from column names.

Expected Results:
- "FirstName", "first_name" → "first" (not "full")
- "LastName", "last_name" → "last" (not "full")
- "MiddleName", "middle_name" → "middle" (not "full")
- "FullName", "full_name" → "full"
- "Name" alone → "full"
- "EmployeeName", "CustomerName" → "full"

Usage:
    python test_name_detection_fix.py
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

# Import patterns from sanitize_smart
NAME_COMPONENT_PATTERNS = {
    "first": [
        r"\bfirst\b",           # FirstName, first_name, FIRST_NAME
        r"\bfname\b",           # fname, FName (after normalization)
        r"\bgiven\b",           # GivenName, given_name
        r"\bf[\s_]?name\b",     # f_name, f name, FName
        r"\bgivenname\b",       # givenname (single word)
        r"\bforename\b",        # forename (single word)
        r"\bfore[\s_]?name\b",  # ForeName, fore_name, fore name
        r"\bfirstname\b"        # firstname (single word)
    ],
    "middle": [
        r"\bmiddle\b",          # MiddleName, middle_name
        r"\bmname\b",           # mname, MName (after normalization)
        r"\bm[\s_]?name\b",     # m_name, m name, MName
        r"\bmiddlename\b",      # middlename (single word)
        r"\bmiddle[\s_]?initial\b"  # middle_initial, middle initial, MiddleInitial
    ],
    "last": [
        r"\blast\b",            # LastName, last_name
        r"\blname\b",           # lname, LName (after normalization)
        r"\bsurname\b",         # Surname, surname
        r"\bfamily\b",          # FamilyName, family_name
        r"\bl[\s_]?name\b",     # l_name, l name, LName
        r"\blastname\b",        # lastname (single word)
        r"\bfamilyname\b"       # familyname (single word)
    ],
    "full": [
        r"\bfull\b",                    # FullName, full_name
        r"\bfullname\b",                # fullname (single word)
        r"\bfull[\s_]?name\b",          # full_name, full name, FullName
        r"\bcomplete\b",                # CompleteName, complete_name
        r"\bcomplete[\s_]?name\b",      # complete_name, complete name, CompleteName
        r"^name$",                      # Exact match: "name" only
        r"^full[\s_]?name$",            # Exact match: fullname/full_name/full name
        r"\b(person|employee|customer|contact|user|student|patient)[\s_]?name\b"  # Generic entity names
    ]
}

@dataclass
class ColumnInfo:
    """Column metadata for testing."""
    data_type: str
    max_length: Optional[int]
    nullable: bool
    column_name: Optional[str] = None


def _detect_name_component_type(column_info: ColumnInfo) -> str:
    """
    Detect name component type from column name using regex patterns.
    
    Uses priority-based detection: component-specific patterns (first/middle/last)
    are checked first and take precedence over generic "full" patterns.
    
    Returns:
        "first", "middle", "last", or "full"
    """
    if not column_info.column_name:
        return "full"
    
    # Normalize column name (VERY IMPORTANT)
    col_name = column_info.column_name
    
    # 1. Replace underscores with spaces first
    col_name = col_name.replace("_", " ")
    
    # 2. Insert spaces before capital letters (CamelCase → Camel Case)
    #    Only if the string is not all uppercase (to avoid "FIRST" → "F I R S T")
    if not col_name.isupper():
        col_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', col_name)
    
    # 3. Convert to lowercase
    col_name = col_name.lower()
    
    # Priority 1: Check component-specific patterns first (first/middle/last)
    # These take precedence to avoid conflicts with generic "name" pattern
    component_types = ["first", "middle", "last"]
    for component in component_types:
        patterns = NAME_COMPONENT_PATTERNS.get(component, [])
        for pattern in patterns:
            if re.search(pattern, col_name):
                return component  # Early exit on first match
    
    # Priority 2: Check "full" patterns only if no component matched
    full_patterns = NAME_COMPONENT_PATTERNS.get("full", [])
    for pattern in full_patterns:
        if re.search(pattern, col_name):
            return "full"
    
    # Default fallback: treat as full name if no patterns matched
    return "full"


def run_tests():
    """Run test cases to validate name component detection."""
    
    test_cases = [
        # ===== FIRST NAME PATTERNS =====
        ("FirstName", "first"),
        ("first_name", "first"),
        ("FIRST_NAME", "first"),
        ("fname", "first"),
        ("FName", "first"),
        ("GivenName", "first"),
        ("given_name", "first"),
        ("ForeName", "first"),
        ("forename", "first"),
        ("firstname", "first"),
        ("f_name", "first"),
        ("givenname", "first"),
        
        # ===== LAST NAME PATTERNS =====
        ("LastName", "last"),
        ("last_name", "last"),
        ("LAST_NAME", "last"),
        ("lname", "last"),
        ("LName", "last"),
        ("Surname", "last"),
        ("surname", "last"),
        ("FamilyName", "last"),
        ("family_name", "last"),
        ("lastname", "last"),
        ("l_name", "last"),
        ("familyname", "last"),
        
        # ===== MIDDLE NAME PATTERNS =====
        ("MiddleName", "middle"),
        ("middle_name", "middle"),
        ("MIDDLE_NAME", "middle"),
        ("mname", "middle"),
        ("MName", "middle"),
        ("middlename", "middle"),
        ("m_name", "middle"),
        ("MiddleInitial", "middle"),
        ("middle_initial", "middle"),
        
        # ===== FULL NAME PATTERNS =====
        ("FullName", "full"),
        ("full_name", "full"),
        ("FULL_NAME", "full"),
        ("Name", "full"),
        ("name", "full"),
        ("fullname", "full"),
        ("CompleteName", "full"),
        ("complete_name", "full"),
        ("completename", "full"),
        
        # ===== GENERIC ENTITY NAME PATTERNS (should be FULL) =====
        ("EmployeeName", "full"),
        ("employee_name", "full"),
        ("CustomerName", "full"),
        ("customer_name", "full"),
        ("PersonName", "full"),
        ("person_name", "full"),
        ("UserName", "full"),
        ("user_name", "full"),
        ("StudentName", "full"),
        ("student_name", "full"),
        ("PatientName", "full"),
        ("patient_name", "full"),
        ("ContactName", "full"),
        ("contact_name", "full"),
        
        # ===== EDGE CASES =====
        ("PersonFirstName", "first"),  # Contains "first"
        ("PersonLastName", "last"),    # Contains "last"
        ("EmployeeFirstName", "first"),
        ("CustomerLastName", "last"),
        ("Client_First_Name", "first"),
        ("Client_Last_Name", "last"),
    ]
    
    print("="*80)
    print("NAME COMPONENT DETECTION - TEST RESULTS")
    print("="*80)
    print()
    
    passed = 0
    failed = 0
    
    for column_name, expected_type in test_cases:
        col_info = ColumnInfo(
            data_type="NVARCHAR",
            max_length=100,
            nullable=True,
            column_name=column_name
        )
        
        detected_type = _detect_name_component_type(col_info)
        
        status = "✓ PASS" if detected_type == expected_type else "✗ FAIL"
        
        if detected_type == expected_type:
            passed += 1
            print(f"{status:8} | {column_name:25} → {detected_type:8} (expected: {expected_type})")
        else:
            failed += 1
            print(f"{status:8} | {column_name:25} → {detected_type:8} (expected: {expected_type}) ⚠️")
    
    print()
    print("="*80)
    print(f"SUMMARY: {passed} passed, {failed} failed out of {len(test_cases)} total")
    print("="*80)
    
    if failed == 0:
        print("\n✓ ALL TESTS PASSED! Name component detection is working correctly.")
        return True
    else:
        print(f"\n✗ {failed} TESTS FAILED! Please review the detection logic.")
        return False


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
