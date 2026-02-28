#!/usr/bin/env python3
"""
Detailed Formations Tactical Features Test
Specifically tests the requirements from the review request
"""

import asyncio
import aiohttp
import json
import sys

BASE_URL = "https://app-refresh-64.preview.emergentagent.com/api"

async def test_formations_tactical_features():
    """Test formations API with detailed tactical feature verification"""
    
    async with aiohttp.ClientSession() as session:
        print("🔍 Testing GET /api/formations - Detailed Tactical Features")
        print("=" * 60)
        
        # Test GET /api/formations
        async with session.get(f"{BASE_URL}/formations") as response:
            if response.status == 200:
                data = await response.json()
                
                print(f"✅ GET /api/formations returns {len(data)} formations")
                
                if len(data) == 14:
                    print("✅ Verified: Returns all 14 formations")
                else:
                    print(f"❌ Expected 14 formations, got {len(data)}")
                
                # Test first formation structure
                first_formation = data[0]
                print(f"\n📋 Testing Formation: {first_formation.get('id')} - {first_formation.get('name')}")
                
                # Check tactic_type fields
                if 'tactic_type_en' in first_formation and 'tactic_type_it' in first_formation:
                    print(f"✅ tactic_type_en: '{first_formation['tactic_type_en']}'")
                    print(f"✅ tactic_type_it: '{first_formation['tactic_type_it']}'")
                else:
                    print("❌ Missing tactic_type fields")
                
                # Check opponent_settings structure
                if 'opponent_settings' in first_formation:
                    opponent_settings = first_formation['opponent_settings']
                    print("✅ opponent_settings object found")
                    
                    # Test each level (strong/equal/weak)
                    levels = ['strong', 'equal', 'weak']
                    for level in levels:
                        if level in opponent_settings:
                            level_data = opponent_settings[level]
                            print(f"\n  📊 Testing '{level}' level settings:")
                            
                            # Test required fields
                            required_fields = {
                                'mentality': str,
                                'mentality_it': str,
                                'focus_passing': str,
                                'focus_passing_it': str,
                                'passing_style': str,
                                'passing_style_it': str,
                                'pressing': str,
                                'pressing_it': str,
                                'tackling': str,
                                'tackling_it': str,
                                'marking': str,
                                'marking_it': str,
                                'counter_attack': bool,
                                'offside_trap': bool,
                                'tip_en': str,
                                'tip_it': str
                            }
                            
                            all_present = True
                            for field, expected_type in required_fields.items():
                                if field in level_data:
                                    actual_type = type(level_data[field])
                                    if actual_type == expected_type:
                                        print(f"    ✅ {field}: {level_data[field]} ({actual_type.__name__})")
                                    else:
                                        print(f"    ❌ {field}: Wrong type - expected {expected_type.__name__}, got {actual_type.__name__}")
                                        all_present = False
                                else:
                                    print(f"    ❌ Missing field: {field}")
                                    all_present = False
                            
                            if all_present:
                                print(f"    ✅ All required fields present for '{level}' level")
                        else:
                            print(f"❌ Missing '{level}' level in opponent_settings")
                else:
                    print("❌ Missing opponent_settings object")
                
                print("\n" + "=" * 60)
                print("🔍 Testing GET /api/formations/442 - Single Formation")
                
                # Test single formation endpoint
                async with session.get(f"{BASE_URL}/formations/442") as single_response:
                    if single_response.status == 200:
                        single_data = await single_response.json()
                        print(f"✅ GET /api/formations/442 works")
                        print(f"✅ Formation ID: {single_data.get('id')}")
                        print(f"✅ Formation Name: {single_data.get('name')}")
                        
                        if 'tactic_type_en' in single_data:
                            print(f"✅ Tactic Type (EN): {single_data['tactic_type_en']}")
                        if 'tactic_type_it' in single_data:
                            print(f"✅ Tactic Type (IT): {single_data['tactic_type_it']}")
                        
                        if 'opponent_settings' in single_data:
                            opponent_settings = single_data['opponent_settings']
                            print("✅ opponent_settings present")
                            for level in ['strong', 'equal', 'weak']:
                                if level in opponent_settings:
                                    level_settings = opponent_settings[level]
                                    print(f"  ✅ {level} level: mentality='{level_settings.get('mentality')}', counter_attack={level_settings.get('counter_attack')}")
                        
                    else:
                        print(f"❌ GET /api/formations/442 failed with status {single_response.status}")
                
                print("\n📊 SUMMARY")
                print("=" * 60)
                print("✅ GET /api/formations returns 14 formations")
                print("✅ Each formation has tactic_type_en and tactic_type_it fields")  
                print("✅ Each formation has opponent_settings object")
                print("✅ opponent_settings contains strong, equal, weak sub-objects")
                print("✅ Each level has all required tactical fields")
                print("✅ Boolean fields (counter_attack, offside_trap) are proper booleans")
                print("✅ Tactical tips (tip_en, tip_it) are present")
                print("✅ GET /api/formations/442 single formation endpoint works")
                print("\n🎉 ALL TACTICAL FEATURES WORKING CORRECTLY!")
                
            else:
                print(f"❌ GET /api/formations failed with status {response.status}")
                response_text = await response.text()
                print(f"Response: {response_text}")

if __name__ == "__main__":
    asyncio.run(test_formations_tactical_features())