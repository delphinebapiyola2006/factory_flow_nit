from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
import sqlite3, os, io, csv, secrets
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from openpyxl import Workbook

DB = os.environ.get("FACTORYFLOW_DB", "factoryflow.db")
app = FastAPI(title="FactoryFlow", version="1.0.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
TOKENS = {}

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def now():
    return datetime.now().isoformat(timespec="seconds")

def money_paise(v):
    return int((Decimal(str(v))*100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def rupees(p):
    return f"₹{Decimal(p)/100:,.2f}"

def init():
    con=db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT, display_name TEXT);
    CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, name TEXT, kind TEXT, state TEXT, gstin TEXT);
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT, sku TEXT, pack TEXT, price_paise INTEGER, gst_rate TEXT, hsn TEXT, expected_output INTEGER DEFAULT 200);
    CREATE TABLE IF NOT EXISTS materials(id INTEGER PRIMARY KEY, name TEXT, category TEXT, unit TEXT, opening_qty TEXT, opening_rate TEXT);
    CREATE TABLE IF NOT EXISTS bom_lines(id INTEGER PRIMARY KEY, product_id INTEGER, material_id INTEGER, qty TEXT);
    CREATE TABLE IF NOT EXISTS stock_movements(id INTEGER PRIMARY KEY, material_id INTEGER, product_id INTEGER, qty_delta TEXT, unit TEXT, source_type TEXT, source_id INTEGER, note TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY, material_id INTEGER, qty TEXT, rate TEXT, supplier TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS production_runs(id INTEGER PRIMARY KEY, product_id INTEGER, batches INTEGER, expected_output INTEGER, good_output INTEGER, damaged_pouches INTEGER, cartons_used INTEGER, labour_paise INTEGER DEFAULT 0, utilities_paise INTEGER DEFAULT 0, created_at TEXT);
    CREATE TABLE IF NOT EXISTS production_actuals(id INTEGER PRIMARY KEY, run_id INTEGER, material_id INTEGER, planned_qty TEXT, actual_qty TEXT, unit TEXT);
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, customer_id INTEGER, salesman_id INTEGER, status TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS order_lines(id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER, qty INTEGER, unit_price_paise INTEGER);
    CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY, order_id INTEGER, invoice_no TEXT UNIQUE, taxable_paise INTEGER, cgst_paise INTEGER, sgst_paise INTEGER, igst_paise INTEGER, total_paise INTEGER, state TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, invoice_id INTEGER, amount_paise INTEGER, method TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY, username TEXT, action TEXT, entity TEXT, entity_id INTEGER, detail TEXT, created_at TEXT);
    """)
    # Lightweight schema migration for databases created by earlier versions.
    cols=[r["name"] for r in con.execute("PRAGMA table_info(products)")]
    if "expected_output" not in cols:
        con.execute("ALTER TABLE products ADD COLUMN expected_output INTEGER DEFAULT 200")
    con.commit(); con.close()

def audit(con, user, action, entity, eid, detail=""):
    con.execute("INSERT INTO audit_events(username,action,entity,entity_id,detail,created_at) VALUES(?,?,?,?,?,?)",
                (user,action,entity,eid,detail,now()))

def stock(con, material_id=None, product_id=None):
    if material_id is not None:
        rows=con.execute("SELECT qty_delta FROM stock_movements WHERE material_id=?",(material_id,)).fetchall()
    else:
        rows=con.execute("SELECT qty_delta FROM stock_movements WHERE product_id=?",(product_id,)).fetchall()
    return sum((Decimal(r["qty_delta"]) for r in rows), Decimal("0"))

def movement(con, material_id, product_id, qty, unit, source, source_id, note):
    con.execute("""INSERT INTO stock_movements(material_id,product_id,qty_delta,unit,source_type,source_id,note,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (material_id,product_id,str(qty),unit,source,source_id,note,now()))

