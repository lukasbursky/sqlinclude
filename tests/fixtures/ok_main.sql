WITH users AS (
    @include "sub/users.sql"
),

orders AS (
    @include orders.sql
)

SELECT 1;