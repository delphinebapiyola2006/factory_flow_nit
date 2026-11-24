"""Reset and execute the NIT Trichy section-5 benchmark in the local demo DB.
WARNING: This resets demo transactions and restores the supplied dummy master data.
Run from the project root: python scripts/seed_benchmark.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
login = client.post('/api/login', json={'username': 'admin', 'password': 'factory123'})
login.raise_for_status()
h = {'Authorization': 'Bearer ' + login.json()['token']}
client.post('/api/reset-benchmark', headers=h).raise_for_status()

# 1. Purchase 60 kg flour @ ₹45/kg
r = client.post('/api/purchases', headers=h, json={'material_id': 1, 'qty': '60', 'rate': '45', 'supplier': 'Benchmark Supplier'})
r.raise_for_status()
# 2-3. One run: 40 kg flour, 10.5 L oil, 1.2 kg spice; 188 good, 6 damaged pouches, 9 cartons
r = client.post('/api/production', headers=h, json={
    'product_id': 1, 'batches': 1,
    'actuals': {'1': '40', '2': '10.5', '3': '1.2'},
    'good_output': 188, 'damaged_pouches': 6, 'cartons_used': 9,
    'labour': '1200', 'utilities': '600'
})
r.raise_for_status()
run_id = r.json()['run_id']
# 4-5. Retailer A order, approval, invoice and dispatch
r = client.post('/api/orders', headers=h, json={'customer_id': 1, 'lines': [{'product_id': 1, 'qty': 150}]})
r.raise_for_status(); order_a = r.json()['order_id']
client.post(f'/api/orders/{order_a}/approve', headers=h).raise_for_status()
inv = client.post(f'/api/orders/{order_a}/invoice', headers=h); inv.raise_for_status()
client.post(f'/api/orders/{order_a}/dispatch', headers=h).raise_for_status()
# 6. Distributor B order; it remains submitted because approval must flag shortage 32
r = client.post('/api/orders', headers=h, json={'customer_id': 2, 'lines': [{'product_id': 1, 'qty': 120}]})
r.raise_for_status(); order_b = r.json()['order_id']
shortage = client.post(f'/api/orders/{order_b}/approve', headers=h)
# 7. ₹4,000 collection
client.post('/api/payments', headers=h, json={'invoice_id': inv.json()['invoice_id'], 'amount': '4000', 'method': 'UPI'}).raise_for_status()
# 8. Record overheads explicitly against the run
client.post(f'/api/production/{run_id}/overheads', headers=h, json={'labour': '1200', 'utilities': '600'}).raise_for_status()

masters = client.get('/api/masters', headers=h).json()
overview = client.get('/api/overview', headers=h).json()
invoices = client.get('/api/invoices', headers=h).json()
print('Benchmark setup complete')
print('Retailer A invoice:', inv.json())
print('Distributor B approval:', shortage.status_code, shortage.json().get('detail'))
print('Finished goods closing:', overview['finished_goods'], 'packets')
print('Raw material closing:', {m['name']: m['stock'] for m in masters['materials']})
print('Retailer A outstanding:', invoices[0]['outstanding'])
print('Expected: FG 88, flour 120, oil 19.5, spice 3.8, pouches 306, cartons 21; invoice ₹7,875; outstanding ₹3,875.')
