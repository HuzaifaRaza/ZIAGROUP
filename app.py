import streamlit as st
import pandas as pd
import datetime
import json
import hashlib
from supabase import create_client, Client
import io
from fpdf import FPDF
import base64

# -------------------- Page Config --------------------
st.set_page_config(page_title="Catering System", layout="wide")

# -------------------- Custom CSS for Styling --------------------
def apply_custom_css(primary_color):
    st.markdown(f"""
    <style>
        :root {{
            --primary: {primary_color};
        }}
        .stApp {{
            background-color: #f4f6f9;
        }}
        .css-1d391kg {{
            background-color: white;
            border-radius: 10px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            padding: 20px;
        }}
        .stButton>button {{
            background-color: var(--primary);
            color: white;
            border: none;
            border-radius: 5px;
            padding: 8px 20px;
            font-weight: 600;
        }}
        .stButton>button:hover {{
            background-color: {primary_color}dd;
        }}
        .sidebar .sidebar-content {{
            background-color: #2c3e50;
            color: white;
        }}
        .stMetric {{
            background-color: white;
            border-radius: 10px;
            padding: 15px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .stAlert {{
            border-radius: 5px;
        }}
    </style>
    """, unsafe_allow_html=True)

# -------------------- Initialize Supabase --------------------
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# -------------------- Utility Functions --------------------
def get_primary_color():
    settings = supabase.table("settings").select("*").eq("key", "primary_color").execute().data
    return settings[0]["value"] if settings else "#3498db"

def hash_password(password):
    # For demo, we use plain; but you can enable hashing by uncommenting below
    # return hashlib.sha256(password.encode()).hexdigest()
    return password  # plain for demo

def login_user(email, password):
    try:
        result = supabase.table("users").select("*").eq("email", email).execute()
        if not result.data:
            return None
        user = result.data[0]
        if user["password"] != password:  # plain compare
            return None
        if user["status"] != "Active":
            return None
        return user
    except Exception as e:
        st.error(f"Login error: {e}")
        return None

def log_audit(action, details):
    try:
        user = st.session_state.get("user", {}).get("email", "system")
        supabase.table("audit_log").insert({
            "user_email": user,
            "action": action,
            "details": details
        }).execute()
    except:
        pass

def get_current_month():
    return datetime.datetime.now().strftime("%Y-%m")

def calculate_recipe_cost(ingredients):
    # ingredients: list of dict [{"item":"Chawal","qty":200,"unit":"g"},...]
    total_cost = 0
    for ing in ingredients:
        # get current rate of item
        item_data = supabase.table("raw_materials").select("current_rate").eq("name", ing["item"]).execute().data
        if item_data:
            rate = item_data[0]["current_rate"]
            qty_kg = ing["qty"] / 1000 if ing["unit"] in ["g","ml"] else ing["qty"]
            total_cost += rate * qty_kg
    return total_cost

def check_stock_sufficient(ingredients, persons):
    # returns (bool, list of insufficient items)
    insufficient = []
    for ing in ingredients:
        stock = supabase.table("stock").select("quantity").eq("item", ing["item"]).execute().data
        if not stock:
            insufficient.append(ing["item"])
            continue
        available = stock[0]["quantity"]
        required = ing["qty"] * persons / 1000 if ing["unit"] in ["g","ml"] else ing["qty"] * persons
        if available < required:
            insufficient.append(ing["item"])
    return len(insufficient) == 0, insufficient

def get_low_stock_details():
    stock_data = supabase.table("stock").select("item, quantity, unit").execute().data
    raw_data = supabase.table("raw_materials").select("name, reorder_level").execute().data
    reorder_map = {r["name"]: r["reorder_level"] for r in raw_data}
    low_stock = []
    for s in stock_data:
        if s["quantity"] <= reorder_map.get(s["item"], 0):
            low_stock.append(s)
    return low_stock

# -------------------- PDF Generation --------------------
def generate_pdf_report(title, data, headers, filename):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, title, ln=1, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "B", 12)
    for i, header in enumerate(headers):
        pdf.cell(40, 10, header, 1)
    pdf.ln()
    pdf.set_font("Arial", "", 10)
    for row in data:
        for i, cell in enumerate(row):
            pdf.cell(40, 10, str(cell), 1)
        pdf.ln()
    return pdf.output(dest="S").encode("latin1")

