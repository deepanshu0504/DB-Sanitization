"""
Unit tests for database name normalization utilities.

Tests case-insensitive identifier normalization, qualified name building,
and CaseInsensitiveDict functionality.

Author: Database Sanitization Team
Date: 2026-03-28
"""

import pytest
from src.database.name_normalizer import (
    normalize_identifier,
    build_qualified_name,
    build_simple_key,
    parse_qualified_name,
    identifiers_match,
    CaseInsensitiveDict
)


class TestNormalizeIdentifier:
    """Test normalize_identifier function."""
    
    def test_lowercase_conversion(self):
        """Test that identifiers are converted to lowercase."""
        assert normalize_identifier("Orders") == "orders"
        assert normalize_identifier("CUSTOMERS") == "customers"
        assert normalize_identifier("Email") == "email"
    
    def test_already_lowercase(self):
        """Test that already lowercase identifiers remain unchanged."""
        assert normalize_identifier("orders") == "orders"
        assert normalize_identifier("dbo") == "dbo"
    
    def test_mixed_case(self):
        """Test mixed case identifiers."""
        assert normalize_identifier("UserId") == "userid"
        assert normalize_identifier("ClientAddress") == "clientaddress"
    
    def test_whitespace_trimming(self):
        """Test that whitespace is trimmed."""
        assert normalize_identifier("  Orders  ") == "orders"
        assert normalize_identifier("\tEmail\n") == "email"
    
    def test_unicode_support(self):
        """Test Unicode identifier handling."""
        assert normalize_identifier("Müller") == "müller"
        assert normalize_identifier("北京") == "北京"
    
    def test_empty_identifier_raises(self):
        """Test that empty identifiers raise ValueError."""
        with pytest.raises(ValueError, match="cannot be None or empty"):
            normalize_identifier("")
        
        with pytest.raises(ValueError, match="cannot be None or empty"):
            normalize_identifier(None)
    
    def test_non_string_raises(self):
        """Test that non-string identifiers raise TypeError."""
        with pytest.raises(TypeError, match="must be string"):
            normalize_identifier(123)


class TestBuildQualifiedName:
    """Test build_qualified_name function."""
    
    def test_table_qualified_normalized(self):
        """Test building normalized table qualified name."""
        result = build_qualified_name("dbo", "Orders", normalize=True)
        assert result == "[dbo].[orders]"
    
    def test_column_qualified_normalized(self):
        """Test building normalized column qualified name."""
        result = build_qualified_name("dbo", "Orders", "Email", normalize=True)
        assert result == "[dbo].[orders].[email]"
    
    def test_no_normalization(self):
        """Test building qualified name without normalization."""
        result = build_qualified_name("DBO", "Orders", "Email", normalize=False)
        assert result == "[DBO].[Orders].[Email]"
    
    def test_mixed_case_normalized(self):
        """Test mixed case gets normalized."""
        result = build_qualified_name("DBO", "ORDERS", "EMAIL", normalize=True)
        assert result == "[dbo].[orders].[email]"
    
    def test_empty_schema_raises(self):
        """Test that empty schema raises ValueError."""
        with pytest.raises(ValueError, match="cannot be None or empty"):
            build_qualified_name("", "Orders")
    
    def test_empty_table_raises(self):
        """Test that empty table raises ValueError."""
        with pytest.raises(ValueError, match="cannot be None or empty"):
            build_qualified_name("dbo", "")


class TestBuildSimpleKey:
    """Test build_simple_key function."""
    
    def test_table_key(self):
        """Test building simple table key."""
        result = build_simple_key("dbo", "Orders")
        assert result == "dbo.orders"
    
    def test_column_key(self):
        """Test building simple column key."""
        result = build_simple_key("dbo", "Orders", "Email")
        assert result == "dbo.orders.email"
    
    def test_custom_separator(self):
        """Test using custom separator."""
        result = build_simple_key("dbo", "Orders", separator="|")
        assert result == "dbo|orders"
    
    def test_no_normalization(self):
        """Test building key without normalization."""
        result = build_simple_key("DBO", "Orders", "Email", normalize=False)
        assert result == "DBO.Orders.Email"


