import json
with open('orders.json', 'r', encoding='utf-8-sig') as f:
    data = json.load(f)
orders = data.get('data', [])
for o in orders:
    if o.get('state') == 'live':
        print(f"side={o['side']} posSide={o['posSide']} px={o['px']} sz={o['sz']} ordId={o['ordId']}")
print(f'Total live orders: {len([o for o in orders if o.get("state") == "live"])}')