def generate_receipt(order_id, emp_name, items, total, payment_status):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Canteen Receipt", ln=1, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"Order ID: {order_id}", ln=1)
    pdf.cell(0, 10, f"Employee: {emp_name}", ln=1)
    pdf.cell(0, 10, f"Date: {datetime.datetime.now().strftime('%d-%m-%Y %H:%M')}", ln=1)
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(80, 10, "Item", 1)
    pdf.cell(40, 10, "Qty", 1)
    pdf.cell(40, 10, "Price", 1)
    pdf.ln()
    pdf.set_font("Arial", "", 12)
    for dish, qty in items.items():
        price = supabase.table("recipes").select("selling_price").eq("dish_name", dish).execute().data[0]["selling_price"]
        pdf.cell(80, 10, dish, 1)
        pdf.cell(40, 10, str(qty), 1)
        pdf.cell(40, 10, f"Rs {price*qty}", 1)
        pdf.ln()
    pdf.set_font("Arial", "B", 12)
    pdf.cell(120, 10, "Total", 1)
    pdf.cell(40, 10, f"Rs {total}", 1)
    pdf.ln()
    pdf.cell(0, 10, f"Payment Status: {payment_status}", ln=1)
    return pdf.output(dest="S").encode("latin1")

def get_pdf_download_link(pdf_bytes, filename):
    b64 = base64.b64encode(pdf_bytes).decode()
    href = f'<a href="data:application/pdf;base64,{b64}" download="{filename}">Download PDF</a>'
    return href

# -------------------- Session Management --------------------
if "user" not in st.session_state:
    st.session_state.user = None
if "page" not in st.session_state:
    st.session_state.page = "Login"

# Apply custom CSS with primary color from settings
if st.session_state.user:
    primary_color = get_primary_color()
else:
    primary_color = "#3498db"
apply_custom_css(primary_color)

# -------------------- Authentication Pages --------------------
def login_page():
    st.title("Catering Management System")
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            if submitted:
                user = login_user(email, password)
                if user:
                    st.session_state.user = user
                    st.session_state.page = "Dashboard"
                    log_audit("Login", f"User {email} logged in")
                    st.rerun()
                else:
                    st.error("Invalid credentials or inactive account")

# -------------------- Dashboard (Role-Based) --------------------
def dashboard():
    user = st.session_state.user
    role = user["role"]

    st.sidebar.title(f"Welcome {user['email']}")
    st.sidebar.write(f"Role: {role}")

    # Navigation based on role
    menu = []

    if role in ["SuperUser", "Admin"]:
        menu.extend(["Dashboard", "Users", "Employees", "Raw Materials", "Recipes", "Purchases", "Monthly Ration", "Reports", "Settings" if role=="SuperUser" else "Audit"])
    if role == "Receiver":
        menu = ["Dashboard", "Receive Material"]
    if role == "Chef":
        menu = ["Dashboard", "Plan Menu", "Production", "Wastage", "Feedback Insights"]
    if role == "Cashier":
        menu = ["Dashboard", "Billing", "Today's Summary"]
    if role == "Employee":
        menu = ["Dashboard", "Give Feedback", "My Feedback History"]

    choice = st.sidebar.radio("Menu", menu)

    if choice == "Dashboard":
        show_dashboard()
    elif choice == "Users":
        users_management()
    elif choice == "Employees":
        employees_management()
    elif choice == "Raw Materials":
        raw_materials_management()
    elif choice == "Recipes":
        recipes_management()
    elif choice == "Purchases":
        purchases_management()
    elif choice == "Monthly Ration":
        monthly_ration_management()
    elif choice == "Reports":
        reports_page()
    elif choice == "Settings":
        settings_page()
    elif choice == "Audit":
        audit_page()
    elif choice == "Receive Material":
        receive_material_page()
    elif choice == "Plan Menu":
        plan_menu_page()
    elif choice == "Production":
        production_page()
    elif choice == "Wastage":
        wastage_page()
    elif choice == "Feedback Insights":
        feedback_insights()
    elif choice == "Billing":
        billing_page()
    elif choice == "Today's Summary":
        today_summary()
    elif choice == "Give Feedback":
        employee_feedback()
    elif choice == "My Feedback History":
        my_feedback_history()

    if st.sidebar.button("Logout"):
        log_audit("Logout", f"User {user['email']} logged out")
        st.session_state.user = None
        st.session_state.page = "Login"
        st.rerun()

