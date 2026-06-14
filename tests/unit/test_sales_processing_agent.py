import pytest

def test_sales_agent_queries_odoo_for_product_context(sales_agent, mock_odoo_client):
    """ensures product facts come from the approved data client."""
    mock_odoo_client.get_product.return_value = {
        "product": "Helmet",
        "stock_availability": 5,
        "price": 25.00,
    }

    result = sales_agent.get_product_context(
        "What is the stock availability of safety helmet?"
    )

    assert result["product"] == "Helmet"
    assert result["stock_availability"] == 5
    mock_odoo_client.get_product.assert_called_once()