def seed(con):
    con.execute("DELETE FROM audit_events"); con.execute("DELETE FROM payments"); con.execute("DELETE FROM invoices")
    con.execute("DELETE FROM order_lines"); con.execute("DELETE FROM orders"); con.execute("DELETE FROM production_actuals")
    con.execute("DELETE FROM production_runs"); con.execute("DELETE FROM purchases"); con.execute("DELETE FROM stock_movements")
    con.execute("DELETE FROM bom_lines"); con.execute("DELETE FROM materials"); con.execute("DELETE FROM products"); con.execute("DELETE FROM customers")
    con.execute("DELETE FROM users")
    users=[("admin","factory123","admin","Factory Admin"),("salesa","factory123","salesman","Salesman A"),
           ("salesb","factory123","salesman","Salesman B"),("production","factory123","production","Production Supervisor"),
           ("auditor","factory123","auditor","External Auditor"),("owner","factory123","owner","Factory Owner")]
    con.executemany("INSERT INTO users(username,password,role,display_name) VALUES(?,?,?,?)",users)
    customers=[("Retailer A","Retailer","Tamil Nadu","33AABCU9603R1ZP"),("Distributor B","Distributor","Karnataka","29AABCU9603R1ZP")]
    con.executemany("INSERT INTO customers(name,kind,state,gstin) VALUES(?,?,?,?)",customers)
    products=[("Murukku 200 g","MUR-200","200 g",5000,"5","190590")]
    con.executemany("INSERT INTO products(name,sku,pack,price_paise,gst_rate,hsn) VALUES(?,?,?,?,?,?)",products)
    mats=[("Flour","Raw","kg","100","42"),("Cooking oil","Raw","litre","30","140"),
          ("Salt and spice mix","Raw","kg","5","200"),("200 g pouch","Packaging","piece","500","2.5"),
          ("Carton","Packaging","piece","30","15")]
    con.executemany("INSERT INTO materials(name,category,unit,opening_qty,opening_rate) VALUES(?,?,?,?,?)",mats)
    # Opening stock is the first source-linked movement.
    for mid,qty,unit in [(1,"100","kg"),(2,"30","litre"),(3,"5","kg"),(4,"500","piece"),(5,"30","piece")]:
        movement(con,mid,None,Decimal(qty),unit,"opening_balance",0,"Benchmark opening stock")
    movement(con,None,1,Decimal("50"),"packet","opening_balance",0,"Benchmark opening finished goods")
    bom=[(1,1,"40"),(1,2,"10"),(1,3,"1.2"),(1,4,"200"),(1,5,"10")]
    con.executemany("INSERT INTO bom_lines(product_id,material_id,qty) VALUES(?,?,?)",bom)
    con.commit()

init()
con=db()
if not con.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
    seed(con)
con.close()

class Login(BaseModel):
    username:str
    password:str
class PurchaseIn(BaseModel):
    material_id:int
    qty:Decimal
    rate:Decimal
    supplier:str="Benchmark Supplier"
class ProductionIn(BaseModel):
    product_id:int=1
    batches:int=1
    actuals:dict
    good_output:int
    damaged_pouches:int=0
    cartons_used:int=0
    labour:Decimal=Decimal("0")
    utilities:Decimal=Decimal("0")
class OrderLineIn(BaseModel):
    product_id:int
    qty:int
class OrderIn(BaseModel):
    customer_id:int
    lines:List[OrderLineIn]
class CustomerCreate(BaseModel):
    name:str
    kind:str="Retailer"
    state:str
    gstin:str=""
class ProductCreate(BaseModel):
    name:str
    sku:str
    pack:str
    price:Decimal
    gst_rate:Decimal=Decimal("5")
    hsn:str="190590"
    expected_output:int=200
    bom:List[dict]
class PaymentIn(BaseModel):
    invoice_id:int
    amount:Decimal
    method:str="Bank transfer"
class OverheadIn(BaseModel):
    labour:Decimal
    utilities:Decimal

def current_user(authorization:Optional[str]=Header(None)):
    token=(authorization or "").replace("Bearer ","")
    username=TOKENS.get(token)
    if not username: raise HTTPException(401,"Please log in")
    con=db(); u=con.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone(); con.close()
    if not u: raise HTTPException(401,"Invalid session")
    return dict(u)

def require(*roles):
    def dep(u=Depends(current_user)):
        if u["role"] not in roles: raise HTTPException(403,"Your role cannot perform this action")
        return u
    return dep

@app.get("/", response_class=HTMLResponse)
def home():
    return FileResponse("app/static/index.html")

@app.post("/api/login")
def login(data:Login):
    con=db(); u=con.execute("SELECT * FROM users WHERE username=? AND password=?",(data.username,data.password)).fetchone(); con.close()
    if not u: raise HTTPException(401,"Incorrect username or password")
    token=secrets.token_urlsafe(32); TOKENS[token]=u["username"]
    return {"token":token,"username":u["username"],"name":u["display_name"],"role":u["role"]}

@app.get("/api/me")
def me(u=Depends(current_user)):
    return {"username":u["username"],"name":u["display_name"],"role":u["role"]}

@app.post("/api/logout")
def logout(authorization:Optional[str]=Header(None)):
    token=(authorization or "").replace("Bearer ", "")
    TOKENS.pop(token, None)
    return {"message":"Logged out"}

@app.post("/api/reset-benchmark")
def reset(u=Depends(require("admin","owner"))):
    con=db(); seed(con); audit(con,u["username"],"RESET_BENCHMARK","system",0,"Benchmark master data restored"); con.commit(); con.close()
    return {"message":"Benchmark reset complete"}