# -------------------- Dashboard Stats --------------------
@st.cache_data(ttl=60)
def get_dashboard_stats():
    today = datetime.date.today().isoformat()
    sales = supabase.table("sales").select("*").eq("date", today).execute()
    total_sales = sum(item["total"] for item in sales.data) if sales.data else 0
    meals_served = len(sales.data) if sales.data else 0

    employees = supabase.table("employees").select("*").eq("status", "Active").execute()
    active_employees = len(employees.data) if employees.data else 0

    low_stock = get_low_stock_details()
    low_stock_count = len(low_stock)

    feedback = supabase.table("feedback").select("rating").execute().data
    avg_rating = sum(f["rating"] for f in feedback)/len(feedback) if feedback else 0

    return {
        "today_sales": total_sales,
        "meals_served": meals_served,
        "active_employees": active_employees,
        "low_stock": low_stock_count,
        "avg_rating": avg_rating,
        "low_stock_details": low_stock
    }

def show_dashboard():
    st.header("Dashboard")
    stats = get_dashboard_stats()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Today's Sales", f"Rs {stats['today_sales']}")
    col2.metric("Meals Served", stats['meals_served'])
    col3.metric("Active Employees", stats['active_employees'])
    col4.metric("Low Stock Items", stats['low_stock'])
    st.metric("Average Rating", f"{stats['avg_rating']:.1f} / 5")

    # Low stock details
    if stats['low_stock_details']:
        st.subheader("⚠️ Low Stock Alerts")
        for item in stats['low_stock_details']:
            st.warning(f"{item['item']} only {item['quantity']} {item['unit']} left (Reorder level: {supabase.table('raw_materials').select('reorder_level').eq('name', item['item']).execute().data[0]['reorder_level']})")

# -------------------- User Management --------------------
def users_management():
    st.header("User Management")
    if st.button("Add User"):
        with st.expander("New User", expanded=True):
            with st.form("add_user"):
                email = st.text_input("Email")
                role = st.selectbox("Role", ["SuperUser","Admin","Receiver","Chef","Cashier","Employee"])
                password = st.text_input("Password", type="password")
                status = st.selectbox("Status", ["Active","Inactive"])
                submitted = st.form_submit_button("Save")
                if submitted:
                    try:
                        supabase.table("users").insert({
                            "email": email,
                            "role": role,
                            "password": password,  # plain
                            "status": status
                        }).execute()
                        st.success("User added")
                        log_audit("Add User", email)
                    except Exception as e:
                        st.error(str(e))

    users = supabase.table("users").select("*").execute().data
    df = pd.DataFrame(users)
    st.dataframe(df[["email","role","status"]])

# -------------------- Employees Management --------------------
def employees_management():
    st.header("Employees Management")
    if st.button("Add Employee"):
        with st.form("add_employee"):
            emp_id = st.text_input("Employee ID")
            name = st.text_input("Name")
            department = st.text_input("Department")
            designation = st.text_input("Designation")
            status = st.selectbox("Status", ["Active","Inactive"])
            dietary = st.selectbox("Dietary Preference", ["Regular","Vegetarian","Jain","Gluten-Free"])
            submitted = st.form_submit_button("Save")
            if submitted:
                try:
                    supabase.table("employees").insert({
                        "emp_id": emp_id,
                        "name": name,
                        "department": department,
                        "designation": designation,
                        "status": status,
                        "dietary_pref": dietary
                    }).execute()
                    st.success("Employee added")
                    log_audit("Add Employee", emp_id)
                except Exception as e:
                    st.error(str(e))

    employees = supabase.table("employees").select("*").execute().data
    df = pd.DataFrame(employees)
    # Add search
    search = st.text_input("Search by name or ID")
    if search:
        df = df[df['name'].str.contains(search, case=False) | df['emp_id'].str.contains(search, case=False)]
    st.dataframe(df)

