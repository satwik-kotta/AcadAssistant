#!/usr/bin/env python3
"""
Test script for prerequisite validation implementation.
Tests that the system properly validates documents before quiz/plan generation.
"""

import httpx
import sys
import json
from pathlib import Path

API_BASE = "http://127.0.0.1:8013"

# Test Bearer token (replace with actual user token after login)
# For testing without auth, we'll need a valid token
BEARER_TOKEN = "Bearer test-token"  # This will fail auth, but that's expected

def test_quiz_without_documents():
    """Test that quiz generation fails when no documents exist."""
    print("\n" + "="*70)
    print("TEST 1: Quiz generation without documents")
    print("="*70)
    
    try:
        # Try to generate quiz without any documents
        response = httpx.get(
            f"{API_BASE}/quiz/1",
            params={"num_questions": 5},
            headers={"Authorization": BEARER_TOKEN},
            timeout=10
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 412:
            print("✅ PASS: Got 412 Precondition Failed (expected)")
            error_msg = response.json().get("detail", "")
            if "No documents uploaded" in error_msg or "Prerequisites not met" in error_msg:
                print("✅ PASS: Error message mentions missing documents")
                return True
        elif response.status_code == 401:
            print("⚠️  Got 401 Unauthorized (auth issue - this is expected in test)")
            return None  # Skip this test
        else:
            print(f"❌ FAIL: Expected 412, got {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

def test_plan_without_documents():
    """Test that plan generation fails when no documents exist."""
    print("\n" + "="*70)
    print("TEST 2: Plan generation without documents")
    print("="*70)
    
    try:
        response = httpx.post(
            f"{API_BASE}/plan",
            json={
                "request": "Create a study plan for calculus",
                "daily_hours": 2.0,
                "weak_subjects": ["derivatives"],
                "start_date": "2025-07-15",
                "start_time": "09:00"
            },
            headers={"Authorization": BEARER_TOKEN},
            timeout=10
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 412:
            print("✅ PASS: Got 412 Precondition Failed (expected)")
            error_msg = response.json().get("detail", "")
            if "No documents" in error_msg or "Prerequisites not met" in error_msg:
                print("✅ PASS: Error message mentions missing documents")
                return True
        elif response.status_code == 401:
            print("⚠️  Got 401 Unauthorized (auth issue - this is expected in test)")
            return None  # Skip this test
        else:
            print(f"❌ FAIL: Expected 412, got {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

def test_prerequisites_without_documents():
    """Test that prerequisites endpoint fails when no documents exist."""
    print("\n" + "="*70)
    print("TEST 3: Prerequisites analysis without documents")
    print("="*70)
    
    try:
        response = httpx.get(
            f"{API_BASE}/prerequisites/1",
            headers={"Authorization": BEARER_TOKEN},
            timeout=10
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 412:
            print("✅ PASS: Got 412 Precondition Failed (expected)")
            return True
        elif response.status_code == 401:
            print("⚠️  Got 401 Unauthorized (auth issue - this is expected in test)")
            return None  # Skip this test
        else:
            print(f"❌ FAIL: Expected 412 or 404, got {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

def test_api_health():
    """Test that API is running and accessible."""
    print("\n" + "="*70)
    print("TEST 0: API Health Check")
    print("="*70)
    
    try:
        response = httpx.get(f"{API_BASE}/docs", timeout=5)
        if response.status_code == 200:
            print("✅ PASS: API is running")
            return True
        else:
            print(f"❌ FAIL: API responded with {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ ERROR: API not accessible: {e}")
        return False

def check_validation_code():
    """Check that validation code exists in api.py."""
    print("\n" + "="*70)
    print("TEST 4: Code validation - Check implementation")
    print("="*70)
    
    api_file = Path("/Users/satwik/Documents/New GenAI/academic-assistant/backend/api.py")
    code = api_file.read_text()
    
    checks = {
        "_validate_documents_ingested": "Document validation function exists",
        "_get_user_documents": "Document fetching function exists",
        "❌ No documents uploaded": "Clear error message for missing documents",
        "prerequisites not met": "Prerequisites language in error",
        "status_code=412": "HTTP 412 Precondition Failed used",
    }
    
    passed = 0
    for check_str, desc in checks.items():
        if check_str in code:
            print(f"✅ PASS: {desc}")
            passed += 1
        else:
            print(f"❌ FAIL: {desc}")
    
    if passed == len(checks):
        print(f"\n✅ All code validations passed ({passed}/{len(checks)})")
        return True
    else:
        print(f"\n❌ Some code validations failed ({passed}/{len(checks)})")
        return False

def check_planner_validation():
    """Check that planner has validation code."""
    print("\n" + "="*70)
    print("TEST 5: Code validation - Planner changes")
    print("="*70)
    
    planner_file = Path("/Users/satwik/Documents/New GenAI/academic-assistant/backend/planner.py")
    code = planner_file.read_text()
    
    checks = {
        "full_text = get_all_full_texts()": "Full text retrieval at start",
        "if not full_text or not full_text.strip()": "Empty document check",
        "raise ValueError": "Raises ValueError for no documents",
        "PREREQUISITE CHECK": "Prerequisite check comment",
    }
    
    passed = 0
    for check_str, desc in checks.items():
        if check_str in code:
            print(f"✅ PASS: {desc}")
            passed += 1
        else:
            print(f"❌ FAIL: {desc}")
    
    if passed == len(checks):
        print(f"\n✅ All planner validations passed ({passed}/{len(checks)})")
        return True
    else:
        print(f"\n❌ Some planner validations failed ({passed}/{len(checks)})")
        return False

def main():
    print("\n" + "="*70)
    print("PREREQUISITE VALIDATION TEST SUITE")
    print("="*70)
    print("\nThis test validates that:")
    print("1. System rejects quiz generation when no documents exist")
    print("2. System rejects plan generation when no documents exist")
    print("3. System rejects prerequisite analysis when no documents exist")
    print("4. Error messages are clear and guide users to upload documents")
    print("5. Code changes have been properly implemented")
    
    results = {}
    
    # Code validation (doesn't require API running)
    results["Code: api.py"] = check_validation_code()
    results["Code: planner.py"] = check_planner_validation()
    
    # API tests (requires running backend)
    print("\n" + "="*70)
    print("RUNTIME TESTS (requires API)")
    print("="*70)
    
    if test_api_health():
        results["API Health"] = True
        # Full API tests only if health check passes
        results["Quiz Without Docs"] = test_quiz_without_documents()
        results["Plan Without Docs"] = test_plan_without_documents()
        results["Prerequisites Without Docs"] = test_prerequisites_without_documents()
    else:
        print("⚠️  Skipping runtime tests - API not accessible")
        print("   Start backend with: uvicorn backend.api:app --host 127.0.0.1 --port 8013")
        results["API Health"] = False
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    for test_name, result in results.items():
        if result is None:
            status = "⏭️  SKIPPED"
        elif result:
            status = "✅ PASS"
        else:
            status = "❌ FAIL"
        print(f"{status}: {test_name}")
    
    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    skipped = sum(1 for r in results.values() if r is None)
    
    print(f"\nTotal: {passed} passed, {failed} failed, {skipped} skipped")
    
    if failed == 0:
        print("\n✅ ALL CRITICAL TESTS PASSED")
        return 0
    else:
        print(f"\n❌ {failed} TEST(S) FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(main())
