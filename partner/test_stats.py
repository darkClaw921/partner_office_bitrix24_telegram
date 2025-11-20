#!/usr/bin/env python3
"""Test script for verifying the stats functionality."""

import asyncio
from unittest.mock import AsyncMock, Mock

from app.services.stats import _get_partner_binding


async def test_get_partner_binding():
    """Test the _get_partner_binding function."""
    # Create a mock service
    service = Mock()
    
    # Test case 1: Entity type provided (C_)
    result = await _get_partner_binding(123, service, "C_")
    assert result == "C_123", f"Expected 'C_123', got '{result}'"
    print("✓ Test 1 passed: Provided entity type (C_) binding correct")
    
    # Test case 2: Entity type provided (CO_)
    result = await _get_partner_binding(456, service, "CO_")
    assert result == "CO_456", f"Expected 'CO_456', got '{result}'"
    print("✓ Test 2 passed: Provided entity type (CO_) binding correct")
    
    # Test case 3: Contact exists (API fallback)
    service.call = AsyncMock()
    service.call.side_effect = [
        {"ID": 123, "NAME": "Test Contact"},  # contact.get response
        {"error": "not found"}  # company.get response (won't be reached)
    ]
    
    result = await _get_partner_binding(123, service, None)  # None forces API check
    assert result == "C_123", f"Expected 'C_123', got '{result}'"
    print("✓ Test 3 passed: Contact binding via API correct")
    
    # Test case 4: Company exists (API fallback)
    service.call.reset_mock()
    service.call.side_effect = [
        {"error": "not found"},  # contact.get response
        {"ID": 456, "TITLE": "Test Company"}  # company.get response
    ]
    
    result = await _get_partner_binding(456, service, None)  # None forces API check
    assert result == "CO_456", f"Expected 'CO_456', got '{result}'"
    print("✓ Test 4 passed: Company binding via API correct")
    
    # Test case 5: Neither exists (fallback to contact)
    service.call.reset_mock()
    service.call.side_effect = [
        {"error": "not found"},  # contact.get response
        {"error": "not found"}   # company.get response
    ]
    
    result = await _get_partner_binding(789, service, None)  # None forces API check
    assert result == "C_789", f"Expected 'C_789', got '{result}'"
    print("✓ Test 5 passed: Fallback to contact binding via API correct")


if __name__ == "__main__":
    asyncio.run(test_get_partner_binding())
    print("All tests passed!")