# -------------------- Raw Materials --------------------
def raw_materials_management():
    st.header("Raw Materials")
    if st.button("Add Item"):
        with st.form("add_raw"):
            name = st.text_input("Item Name")
            unit = st.selectbox("Unit", ["KG","Liter","Pieces"])
            rate = st.number_input("Current Rate (Rs)", min_value=0.0, step=0.01)
            reorder = st.number_input("Reorder Level", min_value=0.0, step=0.01)
            submitted = st.form_submit_button("Save")
            if submitted:
                try:
                    supabase.table("raw_materials").insert({
                        "name": name,
                        "unit": unit,
                        "current_rate": rate,
                        "reorder_level": reorder
                    }).execute()
                    # Also init stock if not exists
                    stock = supabase.table("stock").select("*").eq("item", name).execute()
                    if not stock.data:
                        supabase.table("stock").insert({
                            "item": name,
                            "quantity": 0,
                            "unit": unit
                        }).execute()
                    st.success("Item added")
                except Exception as e:
                    st.error(str(e))

    items = supabase.table("raw_materials").select("*").execute().data
    df = pd.DataFrame(items)
    st.dataframe(df)

# -------------------- Recipes --------------------
def recipes_management():
    st.header("Recipes")
    if st.button("Add Recipe"):
        with st.form("add_recipe"):
            dish = st.text_input("Dish Name")
            price = st.number_input("Selling Price", min_value=0.0)
            st.write("Ingredients")
            ingredients = []
            num = st.number_input("Number of ingredients", min_value=1, step=1, value=1)
            for i in range(int(num)):
                col1, col2, col3 = st.columns(3)
                with col1:
                    item = st.text_input(f"Item {i+1}", key=f"item_{i}")
                with col2:
                    qty = st.number_input(f"Qty {i+1}", min_value=0.0, step=0.1, key=f"qty_{i}")
                with col3:
                    unit = st.selectbox(f"Unit {i+1}", ["g","ml","pcs"], key=f"unit_{i}")
                if item and qty:
                    ingredients.append({"item": item, "qty": qty, "unit": unit})
            submitted = st.form_submit_button("Save")
            if submitted:
                try:
                    # Calculate cost automatically
                    cost = calculate_recipe_cost(ingredients)
                    supabase.table("recipes").insert({
                        "dish_name": dish,
                        "ingredients": json.dumps(ingredients),
                        "selling_price": price,
                        "cost_per_plate": cost
                    }).execute()
                    st.success("Recipe added")
                except Exception as e:
                    st.error(str(e))

    recipes = supabase.table("recipes").select("*").execute().data
    df = pd.DataFrame(recipes)
    st.dataframe(df)

# -------------------- Purchases --------------------
def purchases_management():
    st.header("Purchases")
    if st.button("Add Purchase"):
        with st.form("add_purchase"):
            date = st.date_input("Date", datetime.date.today())
            item = st.text_input("Item")
            qty = st.number_input("Quantity", min_value=0.0, step=0.01)
            unit = st.selectbox("Unit", ["KG","Liter","Pieces"])
            rate = st.number_input("Rate (Rs)", min_value=0.0, step=0.01)
            supplier = st.text_input("Supplier")
            submitted = st.form_submit_button("Save")
            if submitted:
                try:
                    total = qty * rate
                    supabase.table("purchases").insert({
                        "date": date.isoformat(),
                        "item": item,
                        "quantity": qty,
                        "unit": unit,
                        "rate": rate,
                        "supplier": supplier
                    }).execute()
                    # Update stock
                    stock = supabase.table("stock").select("*").eq("item", item).execute()
                    if stock.data:
                        current = stock.data[0]["quantity"]
                        supabase.table("stock").update({
                            "quantity": current + qty,
                            "last_updated": datetime.datetime.now().isoformat()
                        }).eq("item", item).execute()
                    else:
                        supabase.table("stock").insert({
                            "item": item,
                            "quantity": qty,
                            "unit": unit
                        }).execute()
                    # Update raw material rate
                    supabase.table("raw_materials").update({"current_rate": rate}).eq("name", item).execute()
                    st.success("Purchase added")
                    log_audit("Purchase", f"{item} {qty}{unit}")
                except Exception as e:
                    st.error(str(e))

    purchases = supabase.table("purchases").select("*").execute().data
    df = pd.DataFrame(purchases)
    st.dataframe(df)

