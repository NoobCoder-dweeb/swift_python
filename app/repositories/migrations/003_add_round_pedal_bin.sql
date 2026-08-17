-- Existing Docker volumes predate this catalogue row. Keep this idempotent
-- because repository initialisation runs migrations on every application boot.
INSERT INTO swift_products (
    product_id,
    sku,
    name,
    source_url,
    category,
    description,
    currency,
    unit_price,
    stock_availability,
    unit_of_measure,
    status,
    created_at,
    updated_at
) VALUES (
    'SWP-ROUND-PEDAL-BIN-18L',
    'SW-MAINTENANCE-REPAIR-AND-O-ROUND-PEDAL-BIN-18L',
    'Round Pedal Bin 18L',
    'https://safetyware.com/product/round-pedal-bin-18l/',
    'Maintenance Repair And Operations Mro',
    'Safetyware catalogue item from category ''Maintenance Repair And Operations Mro''. Source: https://safetyware.com/product/round-pedal-bin-18l/. Public catalogue price was unavailable; unit_price is an estimated average for similar products in this category.',
    'RM',
    431.01,
    180,
    'unit',
    'active',
    '2026-06-24T01:00:23.319941+00:00',
    '2026-06-24T01:00:23.319941+00:00'
)
ON CONFLICT DO NOTHING;
