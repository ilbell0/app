#!/usr/bin/env python3
"""
Top Eleven Tactics API Backend Test Suite
Tests all backend API endpoints for functionality and data integrity
"""

import asyncio
import aiohttp
import json
import sys
from typing import Dict, List, Any
import traceback

# Backend URL from environment
BASE_URL = "https://app-refresh-64.preview.emergentagent.com/api"

class APITestSuite:
    def __init__(self):
        self.session = None
        self.test_results = []
        self.failed_tests = []
        
    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def log_test(self, test_name: str, success: bool, details: str = ""):
        """Log test result"""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if details:
            print(f"   {details}")
        
        self.test_results.append({
            "test": test_name,
            "success": success,
            "details": details
        })
        
        if not success:
            self.failed_tests.append(test_name)
    
    async def test_endpoint(self, method: str, endpoint: str, expected_status: int = 200, 
                          headers: Dict = None, data: Dict = None) -> tuple[bool, Any, str]:
        """Generic endpoint tester"""
        url = f"{BASE_URL}{endpoint}"
        
        try:
            if method.upper() == "GET":
                async with self.session.get(url, headers=headers) as response:
                    response_data = await response.text()
                    try:
                        json_data = json.loads(response_data)
                    except:
                        json_data = response_data
                    
                    success = response.status == expected_status
                    details = f"Status: {response.status}, Expected: {expected_status}"
                    if not success:
                        details += f", Response: {response_data[:200]}"
                    
                    return success, json_data, details
            
            elif method.upper() == "POST":
                async with self.session.post(url, json=data, headers=headers) as response:
                    response_data = await response.text()
                    try:
                        json_data = json.loads(response_data)
                    except:
                        json_data = response_data
                    
                    success = response.status == expected_status
                    details = f"Status: {response.status}, Expected: {expected_status}"
                    if not success:
                        details += f", Response: {response_data[:200]}"
                    
                    return success, json_data, details
                    
        except Exception as e:
            return False, None, f"Request failed: {str(e)}"
    
    async def test_health_endpoint(self):
        """Test GET /api/health"""
        print("\n🔍 Testing Health Check Endpoint")
        
        success, data, details = await self.test_endpoint("GET", "/health")
        
        if success and isinstance(data, dict) and data.get("status") == "healthy":
            self.log_test("Health Check", True, "Returns healthy status")
        else:
            expected_msg = f"Expected {{'status': 'healthy'}}, got: {data}"
            self.log_test("Health Check", False, f"{details} - {expected_msg}")
    
    async def test_formations_endpoints(self):
        """Test formations endpoints with new tactical features"""
        print("\n🔍 Testing Formations Endpoints (Updated with Tactical Features)")
        
        # Test GET /api/formations
        success, data, details = await self.test_endpoint("GET", "/formations")
        
        if success and isinstance(data, list) and len(data) == 14:
            # Check basic bilingual fields
            first_formation = data[0]
            basic_fields = ["id", "name", "description_en", "description_it", 
                           "strengths_en", "strengths_it", "weaknesses_en", "weaknesses_it"]
            
            has_basic = all(field in first_formation for field in basic_fields)
            
            # Check new tactical fields
            tactical_fields = ["tactic_type_en", "tactic_type_it", "opponent_settings"]
            has_tactical = all(field in first_formation for field in tactical_fields)
            
            if has_basic and has_tactical:
                self.log_test("Get All Formations (Count)", True, f"Returns {len(data)} formations with basic and tactical fields")
                
                # Test opponent_settings structure
                opponent_settings = first_formation.get("opponent_settings", {})
                levels = ["strong", "equal", "weak"]
                
                has_all_levels = all(level in opponent_settings for level in levels)
                
                if has_all_levels:
                    # Test strong level structure
                    strong_settings = opponent_settings.get("strong", {})
                    required_tactical_fields = [
                        "mentality", "mentality_it",
                        "focus_passing", "focus_passing_it", 
                        "passing_style", "passing_style_it",
                        "pressing", "pressing_it",
                        "tackling", "tackling_it",
                        "marking", "marking_it",
                        "counter_attack", "offside_trap",
                        "tip_en", "tip_it"
                    ]
                    
                    has_all_tactical = all(field in strong_settings for field in required_tactical_fields)
                    
                    if has_all_tactical:
                        self.log_test("Formation Tactical Structure", True, "All tactical fields present in opponent_settings")
                        
                        # Verify boolean fields
                        bool_fields = ["counter_attack", "offside_trap"]
                        bool_valid = all(isinstance(strong_settings.get(field), bool) for field in bool_fields)
                        
                        if bool_valid:
                            self.log_test("Formation Boolean Fields", True, "counter_attack and offside_trap are boolean")
                        else:
                            self.log_test("Formation Boolean Fields", False, "counter_attack or offside_trap not boolean")
                    else:
                        missing = [f for f in required_tactical_fields if f not in strong_settings]
                        self.log_test("Formation Tactical Structure", False, f"Missing tactical fields: {missing}")
                else:
                    missing_levels = [level for level in levels if level not in opponent_settings]
                    self.log_test("Formation Opponent Levels", False, f"Missing opponent levels: {missing_levels}")
            else:
                missing_basic = [f for f in basic_fields if f not in first_formation] if not has_basic else []
                missing_tactical = [f for f in tactical_fields if f not in first_formation] if not has_tactical else []
                all_missing = missing_basic + missing_tactical
                self.log_test("Formation Required Fields", False, f"Missing fields: {all_missing}")
        else:
            expected_msg = f"Expected array of 14 formations, got: {type(data)} with length {len(data) if isinstance(data, list) else 'N/A'}"
            self.log_test("Get All Formations (Count)", False, f"{details} - {expected_msg}")
        
        # Test GET /api/formations/442 with tactical data
        success, data, details = await self.test_endpoint("GET", "/formations/442")
        
        if success and isinstance(data, dict) and data.get("id") == "442":
            # Verify tactical fields in single formation
            has_tactic_type = "tactic_type_en" in data and "tactic_type_it" in data
            has_opponent_settings = "opponent_settings" in data
            
            if has_tactic_type and has_opponent_settings:
                # Check opponent_settings for all levels
                opponent_settings = data.get("opponent_settings", {})
                levels_present = all(level in opponent_settings for level in ["strong", "equal", "weak"])
                
                if levels_present:
                    self.log_test("Get Single Formation (442)", True, "Returns 4-4-2 with complete tactical data")
                else:
                    missing_levels = [level for level in ["strong", "equal", "weak"] if level not in opponent_settings]
                    self.log_test("Get Single Formation (442)", False, f"Missing opponent levels: {missing_levels}")
            else:
                missing_fields = []
                if not has_tactic_type:
                    missing_fields.extend(["tactic_type_en", "tactic_type_it"])
                if not has_opponent_settings:
                    missing_fields.append("opponent_settings")
                self.log_test("Get Single Formation (442)", False, f"Missing tactical fields: {missing_fields}")
        else:
            expected_msg = f"Expected formation object with id '442', got: {data}"
            self.log_test("Get Single Formation (442)", False, f"{details} - {expected_msg}")
    
    async def test_counters_endpoints(self):
        """Test counter tactics endpoints"""
        print("\n🔍 Testing Counter Tactics Endpoints")
        
        # Test GET /api/counters
        success, data, details = await self.test_endpoint("GET", "/counters")
        
        if success and isinstance(data, list) and len(data) > 0:
            # Check structure
            first_counter = data[0]
            required_fields = ["formation", "counters", "reason_en", "reason_it"]
            
            has_required = all(field in first_counter for field in required_fields)
            
            if has_required:
                self.log_test("Get All Counter Tactics", True, f"Returns {len(data)} counter tactics with bilingual reasons")
            else:
                missing = [f for f in required_fields if f not in first_counter]
                self.log_test("Get All Counter Tactics", False, f"Missing required fields: {missing}")
        else:
            expected_msg = f"Expected array of counter tactics, got: {type(data)} with length {len(data) if isinstance(data, list) else 'N/A'}"
            self.log_test("Get All Counter Tactics", False, f"{details} - {expected_msg}")
        
        # Test GET /api/counters/442
        success, data, details = await self.test_endpoint("GET", "/counters/442")
        
        if success and isinstance(data, dict) and data.get("formation") == "442":
            counters = data.get("counters", [])
            if isinstance(counters, list) and len(counters) > 0:
                self.log_test("Get Counter for Formation (442)", True, f"Returns counter tactics: {counters}")
            else:
                self.log_test("Get Counter for Formation (442)", False, "No counter formations returned")
        else:
            expected_msg = f"Expected counter object for formation '442', got: {data}"
            self.log_test("Get Counter for Formation (442)", False, f"{details} - {expected_msg}")
    
    async def test_scout_tips_endpoints(self):
        """Test scout tips endpoints"""
        print("\n🔍 Testing Scout Tips Endpoints")
        
        # Test GET /api/scout-tips
        success, data, details = await self.test_endpoint("GET", "/scout-tips")
        
        if success and isinstance(data, list) and len(data) > 0:
            # Check structure
            first_tip = data[0]
            required_fields = ["id", "category", "title_en", "title_it", "content_en", "content_it"]
            
            has_bilingual = all(field in first_tip for field in required_fields)
            
            if has_bilingual:
                categories = list(set(tip["category"] for tip in data))
                self.log_test("Get All Scout Tips", True, f"Returns {len(data)} tips with categories: {categories}")
            else:
                missing = [f for f in required_fields if f not in first_tip]
                self.log_test("Get All Scout Tips", False, f"Missing bilingual fields: {missing}")
        else:
            expected_msg = f"Expected array of scout tips, got: {type(data)} with length {len(data) if isinstance(data, list) else 'N/A'}"
            self.log_test("Get All Scout Tips", False, f"{details} - {expected_msg}")
        
        # Test GET /api/scout-tips/defense
        success, data, details = await self.test_endpoint("GET", "/scout-tips/defense")
        
        if success and isinstance(data, list) and len(data) > 0:
            # Verify all tips are defense category
            all_defense = all(tip.get("category") == "defense" for tip in data)
            if all_defense:
                self.log_test("Get Scout Tips by Category (defense)", True, f"Returns {len(data)} defense tips")
            else:
                categories_found = [tip.get("category") for tip in data]
                self.log_test("Get Scout Tips by Category (defense)", False, f"Found non-defense categories: {categories_found}")
        else:
            expected_msg = f"Expected array of defense tips, got: {type(data)} with length {len(data) if isinstance(data, list) else 'N/A'}"
            self.log_test("Get Scout Tips by Category (defense)", False, f"{details} - {expected_msg}")
    
    async def test_auth_endpoints_without_auth(self):
        """Test auth endpoints behavior without authentication"""
        print("\n🔍 Testing Auth Endpoints (No Authentication)")
        
        # Test GET /api/auth/me without auth (should fail)
        success, data, details = await self.test_endpoint("GET", "/auth/me", expected_status=401)
        
        if success:
            self.log_test("Auth Me (No Auth)", True, "Returns 401 Unauthorized as expected")
        else:
            self.log_test("Auth Me (No Auth)", False, f"Expected 401, {details}")
        
        # Test POST /api/auth/session without session_id (should fail)
        success, data, details = await self.test_endpoint("POST", "/auth/session", 
                                                        expected_status=422, 
                                                        data={})
        
        if success or details.find("422") != -1:
            self.log_test("Auth Session (No Data)", True, "Returns validation error as expected")
        else:
            self.log_test("Auth Session (No Data)", False, f"Expected validation error, {details}")
    
    async def test_authenticated_endpoints_without_auth(self):
        """Test endpoints that require authentication without providing auth"""
        print("\n🔍 Testing Protected Endpoints (No Authentication)")
        
        # Test AI Chat endpoint without auth
        success, data, details = await self.test_endpoint("POST", "/ai/chat", 
                                                        expected_status=401,
                                                        data={"message": "test", "language": "en"})
        
        if success:
            self.log_test("AI Chat (No Auth)", True, "Returns 401 Unauthorized as expected")
        else:
            self.log_test("AI Chat (No Auth)", False, f"Expected 401, {details}")
        
        # Test Favorites endpoint without auth
        success, data, details = await self.test_endpoint("GET", "/favorites", expected_status=401)
        
        if success:
            self.log_test("Favorites (No Auth)", True, "Returns 401 Unauthorized as expected")
        else:
            self.log_test("Favorites (No Auth)", False, f"Expected 401, {details}")
    
    async def run_all_tests(self):
        """Run comprehensive test suite"""
        print("🚀 Starting Top Eleven Tactics API Backend Tests")
        print(f"📍 Testing against: {BASE_URL}")
        
        try:
            # Public endpoint tests (main focus)
            await self.test_health_endpoint()
            await self.test_formations_endpoints()
            await self.test_counters_endpoints()
            await self.test_scout_tips_endpoints()
            
            # Auth behavior tests
            await self.test_auth_endpoints_without_auth()
            await self.test_authenticated_endpoints_without_auth()
            
        except Exception as e:
            print(f"\n❌ Test suite failed with error: {str(e)}")
            traceback.print_exc()
        
        # Summary
        print(f"\n📊 Test Results Summary")
        print("=" * 50)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result["success"])
        failed_tests = total_tests - passed_tests
        
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        
        if self.failed_tests:
            print(f"\n🔍 Failed Tests:")
            for test_name in self.failed_tests:
                print(f"   • {test_name}")
        
        success_rate = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
        print(f"\n📈 Success Rate: {success_rate:.1f}%")
        
        return passed_tests, failed_tests, self.test_results

async def main():
    """Main test execution"""
    async with APITestSuite() as test_suite:
        passed, failed, results = await test_suite.run_all_tests()
        
        # Exit with error code if tests failed
        sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    asyncio.run(main())