# -------------------- Monthly Ration --------------------
def monthly_ration_management():
    st.header("Monthly Ration Setup")
    month = st.text_input("Month (YYYY-MM)", get_current_month())
    if st.button("Add Ration Entry"):
        with st.form("add_ration"):
            item = st.text_input("Item")
            target = st.number_input("Target Quantity", min_value=0.0, step=0.01)
            unit = st.selectbox("Unit", ["KG","Liter","Pieces"])
            submitted = st.form_submit_button("Save")
            if submitted:
                try:
                    supabase.table("monthly_ration").insert({
                        "month": month,
                        "item": item,
                        "target_qty": target,
                        "unit": unit
                    }).execute()
                    st.success("Ration entry added")
                except Exception as e:
                    st.error(str(e))

    data = supabase.table("monthly_ration").select("*").eq("month", month).execute().data
    if data:
        df = pd.DataFrame(data)
        st.dataframe(df[["item","target_qty","unit"]])

# -------------------- Receiver --------------------
def receive_material_page():
    st.header("Receive Material")
    with st.form("receive_form"):
        date = st.date_input("Date", datetime.date.today())
        item = st.text_input("Item")
        # Fetch expected from monthly ration
        month = get_current_month()
        ration = supabase.table("monthly_ration").select("target_qty").eq("month", month).eq("item", item).execute().data
        expected = ration[0]["target_qty"] if ration else 0.0
        st.write(f"Expected this month: {expected}")
        expected_input = st.number_input("Expected Quantity", value=expected, min_value=0.0, step=0.01)
        received = st.number_input("Received Quantity", min_value=0.0, step=0.01)
        batch = st.text_input("Batch No. (optional)")
        submitted = st.form_submit_button("Save")
        if submitted:
            shortage = received - expected_input
            try:
                supabase.table("receiving").insert({
                    "date": date.isoformat(),
                    "item": item,
                    "expected_qty": expected_input,
                    "received_qty": received,
                    "shortage": shortage,
                    "received_by": st.session_state.user["email"],
                    "batch_no": batch
                }).execute()
                # Update stock
                stock = supabase.table("stock").select("*").eq("item", item).execute()
                if stock.data:
                    current = stock.data[0]["quantity"]
                    supabase.table("stock").update({
                        "quantity": current + received,
                        "last_updated": datetime.datetime.now().isoformat()
                    }).eq("item", item).execute()
                else:
                    supabase.table("stock").insert({
                        "item": item,
                        "quantity": received,
                        "unit": "KG"
                    }).execute()
                st.success("Receiving recorded")
                log_audit("Receive", f"{item} {received}")
            except Exception as e:
                st.error(str(e))

    history = supabase.table("receiving").select("*").limit(10).execute().data
    st.subheader("Recent Receivings")
    st.dataframe(pd.DataFrame(history))

