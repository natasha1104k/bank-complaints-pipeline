select distinct
    md5(product)      as product_key,
    product
from {{ ref('stg_complaints') }}
where product is not null