@app.get("/api/overview")
def overview(u=Depends(current_user)):
    con=db()
    orders=con.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
    pending=con.execute("SELECT COUNT(*) n FROM orders WHERE status='submitted'").fetchone()["n"]
    invoices=con.execute("SELECT COUNT(*) n FROM invoices").fetchone()["n"]
    sales=con.execute("SELECT COALESCE(SUM(total_paise),0) n FROM invoices").fetchone()["n"]
    outstanding=con.execute("""SELECT COALESCE(SUM(i.total_paise-COALESCE(p.paid,0)),0) n FROM invoices i
        LEFT JOIN (SELECT invoice_id,SUM(amount_paise) paid FROM payments GROUP BY invoice_id) p ON p.invoice_id=i.id""").fetchone()["n"]
    fg=stock(con,product_id=1)
    raw=[]
    for m in con.execute("SELECT * FROM materials"):
        raw.append({"id":m["id"],"name":m["name"],"unit":m["unit"],"qty":str(stock(con,material_id=m["id"]))})
    recent=con.execute("SELECT o.id,o.status,o.created_at,c.name customer FROM orders o JOIN customers c ON c.id=o.customer_id ORDER BY o.id DESC LIMIT 5").fetchall()
    con.close()
    return {"orders":orders,"pending":pending,"invoices":invoices,"sales":rupees(sales),"outstanding":rupees(outstanding),
            "finished_goods":str(fg),"raw":raw,"recent":[dict(r) for r in recent]}

@app.get("/api/analytics")
def analytics(u=Depends(current_user)):
    con=db()
    sales=con.execute("""SELECT substr(created_at,1,7) period, SUM(total_paise) total_paise, COUNT(*) invoices
        FROM invoices GROUP BY substr(created_at,1,7) ORDER BY period DESC LIMIT 6""").fetchall()
    sales=[dict(r) for r in reversed(sales)]
    statuses=[dict(r) for r in con.execute("SELECT status,COUNT(*) count FROM orders GROUP BY status ORDER BY status")]
    top=con.execute("""SELECT c.name customer, SUM(i.total_paise) total_paise FROM invoices i
        JOIN orders o ON o.id=i.order_id JOIN customers c ON c.id=o.customer_id
        GROUP BY c.id ORDER BY total_paise DESC LIMIT 5""").fetchall()
    con.close()
    return {"sales":sales,"statuses":statuses,"top_customers":[dict(r) for r in top]}

@app.get("/api/masters")
def masters(u=Depends(current_user)):
    con=db()
    customers=[dict(r) for r in con.execute("SELECT * FROM customers")]
    products=[dict(r) for r in con.execute("SELECT * FROM products")]
    materials=[]
    for r in con.execute("SELECT * FROM materials"):
        d=dict(r); d["stock"]=str(stock(con,material_id=r["id"])); materials.append(d)
    boms=[]
    for r in con.execute("""SELECT b.qty,m.name,m.unit FROM bom_lines b JOIN materials m ON m.id=b.material_id WHERE b.product_id=1"""):
        boms.append(dict(r))
    con.close()
    return {"customers":customers,"products":products,"materials":materials,"bom":boms}

@app.post("/api/customers")
def create_customer(data:CustomerCreate,u=Depends(require("admin","owner"))):
    if not data.name.strip() or not data.state.strip(): raise HTTPException(400,"Customer name and state are required")
    con=db(); cur=con.execute("INSERT INTO customers(name,kind,state,gstin) VALUES(?,?,?,?)",(data.name.strip(),data.kind,data.state.strip(),data.gstin.strip()))
    audit(con,u["username"],"CUSTOMER_CREATED","customer",cur.lastrowid,data.name)
    con.commit(); con.close(); return {"customer_id":cur.lastrowid,"message":"Customer created"}

@app.post("/api/products")
def create_product(data:ProductCreate,u=Depends(require("admin","owner"))):
    if not data.name.strip() or not data.sku.strip() or data.price<0 or data.gst_rate<0 or data.expected_output<1 or not data.bom:
        raise HTTPException(400,"Provide product details, positive expected output and at least one BOM line")
    con=db()
    for line in data.bom:
        if int(line.get("material_id",0))<1 or Decimal(str(line.get("qty",0)))<=0:
            con.close(); raise HTTPException(400,"Every BOM line needs a valid material and positive quantity")
        if not con.execute("SELECT 1 FROM materials WHERE id=?",(int(line["material_id"]),)).fetchone():
            con.close(); raise HTTPException(404,"BOM material not found")
    cur=con.execute("INSERT INTO products(name,sku,pack,price_paise,gst_rate,hsn,expected_output) VALUES(?,?,?,?,?,?,?)",
        (data.name.strip(),data.sku.strip(),data.pack.strip(),money_paise(data.price),str(data.gst_rate),data.hsn.strip(),data.expected_output))
    pid=cur.lastrowid
    for line in data.bom:
        con.execute("INSERT INTO bom_lines(product_id,material_id,qty) VALUES(?,?,?)",(pid,int(line["material_id"]),str(Decimal(str(line["qty"])))) )
    audit(con,u["username"],"PRODUCT_CREATED","product",pid,data.name)
    con.commit(); con.close(); return {"product_id":pid,"message":"Product and BOM created"}