# -------------------- Chef Pages --------------------
def plan_menu_page():
    st.header("Plan Menu")
    # Fetch recipes
    recipes = supabase.table("recipes").select("*").execute().data
    if not recipes:
        st.warning("No recipes found")
        return

    # Display recipes with person input
    production_data = []
    for r in recipes:
        persons = st.number_input(f"Persons for {r['dish_name']}", min_value=0, step=1, key=r['id'])
        if persons > 0:
            production_data.append({"dish": r['dish_name'], "persons": persons})

    if st.button("Check Stock & Confirm"):
        all_sufficient = True
        insufficient_items = []
        for item in production_data:
            recipe = next(r for r in recipes if r['dish_name'] == item['dish'])
            ingredients = json.loads(recipe['ingredients'])
            sufficient, insufficient = check_stock_sufficient(ingredients, item['persons'])
            if not sufficient:
                all_sufficient = False
                insufficient_items.extend(insufficient)
        if all_sufficient:
            # Proceed to deduct and save
            for item in production_data:
                recipe = next(r for r in recipes if r['dish_name'] == item['dish'])
                ingredients = json.loads(recipe['ingredients'])
                # Deduct stock
                for ing in ingredients:
                    stock = supabase.table("stock").select("quantity").eq("item", ing['item']).execute()
                    if stock.data:
                        current = stock.data[0]["quantity"]
                        qty_needed = ing['qty'] * item['persons'] / 1000 if ing['unit'] in ['g','ml'] else ing['qty'] * item['persons']
                        new_qty = current - qty_needed
                        supabase.table("stock").update({"quantity": new_qty}).eq("item", ing['item']).execute()
                # Record production
                supabase.table("production").insert({
                    "date": datetime.date.today().isoformat(),
                    "dish": item['dish'],
                    "persons": item['persons'],
                    "raw_material_used": json.dumps(ingredients),
                    "planned_by": st.session_state.user['email']
                }).execute()
            st.success("Production planned and stock deducted")
            log_audit("Production", str(production_data))
        else:
            st.error(f"Insufficient stock for items: {', '.join(set(insufficient_items))}")

def production_page():
    st.header("Today's Production")
    today = datetime.date.today().isoformat()
    prods = supabase.table("production").select("*").eq("date", today).execute().data
    st.dataframe(pd.DataFrame(prods))

def wastage_page():
    st.header("Wastage Entry")
    with st.form("wastage_form"):
        date = st.date_input("Date", datetime.date.today())
        item = st.text_input("Item/Dish")
        qty = st.number_input("Quantity", min_value=0.0, step=0.01)
        unit = st.selectbox("Unit", ["KG","Liter","Pieces","Plates"])
        reason = st.selectbox("Reason", ["Extra Bacha","Jal Gaya","Kharab","Gira","Other"])
        remarks = st.text_input("Remarks")
        submitted = st.form_submit_button("Save")
        if submitted:
            supabase.table("wastage").insert({
                "date": date.isoformat(),
                "item": item,
                "quantity": qty,
                "unit": unit,
                "reason": reason,
                "remarks": remarks
            }).execute()
            st.success("Wastage recorded")
            log_audit("Wastage", f"{item} {qty}{unit}")

def feedback_insights():
    st.header("Feedback Insights")
    feedback = supabase.table("feedback").select("*").execute().data
    if not feedback:
        st.info("No feedback yet")
        return
    df = pd.DataFrame(feedback)
    avg_rating = df.groupby("dish")["rating"].mean().reset_index()
    st.subheader("Average Ratings")
    st.bar_chart(avg_rating.set_index("dish"))
    # Complaints
    complaints = df[df["reason"] != ""]["reason"].value_counts()
    st.subheader("Common Complaints")
    st.write(complaints)

