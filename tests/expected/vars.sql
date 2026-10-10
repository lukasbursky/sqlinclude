
SELECT * FROM orders
WHERE created BETWEEN '2024-01-01' AND '2024-12-31'
  AND region = @region;