@app.post("/api/purchases")
def purchase(data:PurchaseIn,u=Depends(require("admin","production","owner"))):
    if data.qty<=0 or data.rate<0: raise HTTPException(400,"Quantity must be positive and rate non-negative")
    con=db(); m=con.execute("SELECT * FROM materials WHERE id=?",(data.material_id,)).fetchone()
    if not m: con.close(); raise HTTPException(404,"Material not found")
    cur=con.execute("INSERT INTO purchases(material_id,qty,rate,supplier,created_at) VALUES(?,?,?,?,?)",
                    (m["id"],str(data.qty),str(data.rate),data.supplier,now()))
    pid=cur.lastrowid; movement(con,m["id"],None,data.qty,m["unit"],"purchase",pid,f"Purchase from {data.supplier}")
    audit(con,u["username"],"PURCHASE_RECEIVED","purchase",pid,f"{data.qty} {m['unit']} {m['name']} @ ₹{data.rate}")
    con.commit(); con.close(); return {"message":"Purchase recorded","purchase_id":pid}

@app.post("/api/production")
def production(data:ProductionIn,u=Depends(require("production","admin","owner"))):
    if data.batches<1 or data.good_output<0: raise HTTPException(400,"Invalid batch or output")
    con=db()
    bom=con.execute("SELECT * FROM bom_lines WHERE product_id=?",(data.product_id,)).fetchall()
    if not bom: con.close(); raise HTTPException(400,"BOM not configured")
    product=con.execute("SELECT expected_output FROM products WHERE id=?",(data.product_id,)).fetchone()
    if not product: con.close(); raise HTTPException(404,"Product not found")
    expected=int(product["expected_output"] or 200)*data.batches
    actual_map={str(k):Decimal(str(v)) for k,v in data.actuals.items()}
    # Pouch actual includes good pouches plus damaged pouches; carton count is separately captured.
    actual_map["4"]=Decimal(data.good_output+data.damaged_pouches)
    actual_map["5"]=Decimal(data.cartons_used)
    cur=con.execute("""INSERT INTO production_runs(product_id,batches,expected_output,good_output,damaged_pouches,cartons_used,labour_paise,utilities_paise,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (data.product_id,data.batches,expected,data.good_output,data.damaged_pouches,data.cartons_used,
                     money_paise(data.labour),money_paise(data.utilities),now()))
    rid=cur.lastrowid
    for line in bom:
        mid=line["material_id"]; planned=Decimal(line["qty"])*data.batches
        actual=actual_map.get(str(mid),planned)
        m=con.execute("SELECT * FROM materials WHERE id=?",(mid,)).fetchone()
        available=stock(con,material_id=mid)
        if actual>available: con.rollback(); con.close(); raise HTTPException(400,f"Insufficient {m['name']} stock: available {available} {m['unit']}, needed {actual}")
        con.execute("INSERT INTO production_actuals(run_id,material_id,planned_qty,actual_qty,unit) VALUES(?,?,?,?,?)",
                    (rid,mid,str(planned),str(actual),m["unit"]))
        movement(con,mid,None,-actual,m["unit"],"production_issue",rid,f"Production run #{rid}")
    movement(con,None,data.product_id,Decimal(data.good_output),"packet","production_output",rid,f"Good output from run #{rid}")
    audit(con,u["username"],"PRODUCTION_POSTED","production_run",rid,f"Output {data.good_output}/{expected}")
    con.commit(); con.close()
    return {"run_id":rid,"expected_output":expected,"good_output":data.good_output,
            "yield_variance_pct":round((data.good_output-expected)/expected*100,2) if expected else 0}

@app.get("/api/production")
def production_list(u=Depends(current_user)):
    con=db(); runs=[]
    for r in con.execute("SELECT * FROM production_runs ORDER BY id DESC"):
        d=dict(r); d["material_variances"]=[]
        for a in con.execute("SELECT pa.*,m.name FROM production_actuals pa JOIN materials m ON m.id=pa.material_id WHERE run_id=?",(r["id"],)):
            planned=Decimal(a["planned_qty"]); actual=Decimal(a["actual_qty"])
            pct=(actual-planned)/planned*100 if planned else Decimal(0)
            d["material_variances"].append({"name":a["name"],"planned":str(planned),"actual":str(actual),"variance_pct":round(float(pct),2),"flag":abs(pct)>3})
        d["yield_variance_pct"]=round((r["good_output"]-r["expected_output"])/r["expected_output"]*100,2) if r["expected_output"] else 0
        runs.append(d)
    con.close(); return runs

@app.post("/api/orders")
def create_order(data:OrderIn,u=Depends(require("salesman","admin","owner"))):
    if not data.lines: raise HTTPException(400,"Add at least one product")
    con=db()
    if not con.execute("SELECT 1 FROM customers WHERE id=?",(data.customer_id,)).fetchone(): con.close(); raise HTTPException(404,"Customer not found")
    cur=con.execute("INSERT INTO orders(customer_id,salesman_id,status,created_at) VALUES(?,?,?,?)",
                    (data.customer_id,u["id"],"submitted",now()))
    oid=cur.lastrowid
    for line in data.lines:
        if line.qty<1: con.rollback(); con.close(); raise HTTPException(400,"Quantity must be positive")
        p=con.execute("SELECT * FROM products WHERE id=?",(line.product_id,)).fetchone()
        con.execute("INSERT INTO order_lines(order_id,product_id,qty,unit_price_paise) VALUES(?,?,?,?)",(oid,line.product_id,line.qty,p["price_paise"]))
    audit(con,u["username"],"ORDER_SUBMITTED","order",oid,"Sales order submitted")
    con.commit(); con.close(); return {"order_id":oid,"status":"submitted"}

@app.get("/api/orders")
def orders(u=Depends(current_user)):
    con=db()
    q="""SELECT o.*,c.name customer,c.state,c.gstin,u.display_name salesman,
         (SELECT SUM(ol.qty) FROM order_lines ol WHERE ol.order_id=o.id) qty
         FROM orders o JOIN customers c ON c.id=o.customer_id JOIN users u ON u.id=o.salesman_id"""
    params=()
    if u["role"]=="salesman": q+=" WHERE o.salesman_id=?"; params=(u["id"],)
    q+=" ORDER BY o.id DESC"
    result=[]
    for r in con.execute(q,params):
        d=dict(r); d["lines"]=[dict(x) for x in con.execute("SELECT ol.*,p.name product FROM order_lines ol JOIN products p ON p.id=ol.product_id WHERE order_id=?",(r["id"],))]
        result.append(d)
    con.close(); return result

@app.post("/api/orders/{oid}/approve")
def approve(oid:int,u=Depends(require("admin","owner"))):
    con=db(); o=con.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
    if not o: con.close(); raise HTTPException(404,"Order not found")
    if o["status"]!="submitted": con.close(); raise HTTPException(400,"Only submitted orders can be approved")
    lines=con.execute("SELECT * FROM order_lines WHERE order_id=?",(oid,)).fetchall()
    for l in lines:
        available=stock(con,product_id=l["product_id"])
        if available<l["qty"]:
            con.close(); raise HTTPException(409,f"Insufficient finished goods: requested {l['qty']}, available {available}, shortage {l['qty']-available}")
    con.execute("UPDATE orders SET status='approved' WHERE id=?",(oid,))
    audit(con,u["username"],"ORDER_APPROVED","order",oid,"Stock validated")
    con.commit(); con.close(); return {"message":"Order approved"}

@app.post("/api/orders/{oid}/invoice")
def invoice(oid:int,u=Depends(require("admin","owner"))):
    con=db(); o=con.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
    if not o: con.close(); raise HTTPException(404,"Order not found")
    if o["status"]!="approved": con.close(); raise HTTPException(400,"Approve the order before invoicing")
    lines=con.execute("SELECT * FROM order_lines WHERE order_id=?",(oid,)).fetchall()
    taxable=sum(l["qty"]*l["unit_price_paise"] for l in lines)
    rate=Decimal("0.05")
    total_tax=int((Decimal(taxable)*rate).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
    customer=con.execute("SELECT * FROM customers WHERE id=?",(o["customer_id"],)).fetchone()
    if customer["state"]=="Tamil Nadu":
        cgst=total_tax//2; sgst=total_tax-cgst; igst=0
    else: cgst=0; sgst=0; igst=total_tax
    invno=f"FF/2026-27/{oid:04d}"
    cur=con.execute("INSERT INTO invoices(order_id,invoice_no,taxable_paise,cgst_paise,sgst_paise,igst_paise,total_paise,state,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (oid,invno,taxable,cgst,sgst,igst,taxable+total_tax,customer["state"],now()))
    iid=cur.lastrowid; con.execute("UPDATE orders SET status='invoiced' WHERE id=?",(oid,))
    audit(con,u["username"],"INVOICE_CREATED","invoice",iid,invno)
    con.commit(); con.close(); return {"invoice_id":iid,"invoice_no":invno,"taxable":rupees(taxable),"cgst":rupees(cgst),"sgst":rupees(sgst),"igst":rupees(igst),"total":rupees(taxable+total_tax)}

@app.post("/api/orders/{oid}/dispatch")
def dispatch(oid:int,u=Depends(require("admin","owner"))):
    con=db(); o=con.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
    if not o: con.close(); raise HTTPException(404,"Order not found")
    if o["status"]!="invoiced": con.close(); raise HTTPException(400,"Generate invoice before dispatch")
    lines=con.execute("SELECT * FROM order_lines WHERE order_id=?",(oid,)).fetchall()
    for l in lines:
        available=stock(con,product_id=l["product_id"])
        if available<l["qty"]: con.close(); raise HTTPException(409,f"Insufficient stock: {available} available")
    for l in lines: movement(con,None,l["product_id"],-Decimal(l["qty"]),"packet","dispatch",oid,f"Dispatch order #{oid}")
    con.execute("UPDATE orders SET status='dispatched' WHERE id=?",(oid,))
    audit(con,u["username"],"ORDER_DISPATCHED","order",oid,"Finished goods dispatched")
    con.commit(); con.close(); return {"message":"Dispatch recorded; finished goods reduced"}

@app.get("/api/invoices")
def invoices(u=Depends(current_user)):
    con=db(); rows=[]
    for r in con.execute("""SELECT i.*,c.name customer,c.gstin,o.id order_id FROM invoices i JOIN orders o ON o.id=i.order_id JOIN customers c ON c.id=o.customer_id ORDER BY i.id DESC"""):
        d=dict(r); paid=con.execute("SELECT COALESCE(SUM(amount_paise),0) n FROM payments WHERE invoice_id=?",(r["id"],)).fetchone()["n"]
        d["paid"]=rupees(paid); d["outstanding"]=rupees(r["total_paise"]-paid); rows.append(d)
    con.close(); return rows

@app.post("/api/payments")
def payment(data:PaymentIn,u=Depends(require("admin","owner"))):
    amount=money_paise(data.amount)
    if amount<=0: raise HTTPException(400,"Payment must be positive")
    con=db(); inv=con.execute("SELECT * FROM invoices WHERE id=?",(data.invoice_id,)).fetchone()
    if not inv: con.close(); raise HTTPException(404,"Invoice not found")
    paid=con.execute("SELECT COALESCE(SUM(amount_paise),0) n FROM payments WHERE invoice_id=?",(data.invoice_id,)).fetchone()["n"]
    if paid+amount>inv["total_paise"]: con.close(); raise HTTPException(400,"Payment exceeds invoice outstanding")
    cur=con.execute("INSERT INTO payments(invoice_id,amount_paise,method,created_at) VALUES(?,?,?,?)",(data.invoice_id,amount,data.method,now()))
    audit(con,u["username"],"PAYMENT_RECEIVED","payment",cur.lastrowid,rupees(amount))
    con.commit(); con.close(); return {"message":"Payment recorded"}

@app.post("/api/production/{rid}/overheads")
def overheads(rid:int,data:OverheadIn,u=Depends(require("production","admin","owner"))):
    con=db(); r=con.execute("SELECT * FROM production_runs WHERE id=?",(rid,)).fetchone()
    if not r: con.close(); raise HTTPException(404,"Production run not found")
    con.execute("UPDATE production_runs SET labour_paise=?,utilities_paise=? WHERE id=?",(money_paise(data.labour),money_paise(data.utilities),rid))
    audit(con,u["username"],"OVERHEADS_UPDATED","production_run",rid,"Labour and utilities updated")
    con.commit(); con.close(); return {"message":"Overheads updated"}

@app.get("/api/costing")
def costing(u=Depends(current_user)):
    con=db(); result=[]
    for r in con.execute("SELECT * FROM production_runs ORDER BY id DESC"):
        total=Decimal(0)
        details=[]
        for a in con.execute("SELECT * FROM production_actuals WHERE run_id=?",(r["id"],)):
            m=con.execute("SELECT * FROM materials WHERE id=?",(a["material_id"],)).fetchone()
            # Weighted-average purchase valuation for materials; opening rate is included.
            opening=Decimal(m["opening_qty"]); opening_rate=Decimal(m["opening_rate"])
            purchases=con.execute("SELECT qty,rate FROM purchases WHERE material_id=?",(m["id"],)).fetchall()
            total_qty=opening; total_value=opening*opening_rate
            for p in purchases:
                q=Decimal(p["qty"]); total_qty+=q; total_value+=q*Decimal(p["rate"])
            avg=total_value/total_qty if total_qty else Decimal(0)
            cost=Decimal(a["actual_qty"])*avg; total+=cost
            details.append({"material":m["name"],"qty":a["actual_qty"],"unit":m["unit"],"rate":str(avg),"cost":str(cost)})
        total+=Decimal(r["labour_paise"]+r["utilities_paise"])/100
        per=total/Decimal(r["good_output"]) if r["good_output"] else Decimal(0)
        result.append({"run_id":r["id"],"good_output":r["good_output"],"material_cost":str(total),"cost_per_packet":str(per),
                       "labour":rupees(r["labour_paise"]),"utilities":rupees(r["utilities_paise"]),"details":details})
    con.close(); return result

@app.get("/api/ledger")
def ledger(u=Depends(current_user)):
    con=db(); rows=[]
    for r in con.execute("""SELECT sm.*,m.name material,p.name product FROM stock_movements sm
      LEFT JOIN materials m ON m.id=sm.material_id LEFT JOIN products p ON p.id=sm.product_id ORDER BY sm.id DESC LIMIT 250"""):
        d=dict(r); d["item"]=d["material"] or d["product"]; d["balance"]=str(stock(con,material_id=r["material_id"]) if r["material_id"] else stock(con,product_id=r["product_id"]))
        rows.append(d)
    con.close(); return rows

@app.get("/api/salesman-summary")
def salesman_summary(u=Depends(current_user)):
    if u["role"] not in ("salesman","admin","owner"): raise HTTPException(403,"Sales summary is not available")
    con=db(); where="WHERE o.salesman_id=?" if u["role"]=="salesman" else ""
    params=(u["id"],) if where else ()
    rows=[dict(r) for r in con.execute(f"""SELECT c.name customer,COUNT(DISTINCT o.id) orders,
       COALESCE(SUM(ol.qty),0) packets,COALESCE(SUM(ol.qty*ol.unit_price_paise),0) taxable_paise
       FROM orders o JOIN customers c ON c.id=o.customer_id JOIN order_lines ol ON ol.order_id=o.id
       {where} GROUP BY c.id ORDER BY taxable_paise DESC""",params)]
    con.close(); return rows

@app.get("/api/reports")
def reports(start_date:Optional[str]=None,end_date:Optional[str]=None,u=Depends(current_user)):
    con=db()
    date_clause=""
    params=[]
    if start_date: date_clause += " AND date(i.created_at)>=date(?)"; params.append(start_date)
    if end_date: date_clause += " AND date(i.created_at)<=date(?)"; params.append(end_date)
    sales=con.execute("""SELECT i.invoice_no,c.name customer,c.state,i.taxable_paise,i.cgst_paise,i.sgst_paise,i.igst_paise,i.total_paise,i.created_at
      FROM invoices i JOIN orders o ON o.id=i.order_id JOIN customers c ON c.id=o.customer_id WHERE 1=1 """+date_clause+" ORDER BY i.id",params).fetchall()
    p_clause=""; p_params=[]
    if start_date: p_clause += " AND date(p.created_at)>=date(?)"; p_params.append(start_date)
    if end_date: p_clause += " AND date(p.created_at)<=date(?)"; p_params.append(end_date)
    purchases=con.execute("""SELECT p.id,m.name material,p.qty,p.rate,p.supplier,p.created_at FROM purchases p JOIN materials m ON m.id=p.material_id WHERE 1=1 """+p_clause,p_params).fetchall()
    inv=con.execute("SELECT COALESCE(SUM(taxable_paise),0) taxable,COALESCE(SUM(cgst_paise),0) cgst,COALESCE(SUM(sgst_paise),0) sgst,COALESCE(SUM(igst_paise),0) igst FROM invoices i WHERE (? IS NULL OR date(i.created_at)>=date(?)) AND (? IS NULL OR date(i.created_at)<=date(?))",(start_date,start_date,end_date,end_date)).fetchone()
    stock_rows=[]
    for m in con.execute("SELECT * FROM materials"):
        stock_rows.append({"item":m["name"],"category":m["category"],"unit":m["unit"],"closing":str(stock(con,material_id=m["id"]))})
    for product in con.execute("SELECT id,name FROM products"):
        stock_rows.append({"item":product["name"],"category":"Finished goods","unit":"packet","closing":str(stock(con,product_id=product["id"]))})
    production=[]
    for r in con.execute("SELECT * FROM production_runs WHERE (? IS NULL OR date(created_at)>=date(?)) AND (? IS NULL OR date(created_at)<=date(?))",(start_date,start_date,end_date,end_date)):
        production.append(dict(r))
    collections=con.execute("SELECT COALESCE(SUM(p.amount_paise),0) total FROM payments p JOIN invoices i ON i.id=p.invoice_id WHERE (? IS NULL OR date(p.created_at)>=date(?)) AND (? IS NULL OR date(p.created_at)<=date(?))",(start_date,start_date,end_date,end_date)).fetchone()["total"]
    outstanding=con.execute("SELECT COALESCE(SUM(i.total_paise-COALESCE(x.paid,0)),0) total FROM invoices i LEFT JOIN (SELECT invoice_id,SUM(amount_paise) paid FROM payments GROUP BY invoice_id) x ON x.invoice_id=i.id WHERE (? IS NULL OR date(i.created_at)>=date(?)) AND (? IS NULL OR date(i.created_at)<=date(?))",(start_date,start_date,end_date,end_date)).fetchone()["total"]
    con.close()
    return {"sales":[dict(x) for x in sales],"purchases":[dict(x) for x in purchases],"gst":dict(inv),"stock":stock_rows,"production":production,"collections_paise":collections,"outstanding_paise":outstanding,"period":{"start":start_date,"end":end_date}}

@app.get("/api/export/{kind}")
def export(kind:str,start_date:Optional[str]=None,end_date:Optional[str]=None,u=Depends(current_user)):
    data=reports(start_date,end_date,u)
    if kind=="csv":
        output=io.StringIO(); w=csv.writer(output); w.writerow(["Invoice","Customer","State","Taxable","CGST","SGST","IGST","Total"])
        for r in data["sales"]: w.writerow([r["invoice_no"],r["customer"],r["state"],rupees(r["taxable_paise"]),rupees(r["cgst_paise"]),rupees(r["sgst_paise"]),rupees(r["igst_paise"]),rupees(r["total_paise"])])
        return StreamingResponse(iter([output.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=factoryflow_sales.csv"})
    if kind=="xlsx":
        wb=Workbook(); ws=wb.active; ws.title="Sales Register"
        ws.append(["Invoice","Customer","State","Taxable (₹)","CGST (₹)","SGST (₹)","IGST (₹)","Total (₹)"])
        for r in data["sales"]: ws.append([r["invoice_no"],r["customer"],r["state"],r["taxable_paise"]/100,r["cgst_paise"]/100,r["sgst_paise"]/100,r["igst_paise"]/100,r["total_paise"]/100])
        st=wb.create_sheet("Stock Summary"); st.append(["Item","Category","Unit","Closing"])
        for r in data["stock"]: st.append([r["item"],r["category"],r["unit"],r["closing"]])
        bio=io.BytesIO(); wb.save(bio); bio.seek(0)
        return StreamingResponse(bio,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=factoryflow_reports.xlsx"})
    if kind=="pdf":
        bio=io.BytesIO(); c=canvas.Canvas(bio,pagesize=A4); y=800
        c.setFont("Helvetica-Bold",18); c.drawString(48,y,"FactoryFlow — Monthly Audit Summary"); y-=35
        c.setFont("Helvetica",10)
        for line in [f"Sales invoices: {len(data['sales'])}",f"Taxable supplies: {rupees(data['gst']['taxable'])}",
                     f"CGST: {rupees(data['gst']['cgst'])}",f"SGST: {rupees(data['gst']['sgst'])}",f"IGST: {rupees(data['gst']['igst'])}","",
                     "Stock closing balances:"]:
            c.drawString(48,y,line); y-=18
        for r in data["stock"]:
            c.drawString(60,y,f"{r['item']}: {r['closing']} {r['unit']}"); y-=16
            if y<70: c.showPage(); y=800
        c.save(); bio.seek(0)
        return StreamingResponse(bio,media_type="application/pdf",headers={"Content-Disposition":"attachment; filename=factoryflow_audit_report.pdf"})
    raise HTTPException(404,"Export format not supported")

@app.get("/api/invoices/{iid}/pdf")
def invoice_pdf(iid:int,u=Depends(current_user)):
    con=db(); r=con.execute("""SELECT i.*,c.name customer,c.state,c.gstin,p.name product,ol.qty,pr.price_paise
      FROM invoices i JOIN orders o ON o.id=i.order_id JOIN customers c ON c.id=o.customer_id
      JOIN order_lines ol ON ol.order_id=o.id JOIN products p ON p.id=ol.product_id JOIN products pr ON pr.id=ol.product_id
      WHERE i.id=?""",(iid,)).fetchone(); con.close()
    if not r: raise HTTPException(404,"Invoice not found")
    bio=io.BytesIO(); c=canvas.Canvas(bio,pagesize=A4); y=790
    c.setFont("Helvetica-Bold",20); c.drawString(48,y,"FACTORYFLOW"); y-=30
    c.setFont("Helvetica-Bold",14); c.drawString(48,y,"TAX INVOICE"); y-=28
    c.setFont("Helvetica",10)
    for line in [f"Invoice: {r['invoice_no']}",f"Customer: {r['customer']}",f"GSTIN: {r['gstin']}",f"Place of supply: {r['state']}",
                 f"Product: {r['product']}  |  HSN: 190590",f"Quantity: {r['qty']}",f"Taxable value: {rupees(r['taxable_paise'])}",
                 f"CGST: {rupees(r['cgst_paise'])}",f"SGST: {rupees(r['sgst_paise'])}",f"IGST: {rupees(r['igst_paise'])}",
                 f"Invoice total: {rupees(r['total_paise'])}","", "Illustrative prototype invoice — validate statutory requirements before business use."]:
        c.drawString(48,y,line); y-=22
    c.save(); bio.seek(0)
    return StreamingResponse(bio,media_type="application/pdf",headers={"Content-Disposition":f"attachment; filename={r['invoice_no'].replace('/','-')}.pdf"})

@app.get("/api/audit")
def audit_log(u=Depends(require("admin","owner","auditor"))):
    con=db(); rows=[dict(r) for r in con.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT 200")]; con.close(); return rows