# -------------------- Cashier Pages --------------------
def billing_page():
    st.header("Cashier Billing")
    emp_id = st.text_input("Employee ID")
    if emp_id:
        emp = supabase.table("employees").select("*").eq("emp_id", emp_id).execute().data
        if emp:
            st.success(f"Employee: {emp[0]['name']} ({emp[0]['department']})")
            # Fetch outstanding
            ledger = supabase.table("ledger").select("balance").eq("emp_id", emp_id).order("date", desc=True).limit(1).execute().data
            outstanding = ledger[0]["balance"] if ledger else 0
            st.info(f"Outstanding: Rs {outstanding}")
        else:
            st.error("Employee not found")

    # Get today's menu
    today = datetime.date.today().isoformat()
    productions = supabase.table("production").select("*").eq("date", today).execute().data
    if productions:
        menu = [p["dish"] for p in productions]
        st.subheader("Today's Menu")
        selected_items = {}
        for dish in menu:
            col1, col2 = st.columns([2,1])
            with col1:
                qty = st.number_input(f"Qty for {dish}", min_value=0, step=1, key=dish)
            if qty:
                selected_items[dish] = qty

        total = 0
        for dish, qty in selected_items.items():
            price = supabase.table("recipes").select("selling_price").eq("dish_name", dish).execute().data[0]["selling_price"]
            total += price * qty

        st.metric("Total", f"Rs {total}")

        payment = st.radio("Payment Status", ["PAID", "UNPAID"])
        if st.button("Save Bill"):
            if not emp_id:
                st.error("Employee ID required")
                return
            order_id = f"ORD{datetime.datetime.now().strftime('%y%m%d%H%M%S')}"
            # Save sale
            supabase.table("sales").insert({
                "date": today,
                "order_id": order_id,
                "emp_id": emp_id,
                "items": json.dumps(selected_items),
                "total": total,
                "payment_status": payment,
                "payment_mode": "Cash",
                "cashier": st.session_state.user["email"]
            }).execute()
            if payment == "UNPAID":
                # Update ledger
                new_balance = outstanding + total
                supabase.table("ledger").insert({
                    "emp_id": emp_id,
                    "date": today,
                    "debit": total,
                    "balance": new_balance,
                    "remarks": "Meal charges"
                }).execute()
            st.success("Bill saved")
            log_audit("Sale", order_id)

            # Generate receipt PDF
            pdf_bytes = generate_receipt(order_id, emp[0]['name'], selected_items, total, payment)
            st.markdown(get_pdf_download_link(pdf_bytes, f"receipt_{order_id}.pdf"), unsafe_allow_html=True)
    else:
        st.warning("No production today")

def today_summary():
    st.header("Today's Summary")
    today = datetime.date.today().isoformat()
    sales = supabase.table("sales").select("*").eq("date", today).execute().data
    if sales:
        df = pd.DataFrame(sales)
        total = df["total"].sum()
        paid = df[df["payment_status"]=="PAID"]["total"].sum()
        unpaid = df[df["payment_status"]=="UNPAID"]["total"].sum()
        col1, col2, col3 = st.columns(3)
        col1.metric("Total", f"Rs {total}")
        col2.metric("Paid", f"Rs {paid}")
        col3.metric("Unpaid", f"Rs {unpaid}")
        st.dataframe(df[["order_id","emp_id","total","payment_status"]])
    else:
        st.info("No sales today")

# -------------------- Employee Feedback --------------------
def employee_feedback():
    st.header("Give Feedback")
    emp_id = st.text_input("Your Employee ID")
    if emp_id:
        # Get recent meals
        meals = supabase.table("sales").select("*").eq("emp_id", emp_id).order("date", desc=True).limit(10).execute().data
        if meals:
            options = {f"{m['date']} - {list(json.loads(m['items']).keys())[0]}": m for m in meals}
            selected = st.selectbox("Select meal", list(options.keys()))
            meal = options[selected]
            dish = list(json.loads(meal['items']).keys())[0]
            with st.form("feedback_form"):
                rating = st.slider("Rating", 1, 5, 5)
                ate = st.select_slider("How much ate?", options=[0,25,50,75,100], value=100)
                reason = st.text_input("Reason (if not finished)")
                comments = st.text_area("Comments")
                submitted = st.form_submit_button("Submit")
                if submitted:
                    supabase.table("feedback").insert({
                        "date": datetime.date.today().isoformat(),
                        "emp_id": emp_id,
                        "dish": dish,
                        "rating": rating,
                        "ate_percent": ate,
                        "reason": reason,
                        "comments": comments
                    }).execute()
                    st.success("Thank you for your feedback!")

def my_feedback_history():
    st.header("My Feedback History")
    emp_id = st.text_input("Employee ID")
    if emp_id:
        feedback = supabase.table("feedback").select("*").eq("emp_id", emp_id).order("date", desc=True).execute().data
        if feedback:
            df = pd.DataFrame(feedback)
            st.dataframe(df[["date","dish","rating","ate_percent","reason","comments"]])
        else:
            st.info("No feedback yet")

