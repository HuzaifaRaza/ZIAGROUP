import streamlit as st
import pandas as pd
import datetime
import json
import time
from supabase import create_client
import plotly.express as px
from fpdf import FPDF
import base64

# -------------------- Page Config --------------------
st.set_page_config(page_title="Catering System", layout="wide", initial_sidebar_state="expanded")

# -------------------- Initialize Supabase --------------------
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# -------------------- Utility Functions --------------------
def get_settings():
    try:
        settings = supabase.table("settings").select("*").execute().data
        return {s["key"]: s["value"] for s in settings}
    except:
        return {}

def get_primary_color():
    return get_settings().get("primary_color", "#3498db")

def get_logo_url():
    logo = get_settings().get("logo_url", "")
    if logo:
        try:
            signed = supabase.storage.from_("logos").create_signed_url(logo, 3600)
            return signed.get("signedURL")
        except:
            return None
    return None

def login_user(email, password):
    try:
        result = supabase.table("users").select("*").eq("email", email).execute()
        if not result.data:
            return None
        user = result.data[0]
        if user["password"] != password:
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
    total_cost = 0
    for ing in ingredients:
        item_data = supabase.table("raw_materials").select("current_rate").eq("name", ing["item"]).execute().data
        if item_data:
            rate = item_data[0]["current_rate"]
            qty_kg = ing["qty"] / 1000 if ing["unit"] in ["g","ml"] else ing["qty"]
            total_cost += rate * qty_kg
    return total_cost

def check_stock_sufficient(ingredients, persons):
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

def get_employee_points(emp_id):
    feedback = supabase.table("feedback").select("points").eq("emp_id", emp_id).execute().data
    return sum(f["points"] for f in feedback) if feedback else 0

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
    return f'<a href="data:application/pdf;base64,{b64}" download="{filename}">📥 Download PDF</a>'

def get_csv_download_link(df, filename):
    csv = df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    return f'<a href="data:file/csv;base64,{b64}" download="{filename}">📥 Download CSV</a>'

# -------------------- Custom CSS for Modern UI --------------------
def apply_custom_css(primary_color, logo_url=None):
    st.markdown(f"""
    <style>
        :root {{
            --primary: {primary_color};
            --primary-light: {primary_color}dd;
            --sidebar-bg: #1e293b;
            --card-bg: #ffffff;
            --text-dark: #0f172a;
            --text-muted: #64748b;
        }}
        * {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }}
        .stApp {{
            background-color: #f1f5f9;
        }}
        .main .block-container {{
            padding: 2rem 2rem;
        }}
        /* Cards */
        .stMetric, div[data-testid="stExpander"], .stDataFrame, .stForm {{
            background-color: var(--card-bg);
            border-radius: 1rem;
            padding: 1.5rem;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
            border: 1px solid #e2e8f0;
            transition: all 0.2s;
        }}
        .stMetric:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1);
        }}
        /* Buttons */
        .stButton>button {{
            background-color: var(--primary);
            color: white;
            border: none;
            border-radius: 0.5rem;
            padding: 0.5rem 1rem;
            font-weight: 500;
            transition: all 0.2s;
        }}
        .stButton>button:hover {{
            background-color: var(--primary-light);
            transform: translateY(-1px);
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        }}
        .stButton>button:disabled {{
            background-color: #cbd5e1;
            cursor: not-allowed;
        }}
        /* Sidebar */
        .css-1d391kg {{
            background-color: var(--sidebar-bg);
            color: #f1f5f9;
        }}
        .sidebar .stRadio > label {{
            color: #cbd5e1;
            font-size: 0.95rem;
            padding: 0.5rem 1rem;
            border-radius: 0.5rem;
            margin: 0.25rem 0;
            transition: all 0.2s;
        }}
        .sidebar .stRadio > label:hover {{
            background-color: #334155;
            color: white;
        }}
        /* Headers */
        h1, h2, h3 {{
            color: var(--text-dark);
            font-weight: 600;
        }}
        /* Inputs */
        .stTextInput>div>input, .stNumberInput>div>input, .stSelectbox>div>select {{
            border-radius: 0.5rem;
            border: 1px solid #e2e8f0;
            padding: 0.5rem;
            background-color: white;
        }}
        .stTextInput>div>input:focus, .stNumberInput>div>input:focus, .stSelectbox>div>select:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 3px {primary_color}33;
        }}
        /* DataFrames */
        .stDataFrame {{
            overflow: hidden;
        }}
        .stDataFrame thead tr th {{
            background-color: #f8fafc;
            font-weight: 600;
            color: var(--text-dark);
        }}
        .stDataFrame tbody tr:nth-child(even) {{
            background-color: #f8fafc;
        }}
        /* Action buttons in tables */
        .action-button {{
            display: inline-block;
            margin: 0 2px;
        }}
        /* Alerts */
        .stAlert {{
            border-radius: 0.5rem;
            border-left-width: 4px;
        }}
        /* Expander */
        .streamlit-expanderHeader {{
            font-weight: 600;
            color: var(--text-dark);
        }}
    </style>
    """, unsafe_allow_html=True)