class TestParseQualifiedName:
    """Test parse_qualified_name function."""
    
    def test_parse_with_brackets(self):
        """Test parsing qualified name with brackets."""
        schema, table, column = parse_qualified_name("[dbo].[Orders].[Email]")
        assert schema == "dbo"
        assert table == "Orders"
        assert column == "Email"
    
    def test_parse_without_brackets(self):
        """Test parsing qualified name without brackets."""
        schema, table, column = parse_qualified_name("dbo.orders.email")
        assert schema == "dbo"
        assert table == "orders"
        assert column == "email"
    
    def test_parse_table_only(self):
        """Test parsing table qualified name."""
        schema, table, column = parse_qualified_name("[dbo].[Orders]")
        assert schema == "dbo"
        assert table == "Orders"
        assert column is None
    
    def test_invalid_format_raises(self):
        """Test that invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid qualified name format"):
            parse_qualified_name("invalid")
        
        with pytest.raises(ValueError, match="Invalid qualified name format"):
            parse_qualified_name("too.many.parts.here")


class TestIdentifiersMatch:
    """Test identifiers_match function."""
    
    def test_case_insensitive_match(self):
        """Test case-insensitive matching (default)."""
        assert identifiers_match("Orders", "orders") is True
        assert identifiers_match("EMAIL", "email") is True
        assert identifiers_match("DBO", "dbo") is True
    
    def test_case_insensitive_no_match(self):
        """Test case-insensitive non-matching."""
        assert identifiers_match("Orders", "Users") is False
        assert identifiers_match("Email", "Phone") is False
    
    def test_case_sensitive_match(self):
        """Test case-sensitive matching."""
        assert identifiers_match("Orders", "Orders", case_sensitive=True) is True
        assert identifiers_match("orders", "orders", case_sensitive=True) is True
    
    def test_case_sensitive_no_match(self):
        """Test case-sensitive non-matching."""
        assert identifiers_match("Orders", "orders", case_sensitive=True) is False
        assert identifiers_match("EMAIL", "email", case_sensitive=True) is False
    
    def test_none_comparison(self):
        """Test None value comparison."""
        assert identifiers_match(None, None) is True
        assert identifiers_match("Orders", None) is False
        assert identifiers_match(None, "Orders") is False


class TestCaseInsensitiveDict:
    """Test CaseInsensitiveDict class."""
    
    def test_setitem_getitem(self):
        """Test setting and getting items case-insensitively."""
        d = CaseInsensitiveDict()
        d["Orders"] = {"count": 10}
        
        assert d["orders"] == {"count": 10}
        assert d["ORDERS"] == {"count": 10}
        assert d["Orders"] == {"count": 10}
    
    def test_contains(self):
        """Test case-insensitive containment check."""
        d = CaseInsensitiveDict()
        d["Orders"] = {"count": 10}
        
        assert "orders" in d
        assert "ORDERS" in d
        assert "Orders" in d
        assert "Users" not in d
    
    def test_preserves_original_case(self):
        """Test that original key case is preserved."""
        d = CaseInsensitiveDict()
        d["Orders"] = {"count": 10}
        
        keys = list(d.keys())
        assert keys == ["Orders"]  # Original case preserved
    
    def test_update_overwrites_with_new_case(self):
        """Test that updating with different case changes stored case."""
        d = CaseInsensitiveDict()
        d["Orders"] = {"count": 10}
        d["ORDERS"] = {"count": 20}  # Update with different case
        
        assert d["orders"] == {"count": 20}
        keys = list(d.keys())
        assert keys == ["ORDERS"]  # New case preserved
    
    def test_delitem(self):
        """Test case-insensitive deletion."""
        d = CaseInsensitiveDict()
        d["Orders"] = {"count": 10}
        
        del d["orders"]  # Delete using different case
        assert "Orders" not in d
    
    def test_len(self):
        """Test dictionary length."""
        d = CaseInsensitiveDict()
        d["Orders"] = {"count": 10}
        d["Users"] = {"count": 5}
        
        assert len(d) == 2
    
    def test_iter(self):
        """Test iterating over keys."""
        d = CaseInsensitiveDict()
        d["Orders"] = {"count": 10}
        d["Users"] = {"count": 5}
        
        keys = list(d)
        assert set(keys) == {"Orders", "Users"}
    
    def test_items(self):
        """Test iterating over items."""
        d = CaseInsensitiveDict()
        d["Orders"] = {"count": 10}
        
        items = list(d.items())
        assert items == [("Orders", {"count": 10})]
    
    def test_values(self):
        """Test iterating over values."""
        d = CaseInsensitiveDict()
        d["Orders"] = {"count": 10}
        d["Users"] = {"count": 5}
        
        values = list(d.values())
        assert {"count": 10} in values
        assert {"count": 5} in values
    
    def test_get_with_default(self):
        """Test get method with default value."""
        d = CaseInsensitiveDict()
        d["Orders"] = {"count": 10}
        
        assert d.get("orders") == {"count": 10}
        assert d.get("Users", "default") == "default"
    
    def test_copy(self):
        """Test dictionary copy."""
        d = CaseInsensitiveDict()
        d["Orders"] = {"count": 10}
        
        d2 = d.copy()
        assert d2["orders"] == {"count": 10}
        assert "Orders" in d2
    
    def test_to_dict(self):
        """Test conversion to standard dict."""
        d = CaseInsensitiveDict()
        d["Orders"] = {"count": 10}
        d["Users"] = {"count": 5}
        
        standard_dict = d.to_dict()
        assert isinstance(standard_dict, dict)
        assert standard_dict == {"Orders": {"count": 10}, "Users": {"count": 5}}
    
    def test_initialization_with_data(self):
        """Test initializing with existing dictionary."""
        data = {"Orders": {"count": 10}, "Users": {"count": 5}}
        d = CaseInsensitiveDict(data)
        
        assert d["orders"] == {"count": 10}
        assert d["USERS"] == {"count": 5}
    
    def test_keyerror_on_missing(self):
        """Test that KeyError is raised for missing keys."""
        d = CaseInsensitiveDict()
        
        with pytest.raises(KeyError):
            _ = d["NonExistent"]
    
    def test_non_string_key_raises(self):
        """Test that non-string keys raise TypeError."""
        d = CaseInsensitiveDict()
        
        with pytest.raises(TypeError, match="must be strings"):
            d[123] = "value"
        
        with pytest.raises(TypeError, match="must be strings"):
            _ = d[123]