# -------------------- Reports --------------------
def reports_page():
    st.header("Reports")
    report_type = st.selectbox("Report Type", ["Sales", "Stock", "Wastage", "Feedback", "Profit & Loss", "Ledger"])
    start = st.date_input("Start Date")
    end = st.date_input("End Date")
    if st.button("Generate"):
        data = []
        headers = []
        if report_type == "Sales":
            data_raw = supabase.table("sales").select("*").gte("date", start.isoformat()).lte("date", end.isoformat()).execute().data
            if data_raw:
                df = pd.DataFrame(data_raw)
                headers = ["Date","Order ID","Employee","Total","Status"]
                data = df[["date","order_id","emp_id","total","payment_status"]].values.tolist()
        elif report_type == "Stock":
            data_raw = supabase.table("stock").select("*").execute().data
            if data_raw:
                df = pd.DataFrame(data_raw)
                headers = ["Item","Quantity","Unit","Last Updated"]
                data = df[["item","quantity","unit","last_updated"]].values.tolist()
        elif report_type == "Wastage":
            data_raw = supabase.table("wastage").select("*").gte("date", start.isoformat()).lte("date", end.isoformat()).execute().data
            if data_raw:
                df = pd.DataFrame(data_raw)
                headers = ["Date","Item","Quantity","Unit","Reason"]
                data = df[["date","item","quantity","unit","reason"]].values.tolist()
        elif report_type == "Feedback":
            data_raw = supabase.table("feedback").select("*").gte("date", start.isoformat()).lte("date", end.isoformat()).execute().data
            if data_raw:
                df = pd.DataFrame(data_raw)
                headers = ["Date","Employee","Dish","Rating","Ate%","Reason"]
                data = df[["date","emp_id","dish","rating","ate_percent","reason"]].values.tolist()
        elif report_type == "Profit & Loss":
            sales = supabase.table("sales").select("total").gte("date", start.isoformat()).lte("date", end.isoformat()).execute().data
            purchases = supabase.table("purchases").select("total").gte("date", start.isoformat()).lte("date", end.isoformat()).execute().data
            revenue = sum(s["total"] for s in sales)
            cost = sum(p["total"] for p in purchases)
            profit = revenue - cost
            st.metric("Revenue", f"Rs {revenue}")
            st.metric("Cost", f"Rs {cost}")
            st.metric("Profit", f"Rs {profit}")
            data = [[revenue, cost, profit]]
            headers = ["Revenue","Cost","Profit"]
        elif report_type == "Ledger":
            data_raw = supabase.table("ledger").select("*").execute().data
            if data_raw:
                df = pd.DataFrame(data_raw)
                headers = ["Employee","Date","Debit","Credit","Balance"]
                data = df[["emp_id","date","debit","credit","balance"]].values.tolist()

        if data:
            st.dataframe(pd.DataFrame(data, columns=headers))
            # PDF download
            pdf_bytes = generate_pdf_report(f"{report_type} Report", data, headers, f"{report_type}.pdf")
            st.markdown(get_pdf_download_link(pdf_bytes, f"{report_type}_report.pdf"), unsafe_allow_html=True)

# -------------------- Settings (SuperUser) --------------------
def settings_page():
    st.header("System Settings")
    settings = supabase.table("settings").select("*").execute().data
    settings_dict = {s["key"]: s["value"] for s in settings}
    with st.form("settings_form"):
        app_name = st.text_input("App Name", settings_dict.get("app_name", ""))
        company = st.text_input("Company Name", settings_dict.get("company_name", ""))
        color = st.color_picker("Primary Color", settings_dict.get("primary_color", "#3498db"))
        date_fmt = st.selectbox("Date Format", ["DD-MM-YYYY", "MM-DD-YYYY", "YYYY-MM-DD"], index=0)
        submitted = st.form_submit_button("Save")
        if submitted:
            for key, val in [("app_name", app_name), ("company_name", company), ("primary_color", color), ("date_format", date_fmt)]:
                supabase.table("settings").upsert({"key": key, "value": val}).execute()
            st.success("Settings saved")
            log_audit("Settings", "Updated")
            st.rerun()

# -------------------- Audit Log --------------------
def audit_page():
    st.header("Audit Log")
    logs = supabase.table("audit_log").select("*").order("timestamp", desc=True).limit(100).execute().data
    st.dataframe(pd.DataFrame(logs))

# -------------------- Main App --------------------
def main():
    if st.session_state.user is None:
        login_page()
    else:
        dashboard()

if __name__ == "__main__":
    main()
