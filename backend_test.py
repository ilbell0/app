#!/usr/bin/env python3
"""
Backend API Testing for Top Eleven Tips App
Testing META 2025/2026 formations and counter-tactics updates
"""

import asyncio
import httpx
import sys
from typing import Dict, List, Any

# Backend URL from environment configuration
BASE_URL = "https://app-refresh-64.preview.emergentagent.com/api"

class BackendTester:
    def __init__(self):
        self.base_url = BASE_URL
        self.results = {
            "health_check": False,
            "formations_count": 0,
            "formations_total_expected": 20,
            "counters_count": 0,
            "counters_total_expected": 17,
            "scout_tips_working": False,
            "meta_formations_found": [],
            "meta_counters_found": [],
            "expected_meta_formations": [
                {"id": "31411", "name": "3-1-4-1-1", "should_contain_meta": True},
                {"id": "4123", "name": "4-1-2-3", "should_contain_meta": False},
                {"id": "41221", "name": "4-1-2-2-1", "should_contain_meta": False},
                {"id": "3241", "name": "3-2-4-1", "should_contain_meta": True},
                {"id": "5212", "name": "5-2-1-2", "should_contain_meta": False},
                {"id": "4321", "name": "4-3-2-1 Christmas Tree", "should_contain_meta": False}
            ],
            "expected_meta_counters": [
                {"formation": "31411", "should_have_meta_flag": True},
                {"formation": "4123", "should_have_meta_flag": True},
                {"formation": "41221", "should_have_meta_flag": True},
                {"formation": "3241", "should_have_meta_flag": True},
                {"formation": "5212", "should_have_meta_flag": True},
                {"formation": "4321", "should_have_meta_flag": True},
                {"formation": "31231", "should_have_meta_flag": True}
            ],
            "errors": []
        }

    async def test_health_endpoint(self):
        """Test the health check endpoint"""
        print("🔍 Testing GET /api/health...")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/health")
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "healthy":
                        self.results["health_check"] = True
                        print("✅ Health check endpoint working correctly")
                    else:
                        self.results["errors"].append("Health endpoint returned unexpected data")
                        print("❌ Health check endpoint returned unexpected data")
                else:
                    self.results["errors"].append(f"Health endpoint returned {response.status_code}")
                    print(f"❌ Health endpoint returned {response.status_code}")
                    
        except Exception as e:
            self.results["errors"].append(f"Health check failed: {str(e)}")
            print(f"❌ Health check failed: {str(e)}")

    async def test_formations_endpoint(self):
        """Test formations endpoint and verify META 2025/2026 formations"""
        print("\n🔍 Testing GET /api/formations...")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/formations")
                
                if response.status_code == 200:
                    formations = response.json()
                    self.results["formations_count"] = len(formations)
                    
                    print(f"📊 Found {len(formations)} formations (expected: {self.results['formations_total_expected']})")
                    
                    if len(formations) == self.results["formations_total_expected"]:
                        print("✅ Formations count matches expected (20 formations)")
                    else:
                        self.results["errors"].append(f"Expected {self.results['formations_total_expected']} formations, got {len(formations)}")
                        print(f"❌ Expected {self.results['formations_total_expected']} formations, got {len(formations)}")
                    
                    # Check for specific META 2025/2026 formations
                    formation_ids = [f["id"] for f in formations]
                    formation_dict = {f["id"]: f for f in formations}
                    
                    print("\n🔍 Verifying META 2025/2026 formations...")
                    for expected_formation in self.results["expected_meta_formations"]:
                        formation_id = expected_formation["id"]
                        expected_name = expected_formation["name"]
                        should_contain_meta = expected_formation["should_contain_meta"]
                        
                        if formation_id in formation_ids:
                            formation = formation_dict[formation_id]
                            self.results["meta_formations_found"].append(formation_id)
                            
                            # Check name matches
                            if formation["name"] == expected_name:
                                print(f"✅ Found {formation_id}: {formation['name']}")
                                
                                # Check if it should contain META 2026 in tactic_type
                                if should_contain_meta:
                                    tactic_type_en = formation.get("tactic_type_en", "")
                                    if "META 2026" in tactic_type_en:
                                        print(f"   ✅ Contains 'META 2026' in tactic_type: {tactic_type_en}")
                                    else:
                                        self.results["errors"].append(f"Formation {formation_id} should contain 'META 2026' in tactic_type")
                                        print(f"   ❌ Missing 'META 2026' in tactic_type: {tactic_type_en}")
                                        
                            else:
                                self.results["errors"].append(f"Formation {formation_id} has wrong name: {formation['name']}, expected: {expected_name}")
                                print(f"   ❌ Wrong name: {formation['name']}, expected: {expected_name}")
                        else:
                            self.results["errors"].append(f"Missing META formation: {formation_id} ({expected_name})")
                            print(f"❌ Missing META formation: {formation_id} ({expected_name})")
                    
                    # Also verify that formations have proper structure
                    print("\n🔍 Verifying formation data structure...")
                    for formation in formations[:3]:  # Check first 3 formations for structure
                        required_fields = ["id", "name", "description_en", "description_it", "positions", 
                                         "strengths_en", "strengths_it", "weaknesses_en", "weaknesses_it",
                                         "tactic_type_en", "tactic_type_it", "opponent_settings"]
                        
                        missing_fields = [field for field in required_fields if field not in formation]
                        if missing_fields:
                            self.results["errors"].append(f"Formation {formation['id']} missing fields: {missing_fields}")
                            print(f"❌ Formation {formation['id']} missing fields: {missing_fields}")
                        else:
                            print(f"✅ Formation {formation['id']} has all required fields")
                            
                else:
                    self.results["errors"].append(f"Formations endpoint returned {response.status_code}")
                    print(f"❌ Formations endpoint returned {response.status_code}")
                    
        except Exception as e:
            self.results["errors"].append(f"Formations test failed: {str(e)}")
            print(f"❌ Formations test failed: {str(e)}")

    async def test_counters_endpoint(self):
        """Test counter tactics endpoint and verify META 2025/2026 counters"""
        print("\n🔍 Testing GET /api/counters...")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/counters")
                
                if response.status_code == 200:
                    counters = response.json()
                    self.results["counters_count"] = len(counters)
                    
                    print(f"📊 Found {len(counters)} counter tactics (expected: {self.results['counters_total_expected']})")
                    
                    if len(counters) == self.results["counters_total_expected"]:
                        print("✅ Counter tactics count matches expected (17 counters)")
                    else:
                        self.results["errors"].append(f"Expected {self.results['counters_total_expected']} counters, got {len(counters)}")
                        print(f"❌ Expected {self.results['counters_total_expected']} counters, got {len(counters)}")
                    
                    # Check for specific META 2025/2026 counter tactics
                    counter_dict = {c["formation"]: c for c in counters}
                    
                    print("\n🔍 Verifying META 2025/2026 counter tactics...")
                    for expected_counter in self.results["expected_meta_counters"]:
                        formation_id = expected_counter["formation"]
                        should_have_meta_flag = expected_counter["should_have_meta_flag"]
                        
                        if formation_id in counter_dict:
                            counter = counter_dict[formation_id]
                            self.results["meta_counters_found"].append(formation_id)
                            
                            if should_have_meta_flag:
                                if counter.get("meta_2026") == True:
                                    print(f"✅ Found META 2026 counter for {formation_id} with meta_2026: true")
                                else:
                                    self.results["errors"].append(f"Counter for {formation_id} should have meta_2026: true")
                                    print(f"❌ Counter for {formation_id} missing meta_2026: true flag")
                            else:
                                print(f"✅ Found counter for {formation_id}")
                                
                            # Verify counter has required structure
                            required_fields = ["formation", "counters", "reason_en", "reason_it", "tactics_en", "tactics_it"]
                            missing_fields = [field for field in required_fields if field not in counter]
                            if missing_fields:
                                self.results["errors"].append(f"Counter {formation_id} missing fields: {missing_fields}")
                                print(f"   ❌ Missing fields: {missing_fields}")
                            else:
                                print(f"   ✅ Has all required fields")
                                
                        else:
                            self.results["errors"].append(f"Missing META counter for formation: {formation_id}")
                            print(f"❌ Missing META counter for formation: {formation_id}")
                    
                else:
                    self.results["errors"].append(f"Counters endpoint returned {response.status_code}")
                    print(f"❌ Counters endpoint returned {response.status_code}")
                    
        except Exception as e:
            self.results["errors"].append(f"Counters test failed: {str(e)}")
            print(f"❌ Counters test failed: {str(e)}")

    async def test_scout_tips_endpoint(self):
        """Test scout tips endpoint"""
        print("\n🔍 Testing GET /api/scout-tips...")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/scout-tips")
                
                if response.status_code == 200:
                    scout_tips = response.json()
                    self.results["scout_tips_working"] = True
                    print(f"✅ Scout tips endpoint working - found {len(scout_tips)} tips")
                    
                    # Verify structure of first tip
                    if scout_tips:
                        tip = scout_tips[0]
                        required_fields = ["id", "category", "title_en", "title_it", "content_en", "content_it"]
                        missing_fields = [field for field in required_fields if field not in tip]
                        if missing_fields:
                            self.results["errors"].append(f"Scout tip missing fields: {missing_fields}")
                            print(f"❌ Scout tip missing fields: {missing_fields}")
                        else:
                            print("✅ Scout tips have proper structure")
                            
                else:
                    self.results["errors"].append(f"Scout tips endpoint returned {response.status_code}")
                    print(f"❌ Scout tips endpoint returned {response.status_code}")
                    
        except Exception as e:
            self.results["errors"].append(f"Scout tips test failed: {str(e)}")
            print(f"❌ Scout tips test failed: {str(e)}")

    async def run_all_tests(self):
        """Run all backend tests"""
        print("🚀 Starting Backend API Tests for META 2025/2026 Updates...")
        print(f"🌐 Testing against: {self.base_url}")
        print("=" * 70)
        
        await self.test_health_endpoint()
        await self.test_formations_endpoint()
        await self.test_counters_endpoint()
        await self.test_scout_tips_endpoint()
        
        # Print summary
        print("\n" + "=" * 70)
        print("📋 TEST SUMMARY")
        print("=" * 70)
        
        print(f"🏥 Health Check: {'✅ PASS' if self.results['health_check'] else '❌ FAIL'}")
        print(f"📊 Formations Count: {self.results['formations_count']}/{self.results['formations_total_expected']} {'✅ PASS' if self.results['formations_count'] == self.results['formations_total_expected'] else '❌ FAIL'}")
        print(f"🛡️  Counter Tactics Count: {self.results['counters_count']}/{self.results['counters_total_expected']} {'✅ PASS' if self.results['counters_count'] == self.results['counters_total_expected'] else '❌ FAIL'}")
        print(f"🔍 Scout Tips: {'✅ PASS' if self.results['scout_tips_working'] else '❌ FAIL'}")
        
        print(f"\n📈 META Formations Found: {len(self.results['meta_formations_found'])}/{len(self.results['expected_meta_formations'])}")
        for formation_id in self.results['meta_formations_found']:
            print(f"   ✅ {formation_id}")
        
        print(f"\n🎯 META Counters Found: {len(self.results['meta_counters_found'])}/{len(self.results['expected_meta_counters'])}")
        for formation_id in self.results['meta_counters_found']:
            print(f"   ✅ {formation_id}")
        
        if self.results['errors']:
            print(f"\n❌ ERRORS FOUND ({len(self.results['errors'])}):")
            for i, error in enumerate(self.results['errors'], 1):
                print(f"   {i}. {error}")
        else:
            print("\n🎉 NO ERRORS FOUND - ALL TESTS PASSED!")
        
        # Determine overall success
        success_criteria = [
            self.results['health_check'],
            self.results['formations_count'] == self.results['formations_total_expected'],
            self.results['counters_count'] == self.results['counters_total_expected'],
            self.results['scout_tips_working'],
            len(self.results['errors']) == 0
        ]
        
        overall_success = all(success_criteria)
        print(f"\n🏆 OVERALL RESULT: {'✅ ALL TESTS PASSED' if overall_success else '❌ SOME TESTS FAILED'}")
        
        return overall_success

async def main():
    """Main test runner"""
    tester = BackendTester()
    success = await tester.run_all_tests()
    return success

if __name__ == "__main__":
    # Run the tests
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n🛑 Tests cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Test runner failed: {e}")
        sys.exit(1)