# -------------------- Session State Init --------------------
if "user" not in st.session_state:
    st.session_state.user = None
if "edit_id" not in st.session_state:
    st.session_state.edit_id = None
if "edit_table" not in st.session_state:
    st.session_state.edit_table = None
if "ingredients" not in st.session_state:
    st.session_state.ingredients = [{"item": "", "qty": 0.0, "unit": "g"}]

# -------------------- Login Page --------------------
def login_page():
    st.markdown("<h1 style='text-align: center; margin-bottom: 2rem;'>Catering Management System</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        with st.form("login_form"):
            if logo_url := get_logo_url():
                st.markdown(f'<div style="text-align: center; margin-bottom: 2rem;"><img src="{logo_url}" style="max-height: 80px;"></div>', unsafe_allow_html=True)
            email = st.text_input("Email", placeholder="super@catering.com")
            password = st.text_input("Password", type="password", placeholder="••••••")
            submitted = st.form_submit_button("Login", use_container_width=True)
            if submitted:
                user = login_user(email, password)
                if user:
                    st.session_state.user = user
                    log_audit("Login", f"User {email} logged in")
                    st.rerun()
                else:
                    st.error("Invalid credentials or inactive account")

# -------------------- Dashboard (Role-Based) --------------------
def dashboard():
    user = st.session_state.user
    role = user["role"]
    primary_color = get_primary_color()
    apply_custom_css(primary_color, get_logo_url())

    with st.sidebar:
        if logo_url := get_logo_url():
            st.markdown(f'<div style="text-align: center; margin-bottom: 1rem;"><img src="{logo_url}" style="max-height: 60px;"></div>', unsafe_allow_html=True)
        st.markdown(f"### Welcome, {user['email']}")
        st.caption(f"Role: {role}")

        menu_options = {
            "SuperUser": ["Dashboard", "Users", "Employees", "Raw Materials", "Recipes", "Purchases", "Monthly Ration", "Reports", "Settings", "Audit"],
            "Admin": ["Dashboard", "Users", "Employees", "Raw Materials", "Recipes", "Purchases", "Monthly Ration", "Reports", "Audit"],
            "Receiver": ["Dashboard", "Receive Material"],
            "Chef": ["Dashboard", "Plan Menu", "Production", "Wastage", "Feedback Insights"],
            "Cashier": ["Dashboard", "Billing", "Today's Summary"],
            "Employee": ["Dashboard", "Give Feedback", "My Feedback History", "My Points"]
        }
        menu = menu_options.get(role, ["Dashboard"])
        choice = st.radio("", menu, key="nav")

        if st.button("Logout", use_container_width=True):
            log_audit("Logout", f"User {user['email']} logged out")
            st.session_state.user = None
            st.rerun()

    # Page routing
    pages = {
        "Dashboard": show_dashboard,
        "Users": users_management,
        "Employees": employees_management,
        "Raw Materials": raw_materials_management,
        "Recipes": recipes_management,
        "Purchases": purchases_management,
        "Monthly Ration": monthly_ration_management,
        "Reports": reports_page,
        "Settings": settings_page,
        "Audit": audit_page,
        "Receive Material": receive_material_page,
        "Plan Menu": plan_menu_page,
        "Production": production_page,
        "Wastage": wastage_page,
        "Feedback Insights": feedback_insights,
        "Billing": billing_page,
        "Today's Summary": today_summary,
        "Give Feedback": employee_feedback,
        "My Feedback History": my_feedback_history,
        "My Points": my_points,
    }
    pages[choice]()

# -------------------- Dashboard Stats (Cached) --------------------
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
    cols = st.columns(4)
    cols[0].metric("Today's Sales", f"Rs {stats['today_sales']:,.0f}")
    cols[1].metric("Meals Served", stats['meals_served'])
    cols[2].metric("Active Employees", stats['active_employees'])
    cols[3].metric("Low Stock Items", stats['low_stock'])
    st.metric("Average Rating", f"{stats['avg_rating']:.1f} / 5")

    if stats['low_stock_details']:
        st.subheader("⚠️ Low Stock Alerts")
        for item in stats['low_stock_details']:
            reorder = supabase.table("raw_materials").select("reorder_level").eq("name", item["item"]).execute().data
            level = reorder[0]["reorder_level"] if reorder else 0
            st.warning(f"{item['item']} only {item['quantity']} {item['unit']} left (Reorder level: {level})")

# -------------------- Generic CRUD Helpers --------------------
def render_crud_table(table_name, columns, display_columns, form_fields, fetch_func, insert_func, update_func, delete_func, key_field="id"):
    """
    Generic function to display a table with Add, Edit, Delete buttons.
    - table_name: for session state keys
    - columns: list of all columns in the table (for fetching)
    - display_columns: list of columns to show in dataframe
    - form_fields: list of dicts for form inputs [{"name":col, "type": "text|number|select", "options":[...]}]
    - fetch_func: function that returns list of rows
    - insert_func: function(row_data) -> bool
    - update_func: function(id, row_data) -> bool
    - delete_func: function(id) -> bool
    - key_field: primary key column name
    """
    st.subheader(table_name.replace("_", " ").title())
    
    # Add button
    if st.button(f"➕ Add {table_name[:-1].title() if table_name.endswith('s') else table_name.title()}"):
        st.session_state[f"add_{table_name}"] = True
    
    # Add form
    if st.session_state.get(f"add_{table_name}", False):
        with st.form(f"form_add_{table_name}"):
            row_data = {}
            for field in form_fields:
                if field["type"] == "text":
                    row_data[field["name"]] = st.text_input(field["label"])
                elif field["type"] == "number":
                    row_data[field["name"]] = st.number_input(field["label"], value=0.0, step=0.01)
                elif field["type"] == "select":
                    row_data[field["name"]] = st.selectbox(field["label"], field["options"])
                elif field["type"] == "date":
                    row_data[field["name"]] = st.date_input(field["label"], datetime.date.today()).isoformat()
            if st.form_submit_button("Save"):
                if insert_func(row_data):
                    st.success("Added successfully")
                    st.session_state[f"add_{table_name}"] = False
                    st.rerun()
                else:
                    st.error("Failed to add")
    
    # Fetch data
    data = fetch_func()
    if not data:
        st.info("No records found")
        return
    
    df = pd.DataFrame(data)
    # Show dataframe with action buttons
    col_order = display_columns + ["Actions"]
    df_display = df[display_columns].copy()
    
    # Create action buttons
    for idx, row in df.iterrows():
        row_id = row[key_field]
        col1, col2 = st.columns([1,1])
        with col1:
            if st.button(f"✏️ Edit", key=f"edit_{table_name}_{row_id}"):
                st.session_state.edit_table = table_name
                st.session_state.edit_id = row_id
                st.session_state.edit_data = row.to_dict()
        with col2:
            if st.button(f"🗑️ Delete", key=f"delete_{table_name}_{row_id}"):
                if delete_func(row_id):
                    st.success("Deleted")
                    st.rerun()
                else:
                    st.error("Delete failed")
        st.write("---")
    
    # Display dataframe (without actions)
    st.dataframe(df_display, use_container_width=True)
    st.markdown(get_csv_download_link(df_display, f"{table_name}.csv"), unsafe_allow_html=True)

# -------------------- Users Management --------------------
def users_management():
    st.header("User Management")
    
    # Fetch function
    def fetch_users():
        return supabase.table("users").select("*").execute().data
    
    # Insert function
    def insert_user(data):
        try:
            supabase.table("users").insert(data).execute()
            log_audit("Add User", data["email"])
            return True
        except:
            return False
    
    # Update function
    def update_user(id, data):
        try:
            supabase.table("users").update(data).eq("id", id).execute()
            log_audit("Update User", data["email"])
            return True
        except:
            return False
    
    # Delete function
    def delete_user(id):
        try:
            supabase.table("users").delete().eq("id", id).execute()
            log_audit("Delete User", str(id))
            return True
        except:
            return False
    
    form_fields = [
        {"name": "email", "label": "Email", "type": "text"},
        {"name": "role", "label": "Role", "type": "select", "options": ["SuperUser","Admin","Receiver","Chef","Cashier","Employee"]},
        {"name": "password", "label": "Password", "type": "text"},
        {"name": "status", "label": "Status", "type": "select", "options": ["Active","Inactive"]}
    ]
    
    render_crud_table("users", 
                      columns=["id","email","role","password","status","created_at"],
                      display_columns=["email","role","status"],
                      form_fields=form_fields,
                      fetch_func=fetch_users,
                      insert_func=insert_user,
                      update_func=update_user,
                      delete_func=delete_user)

# -------------------- Employees Management --------------------
def employees_management():
    st.header("Employees Management")
    
    def fetch_employees():
        return supabase.table("employees").select("*").execute().data
    
    def insert_employee(data):
        try:
            supabase.table("employees").insert(data).execute()
            log_audit("Add Employee", data["emp_id"])
            return True
        except:
            return False
    
    def update_employee(id, data):
        try:
            supabase.table("employees").update(data).eq("emp_id", id).execute()
            log_audit("Update Employee", id)
            return True
        except:
            return False
    
    def delete_employee(id):
        try:
            supabase.table("employees").delete().eq("emp_id", id).execute()
            log_audit("Delete Employee", id)
            return True
        except:
            return False
    
    form_fields = [
        {"name": "emp_id", "label": "Employee ID", "type": "text"},
        {"name": "name", "label": "Name", "type": "text"},
        {"name": "department", "label": "Department", "type": "text"},
        {"name": "designation", "label": "Designation", "type": "text"},
        {"name": "status", "label": "Status", "type": "select", "options": ["Active","Inactive"]},
        {"name": "dietary_pref", "label": "Dietary Preference", "type": "select", "options": ["Regular","Vegetarian","Jain","Gluten-Free"]}
    ]
    
    render_crud_table("employees",
                      columns=["emp_id","name","department","designation","status","dietary_pref"],
                      display_columns=["emp_id","name","department","designation","status","dietary_pref"],
                      form_fields=form_fields,
                      fetch_func=fetch_employees,
                      insert_func=insert_employee,
                      update_func=update_employee,
                      delete_func=delete_employee,
                      key_field="emp_id")

# -------------------- Raw Materials Management --------------------
def raw_materials_management():
    st.header("Raw Materials")
    
    def fetch_raw():
        return supabase.table("raw_materials").select("*").execute().data
    
    def insert_raw(data):
        try:
            supabase.table("raw_materials").insert(data).execute()
            # Also init stock if not exists
            stock = supabase.table("stock").select("*").eq("item", data["name"]).execute()
            if not stock.data:
                supabase.table("stock").insert({
                    "item": data["name"],
                    "quantity": 0,
                    "unit": data["unit"]
                }).execute()
            log_audit("Add Raw Material", data["name"])
            return True
        except:
            return False
    
    def update_raw(id, data):
        try:
            supabase.table("raw_materials").update(data).eq("id", id).execute()
            # Update stock unit if changed
            supabase.table("stock").update({"unit": data["unit"]}).eq("item", data["name"]).execute()
            log_audit("Update Raw Material", data["name"])
            return True
        except:
            return False
    
    def delete_raw(id):
        try:
            # Also delete from stock
            item = supabase.table("raw_materials").select("name").eq("id", id).execute().data[0]["name"]
            supabase.table("stock").delete().eq("item", item).execute()
            supabase.table("raw_materials").delete().eq("id", id).execute()
            log_audit("Delete Raw Material", item)
            return True
        except:
            return False
    
    form_fields = [
        {"name": "name", "label": "Item Name", "type": "text"},
        {"name": "unit", "label": "Unit", "type": "select", "options": ["KG","Liter","Pieces"]},
        {"name": "current_rate", "label": "Current Rate (Rs)", "type": "number"},
        {"name": "reorder_level", "label": "Reorder Level", "type": "number"}
    ]
    
    render_crud_table("raw_materials",
                      columns=["id","name","unit","current_rate","reorder_level"],
                      display_columns=["name","unit","current_rate","reorder_level"],
                      form_fields=form_fields,
                      fetch_func=fetch_raw,
                      insert_func=insert_raw,
                      update_func=update_raw,
                      delete_func=delete_raw)

# -------------------- Recipes Management (Dynamic Ingredients) --------------------
def recipes_management():
    st.header("Recipes")
    
    def fetch_recipes():
        return supabase.table("recipes").select("*").execute().data
    
    def insert_recipe(data):
        try:
            supabase.table("recipes").insert(data).execute()
            log_audit("Add Recipe", data["dish_name"])
            return True
        except:
            return False
    
    def update_recipe(id, data):
        try:
            supabase.table("recipes").update(data).eq("id", id).execute()
            log_audit("Update Recipe", data["dish_name"])
            return True
        except:
            return False
    
    def delete_recipe(id):
        try:
            supabase.table("recipes").delete().eq("id", id).execute()
            log_audit("Delete Recipe", str(id))
            return True
        except:
            return False
    
    # Custom add form with dynamic ingredients
    if st.button("➕ Add Recipe"):
        st.session_state.add_recipe = True
    
    if st.session_state.get("add_recipe", False):
        with st.form("add_recipe_form"):
            dish_name = st.text_input("Dish Name")
            selling_price = st.number_input("Selling Price", min_value=0.0, step=0.01)
            st.write("Ingredients")
            # Ingredient rows from session state
            for i, ing in enumerate(st.session_state.ingredients):
                cols = st.columns([4,2,2,1])
                with cols[0]:
                    ing["item"] = st.text_input(f"Item {i+1}", value=ing["item"], key=f"item_{i}")
                with cols[1]:
                    ing["qty"] = st.number_input(f"Qty {i+1}", min_value=0.0, step=0.1, value=ing["qty"], key=f"qty_{i}")
                with cols[2]:
                    ing["unit"] = st.selectbox(f"Unit {i+1}", ["g","ml","pcs"], index=["g","ml","pcs"].index(ing["unit"]), key=f"unit_{i}")
                with cols[3]:
                    if i > 0:
                        if st.button("❌", key=f"remove_{i}"):
                            st.session_state.ingredients.pop(i)
                            st.rerun()
            # Buttons to add/remove ingredients
            col1, col2 = st.columns([1,5])
            with col1:
                if st.button("➕ Add Ingredient"):
                    st.session_state.ingredients.append({"item": "", "qty": 0.0, "unit": "g"})
                    st.rerun()
            with col2:
                if st.button("🗑️ Clear All"):
                    st.session_state.ingredients = [{"item": "", "qty": 0.0, "unit": "g"}]
                    st.rerun()
            
            submitted = st.form_submit_button("Save")
            if submitted:
                ingredients = [ing for ing in st.session_state.ingredients if ing["item"].strip() and ing["qty"] > 0]
                if not ingredients:
                    st.error("Add at least one valid ingredient")
                else:
                    cost = calculate_recipe_cost(ingredients)
                    data = {
                        "dish_name": dish_name,
                        "ingredients": json.dumps(ingredients),
                        "selling_price": selling_price,
                        "cost_per_plate": cost
                    }
                    if insert_recipe(data):
                        st.success("Recipe added")
                        st.session_state.add_recipe = False
                        st.session_state.ingredients = [{"item": "", "qty": 0.0, "unit": "g"}]
                        st.rerun()
    
    # Display recipes with edit/delete
    recipes = fetch_recipes()
    if recipes:
        df = pd.DataFrame(recipes)
        for idx, row in df.iterrows():
            with st.expander(f"{row['dish_name']} - Rs {row['selling_price']}"):
                st.write(f"**Cost per plate:** Rs {row['cost_per_plate']}")
                st.write("**Ingredients:**")
                ingredients = json.loads(row['ingredients'])
                for ing in ingredients:
                    st.write(f"- {ing['item']}: {ing['qty']} {ing['unit']}")
                col1, col2 = st.columns([1,1])
                with col1:
                    if st.button(f"✏️ Edit", key=f"edit_recipe_{row['id']}"):
                        st.session_state.edit_recipe_id = row['id']
                        st.session_state.edit_recipe_data = row
                with col2:
                    if st.button(f"🗑️ Delete", key=f"delete_recipe_{row['id']}"):
                        if delete_recipe(row['id']):
                            st.success("Deleted")
                            st.rerun()
        st.markdown(get_csv_download_link(df[["dish_name","selling_price","cost_per_plate"]], "recipes.csv"), unsafe_allow_html=True)

# -------------------- Purchases Management --------------------
def purchases_management():
    st.header("Purchases")
    
    def fetch_purchases():
        return supabase.table("purchases").select("*").order("date", desc=True).execute().data
    
    def insert_purchase(data):
        try:
            data["total"] = data["quantity"] * data["rate"]
            supabase.table("purchases").insert(data).execute()
            # Update stock
            stock = supabase.table("stock").select("*").eq("item", data["item"]).execute()
            if stock.data:
                current = stock.data[0]["quantity"]
                supabase.table("stock").update({
                    "quantity": current + data["quantity"],
                    "last_updated": datetime.datetime.now().isoformat()
                }).eq("item", data["item"]).execute()
            else:
                supabase.table("stock").insert({
                    "item": data["item"],
                    "quantity": data["quantity"],
                    "unit": data["unit"]
                }).execute()
            # Update raw material rate
            supabase.table("raw_materials").update({"current_rate": data["rate"]}).eq("name", data["item"]).execute()
            log_audit("Add Purchase", f"{data['item']} {data['quantity']}{data['unit']}")
            return True
        except:
            return False
    
    def update_purchase(id, data):
        # Complex due to stock implications; we can disable edit for purchases
        st.warning("Edit not supported; delete and re-add if needed.")
        return False
    
    def delete_purchase(id):
        try:
            # Optionally revert stock? For simplicity, just delete
            supabase.table("purchases").delete().eq("id", id).execute()
            log_audit("Delete Purchase", str(id))
            return True
        except:
            return False
    
    form_fields = [
        {"name": "date", "label": "Date", "type": "date"},
        {"name": "item", "label": "Item", "type": "text"},
        {"name": "quantity", "label": "Quantity", "type": "number"},
        {"name": "unit", "label": "Unit", "type": "select", "options": ["KG","Liter","Pieces"]},
        {"name": "rate", "label": "Rate (Rs)", "type": "number"},
        {"name": "supplier", "label": "Supplier", "type": "text"}
    ]
    
    render_crud_table("purchases",
                      columns=["id","date","item","quantity","unit","rate","total","supplier"],
                      display_columns=["date","item","quantity","unit","rate","total","supplier"],
                      form_fields=form_fields,
                      fetch_func=fetch_purchases,
                      insert_func=insert_purchase,
                      update_func=update_purchase,
                      delete_func=delete_purchase)

# -------------------- Monthly Ration Management --------------------
def monthly_ration_management():
    st.header("Monthly Ration")
    
    def fetch_ration():
        return supabase.table("monthly_ration").select("*").order("month", desc=True).execute().data
    
    def insert_ration(data):
        try:
            supabase.table("monthly_ration").insert(data).execute()
            log_audit("Add Monthly Ration", f"{data['month']} {data['item']}")
            return True
        except:
            return False
    
    def update_ration(id, data):
        try:
            supabase.table("monthly_ration").update(data).eq("id", id).execute()
            log_audit("Update Monthly Ration", str(id))
            return True
        except:
            return False
    
    def delete_ration(id):
        try:
            supabase.table("monthly_ration").delete().eq("id", id).execute()
            log_audit("Delete Monthly Ration", str(id))
            return True
        except:
            return False
    
    form_fields = [
        {"name": "month", "label": "Month (YYYY-MM)", "type": "text"},
        {"name": "item", "label": "Item", "type": "text"},
        {"name": "target_qty", "label": "Target Quantity", "type": "number"},
        {"name": "unit", "label": "Unit", "type": "select", "options": ["KG","Liter","Pieces"]}
    ]
    
    render_crud_table("monthly_ration",
                      columns=["id","month","item","target_qty","unit"],
                      display_columns=["month","item","target_qty","unit"],
                      form_fields=form_fields,
                      fetch_func=fetch_ration,
                      insert_func=insert_ration,
                      update_func=update_ration,
                      delete_func=delete_ration)

# -------------------- Receiver --------------------
def receive_material_page():
    st.header("Receive Material")
    with st.form("receive_form"):
        date = st.date_input("Date", datetime.date.today())
        item = st.text_input("Item")
        month = get_current_month()
        ration = supabase.table("monthly_ration").select("target_qty").eq("month", month).eq("item", item).execute().data
        expected = ration[0]["target_qty"] if ration else 0.0
        st.info(f"Expected this month: {expected}")
        expected_input = st.number_input("Expected Quantity", value=expected, min_value=0.0, step=0.01)
        received = st.number_input("Received Quantity", min_value=0.0, step=0.01)
        batch = st.text_input("Batch No. (optional)")
        if st.form_submit_button("Save"):
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
                st.rerun()
            except Exception as e:
                st.error(str(e))

    history = supabase.table("receiving").select("*").limit(10).order("date", desc=True).execute().data
    if history:
        st.subheader("Recent Receivings")
        st.dataframe(pd.DataFrame(history), use_container_width=True)

# -------------------- Chef Pages --------------------
def plan_menu_page():
    st.header("Plan Menu")
    recipes = supabase.table("recipes").select("*").execute().data
    if not recipes:
        st.warning("No recipes found")
        return

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
            for item in production_data:
                recipe = next(r for r in recipes if r['dish_name'] == item['dish'])
                ingredients = json.loads(recipe['ingredients'])
                for ing in ingredients:
                    stock = supabase.table("stock").select("quantity").eq("item", ing['item']).execute()
                    if stock.data:
                        current = stock.data[0]["quantity"]
                        qty_needed = ing['qty'] * item['persons'] / 1000 if ing['unit'] in ['g','ml'] else ing['qty'] * item['persons']
                        new_qty = current - qty_needed
                        supabase.table("stock").update({"quantity": new_qty}).eq("item", ing['item']).execute()
                supabase.table("production").insert({
                    "date": datetime.date.today().isoformat(),
                    "dish": item['dish'],
                    "persons": item['persons'],
                    "raw_material_used": json.dumps(ingredients),
                    "planned_by": st.session_state.user['email']
                }).execute()
            st.success("Production planned and stock deducted")
            log_audit("Production", str(production_data))
            st.rerun()
        else:
            st.error(f"Insufficient stock for items: {', '.join(set(insufficient_items))}")

def production_page():
    st.header("Today's Production")
    today = datetime.date.today().isoformat()
    prods = supabase.table("production").select("*").eq("date", today).execute().data
    if prods:
        df = pd.DataFrame(prods)
        st.dataframe(df, use_container_width=True)

def wastage_page():
    st.header("Wastage Entry")
    with st.form("wastage_form"):
        date = st.date_input("Date", datetime.date.today())
        item = st.text_input("Item/Dish")
        qty = st.number_input("Quantity", min_value=0.0, step=0.01)
        unit = st.selectbox("Unit", ["KG","Liter","Pieces","Plates"])
        reason = st.selectbox("Reason", ["Extra Bacha","Jal Gaya","Kharab","Gira","Other"])
        remarks = st.text_input("Remarks")
        if st.form_submit_button("Save"):
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
            st.rerun()

def feedback_insights():
    st.header("Feedback Insights")
    feedback = supabase.table("feedback").select("*").execute().data
    if not feedback:
        st.info("No feedback yet")
        return
    df = pd.DataFrame(feedback)
    avg_rating = df.groupby("dish")["rating"].mean().reset_index()
    st.subheader("Average Ratings")
    fig = px.bar(avg_rating, x="dish", y="rating", title="Dish Ratings")
    st.plotly_chart(fig, use_container_width=True)
    complaints = df[df["reason"] != ""]["reason"].value_counts().reset_index()
    complaints.columns = ["Reason", "Count"]
    st.subheader("Common Complaints")
    st.dataframe(complaints, use_container_width=True)

# -------------------- Cashier Pages --------------------
def billing_page():
    st.header("Cashier Billing")
    emp_id = st.text_input("Employee ID")
    emp = None
    if emp_id:
        emp = supabase.table("employees").select("*").eq("emp_id", emp_id).execute().data
        if emp:
            st.success(f"Employee: {emp[0]['name']} ({emp[0]['department']})")
            ledger = supabase.table("ledger").select("balance").eq("emp_id", emp_id).order("date", desc=True).limit(1).execute().data
            outstanding = ledger[0]["balance"] if ledger else 0
            st.info(f"Outstanding: Rs {outstanding}")
        else:
            st.error("Employee not found")

    today = datetime.date.today().isoformat()
    productions = supabase.table("production").select("*").eq("date", today).execute().data
    if productions:
        menu = [p["dish"] for p in productions]
        st.subheader("Today's Menu")
        selected_items = {}
        for dish in menu:
            cols = st.columns([3,1])
            with cols[0]:
                qty = st.number_input(f"Qty for {dish}", min_value=0, step=1, key=dish)
            if qty:
                selected_items[dish] = qty

        total = 0
        for dish, qty in selected_items.items():
            price = supabase.table("recipes").select("selling_price").eq("dish_name", dish).execute().data[0]["selling_price"]
            total += price * qty

        st.metric("Total", f"Rs {total}")

        payment = st.radio("Payment Status", ["PAID", "UNPAID"], horizontal=True)
        if st.button("Save Bill"):
            if not emp_id or not emp:
                st.error("Valid Employee ID required")
                return
            order_id = f"ORD{datetime.datetime.now().strftime('%y%m%d%H%M%S')}"
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
        cols = st.columns(3)
        cols[0].metric("Total", f"Rs {total}")
        cols[1].metric("Paid", f"Rs {paid}")
        cols[2].metric("Unpaid", f"Rs {unpaid}")
        st.dataframe(df[["order_id","emp_id","total","payment_status"]], use_container_width=True)
        st.markdown(get_csv_download_link(df, "today_sales.csv"), unsafe_allow_html=True)
    else:
        st.info("No sales today")

# -------------------- Employee Feedback --------------------
def employee_feedback():
    st.header("Give Feedback")
    emp_id = st.text_input("Your Employee ID")
    if emp_id:
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
                if st.form_submit_button("Submit"):
                    supabase.table("feedback").insert({
                        "date": datetime.date.today().isoformat(),
                        "emp_id": emp_id,
                        "dish": dish,
                        "rating": rating,
                        "ate_percent": ate,
                        "reason": reason,
                        "comments": comments,
                        "points": 10
                    }).execute()
                    st.success("Thank you for your feedback! You earned 10 points.")
                    st.rerun()
        else:
            st.warning("No meals found for this employee")

def my_feedback_history():
    st.header("My Feedback History")
    emp_id = st.text_input("Employee ID")
    if emp_id:
        feedback = supabase.table("feedback").select("*").eq("emp_id", emp_id).order("date", desc=True).execute().data
        if feedback:
            df = pd.DataFrame(feedback)[["date","dish","rating","ate_percent","reason","comments"]]
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No feedback yet")

def my_points():
    st.header("My Loyalty Points")
    emp_id = st.text_input("Employee ID")
    if emp_id:
        points = get_employee_points(emp_id)
        st.metric("Total Points", points)
        st.info("Redeem options coming soon!")

# -------------------- Reports (Advanced) --------------------
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
                st.dataframe(df, use_container_width=True)
                # Chart
                sales_by_date = df.groupby("date")["total"].sum().reset_index()
                fig = px.line(sales_by_date, x="date", y="total", title="Sales Trend")
                st.plotly_chart(fig, use_container_width=True)
        elif report_type == "Stock":
            data_raw = supabase.table("stock").select("*").execute().data
            if data_raw:
                df = pd.DataFrame(data_raw)
                headers = ["Item","Quantity","Unit","Last Updated"]
                data = df[["item","quantity","unit","last_updated"]].values.tolist()
                st.dataframe(df, use_container_width=True)
        elif report_type == "Wastage":
            data_raw = supabase.table("wastage").select("*").gte("date", start.isoformat()).lte("date", end.isoformat()).execute().data
            if data_raw:
                df = pd.DataFrame(data_raw)
                headers = ["Date","Item","Quantity","Unit","Reason"]
                data = df[["date","item","quantity","unit","reason"]].values.tolist()
                st.dataframe(df, use_container_width=True)
                # Pie chart by reason
                reason_counts = df["reason"].value_counts().reset_index()
                reason_counts.columns = ["Reason","Count"]
                fig = px.pie(reason_counts, values="Count", names="Reason", title="Wastage by Reason")
                st.plotly_chart(fig, use_container_width=True)
        elif report_type == "Feedback":
            data_raw = supabase.table("feedback").select("*").gte("date", start.isoformat()).lte("date", end.isoformat()).execute().data
            if data_raw:
                df = pd.DataFrame(data_raw)
                headers = ["Date","Employee","Dish","Rating","Ate%","Reason"]
                data = df[["date","emp_id","dish","rating","ate_percent","reason"]].values.tolist()
                st.dataframe(df, use_container_width=True)
                # Avg rating by dish
                avg_rating = df.groupby("dish")["rating"].mean().reset_index()
                fig = px.bar(avg_rating, x="dish", y="rating", title="Average Rating by Dish")
                st.plotly_chart(fig, use_container_width=True)
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
                st.dataframe(df, use_container_width=True)

        if data:
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
        logo_file = st.file_uploader("Upload Logo (image)", type=["png","jpg","jpeg"])
        if st.form_submit_button("Save"):
            logo_url = settings_dict.get("logo_url", "")
            if logo_file:
                file_bytes = logo_file.read()
                file_name = f"logo_{int(time.time())}.png"
                supabase.storage.from_("logos").upload(file_name, file_bytes, {"content-type": logo_file.type})
                logo_url = file_name
            for key, val in [("app_name", app_name), ("company_name", company), ("primary_color", color), ("date_format", date_fmt), ("logo_url", logo_url)]:
                supabase.table("settings").upsert({"key": key, "value": val}).execute()
            st.success("Settings saved")
            log_audit("Settings", "Updated")
            st.rerun()

# -------------------- Audit Log --------------------
def audit_page():
    st.header("Audit Log")
    logs = supabase.table("audit_log").select("*").order("timestamp", desc=True).limit(100).execute().data
    if logs:
        df = pd.DataFrame(logs)
        st.dataframe(df, use_container_width=True)
        st.markdown(get_csv_download_link(df, "audit_log.csv"), unsafe_allow_html=True)

# -------------------- Main --------------------
def main():
    if st.session_state.user is None:
        login_page()
    else:
        dashboard()

if __name__ == "__main__":
    main()
