@define start = '2024-01-01'
@define end = '2024-12-31'

SELECT * FROM orders
WHERE created BETWEEN @start AND @end
  AND region = @region;