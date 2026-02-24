import streamlit as st
import pandas as pd
import datetime
import json
import time
import calendar
from supabase import create_client
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import base64
import io

# -------------------- Page Config --------------------
st.set_page_config(
    page_title="Catering System",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': None,
        'Report a bug': None,
        'About': 'Catering Management System v8.0'
    }
)

# -------------------- Initialize Supabase --------------------
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# -------------------- Cached Queries --------------------
@st.cache_data(ttl=300)
def get_raw_materials():
    return supabase.table("raw_materials").select("*").execute().data

@st.cache_data(ttl=300)
def get_recipes():
    return supabase.table("recipes").select("*").execute().data

@st.cache_data(ttl=300)
def get_employees_all():
    return supabase.table("employees").select("*").execute().data

@st.cache_data(ttl=60)
def get_sales_range(start_date, end_date):
    return supabase.table("sales").select("*").gte("date", start_date).lte("date", end_date).execute().data

@st.cache_data(ttl=60)
def get_purchases_range(start_date, end_date):
    return supabase.table("purchases").select("*").gte("date", start_date).lte("date", end_date).execute().data

@st.cache_data(ttl=60)
def get_feedback_range(start_date, end_date):
    return supabase.table("feedback").select("*").gte("date", start_date).lte("date", end_date).execute().data

@st.cache_data(ttl=60)
def get_wastage_range(start_date, end_date):
    return supabase.table("wastage").select("*").gte("date", start_date).lte("date", end_date).execute().data

@st.cache_data(ttl=300)
def get_all_production():
    return supabase.table("production").select("*").execute().data

@st.cache_data(ttl=300)
def get_all_stock():
    return supabase.table("stock").select("*").execute().data

# -------------------- Enhanced Dashboard Caches --------------------
@st.cache_data(ttl=300)
def get_last_7_days_sales():
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=6)
    sales_data = supabase.table("sales").select("date, total").gte("date", start_date.isoformat()).lte("date", end_date.isoformat()).execute().data
    df = pd.DataFrame(sales_data)
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df = df.groupby('date')['total'].sum().reset_index()
    return df

@st.cache_data(ttl=300)
def get_last_7_days_wastage():
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=6)
    wastage_data = supabase.table("wastage").select("date, quantity").gte("date", start_date.isoformat()).lte("date", end_date.isoformat()).execute().data
    df = pd.DataFrame(wastage_data)
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df = df.groupby('date')['quantity'].sum().reset_index()
    return df

@st.cache_data(ttl=300)
def get_last_7_days_feedback_ratings():
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=6)
    feedback_data = supabase.table("feedback").select("date, rating").gte("date", start_date.isoformat()).lte("date", end_date.isoformat()).execute().data
    df = pd.DataFrame(feedback_data)
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df = df.groupby('date')['rating'].mean().reset_index()
    return df

@st.cache_data(ttl=300)
def get_top_dishes_last_7_days():
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=6)
    sales_data = supabase.table("sales").select("items").gte("date", start_date.isoformat()).lte("date", end_date.isoformat()).execute().data
    dish_counts = {}
    for sale in sales_data:
        items = json.loads(sale['items'])
        for dish, qty in items.items():
            dish_counts[dish] = dish_counts.get(dish, 0) + qty
    df = pd.DataFrame(list(dish_counts.items()), columns=['Dish', 'Quantity']).sort_values('Quantity', ascending=False).head(5)
    return df

@st.cache_data(ttl=300)
def get_wastage_by_reason_last_7_days():
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=6)
    wastage_data = supabase.table("wastage").select("reason, quantity").gte("date", start_date.isoformat()).lte("date", end_date.isoformat()).execute().data
    df = pd.DataFrame(wastage_data)
    if not df.empty:
        df = df.groupby('reason')['quantity'].sum().reset_index()
    return df

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
    stock_data = get_all_stock()
    raw_data = get_raw_materials()
    reorder_map = {r["name"]: r["reorder_level"] for r in raw_data}
    low_stock = []
    for s in stock_data:
        if s["quantity"] <= reorder_map.get(s["item"], 0):
            low_stock.append(s)
    return low_stock

def get_employee_points(emp_id):
    feedback = supabase.table("feedback").select("points").eq("emp_id", emp_id).execute().data
    return sum(f["points"] for f in feedback) if feedback else 0

def get_available_months():
    data = supabase.table("monthly_ration").select("month").execute().data
    months = sorted(set(d['month'] for d in data), reverse=True)
    return months

# -------------------- Notifications --------------------
def check_low_stock_notifications():
    low_stock = get_low_stock_details()
    for item in low_stock:
        st.toast(f"⚠️ Low stock: {item['item']} only {item['quantity']} left", icon="⚠️")

# -------------------- Professional PDF Generation --------------------
def generate_professional_pdf(title, data, headers, filename, landscape=False, logo_url=None, company_name=None):
    pdf = FPDF()
    if landscape:
        pdf.add_page(orientation='L')
    else:
        pdf.add_page()
    
    # Logo and header
    if logo_url:
        # Download logo from URL (simplified: use local file, but here we skip)
        pdf.image(logo_url, x=10, y=8, w=33)
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, title, ln=1, align="C")
    if company_name:
        pdf.set_font("Arial", "", 10)
        pdf.cell(0, 5, company_name, ln=1, align="C")
    pdf.ln(10)
    
    # Column widths (auto)
    col_width = pdf.w / (len(headers) + 1) - 1
    pdf.set_font("Arial", "B", 10)
    for header in headers:
        pdf.cell(col_width, 8, header, 1, 0, 'C')
    pdf.ln()
    
    pdf.set_font("Arial", "", 8)
    for row in data:
        for i, cell in enumerate(row):
            # Truncate if too long
            cell_str = str(cell)
            if len(cell_str) > 30:
                cell_str = cell_str[:27] + "..."
            pdf.cell(col_width, 6, cell_str, 1, 0, 'L' if i>0 else 'C')
        pdf.ln()
    
    # Footer
    pdf.set_y(-15)
    pdf.set_font("Arial", "I", 8)
    pdf.cell(0, 10, f"Generated on {datetime.datetime.now().strftime('%d-%m-%Y %H:%M')} - Page {pdf.page_no()}", 0, 0, 'C')
    
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

def get_excel_download_link(df, filename):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    excel_data = output.getvalue()
    b64 = base64.b64encode(excel_data).decode()
    return f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="{filename}">📥 Download Excel</a>'

# -------------------- Custom CSS for Perfect Alignment --------------------
def apply_custom_css(primary_color, logo_url=None):
    st.markdown(f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        
        :root {{
            --primary: {primary_color};
            --primary-light: {primary_color}20;
            --primary-dark: {primary_color}cc;
            --sidebar-bg: #1e293b;
            --card-bg: #ffffff;
            --text-dark: #0f172a;
            --text-muted: #64748b;
            --border-light: #e2e8f0;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --info: #3b82f6;
        }}
        
        * {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }}
        
        .stApp {{
            background-color: #f8fafc;
        }}
        
        .main .block-container {{
            padding: 2rem 2rem;
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        /* Sidebar */
        .css-1d391kg, [data-testid="stSidebar"] {{
            background-color: var(--sidebar-bg);
            background-image: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
            color: #f1f5f9;
            padding: 1rem 0.5rem;
        }}
        
        /* Sidebar buttons */
        .stButton button {{
            width: 100%;
            text-align: left;
            background-color: transparent;
            color: #cbd5e1;
            border: none;
            padding: 0.75rem 1rem;
            border-radius: 0.5rem;
            font-weight: 500;
            transition: all 0.2s;
            margin-bottom: 0.25rem;
            display: flex;
            align-items: center;
        }}
        
        .stButton button:hover {{
            background-color: #334155;
            color: white;
        }}
        
        .stButton button.active {{
            background-color: var(--primary);
            color: white;
        }}
        
        /* Sidebar logo and text */
        .sidebar-logo {{
            text-align: center;
            margin-bottom: 1rem;
        }}
        
        .sidebar-logo img {{
            max-width: 150px;
            border-radius: 0.5rem;
        }}
        
        .user-info {{
            padding: 0 1rem 1rem 1rem;
            border-bottom: 1px solid #334155;
            margin-bottom: 1rem;
        }}
        
        .user-info h4 {{
            color: white;
            margin-bottom: 0.25rem;
        }}
        
        .user-info p {{
            color: #94a3b8;
            font-size: 0.9rem;
        }}
        
        /* Cards */
        .stMetric, div[data-testid="stExpander"], .stDataFrame, .stForm {{
            background-color: var(--card-bg);
            border-radius: 1rem;
            padding: 1.5rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            border: 1px solid var(--border-light);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        
        .stMetric:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        }}
        
        /* Main buttons */
        .stButton>button:not(.sidebar-button) {{
            background-color: var(--primary);
            color: white;
            border: none;
            border-radius: 0.5rem;
            padding: 0.5rem 1rem;
            font-weight: 500;
            transition: all 0.2s;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}
        
        .stButton>button:hover:not(.sidebar-button) {{
            background-color: var(--primary-dark);
            transform: translateY(-1px);
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.15);
        }}
        
        /* Inputs */
        .stTextInput>div>input, .stNumberInput>div>input, .stSelectbox>div>select, .stDateInput>div>input {{
            border-radius: 0.5rem;
            border: 1px solid var(--border-light);
            padding: 0.5rem;
            background-color: white;
            transition: border-color 0.2s, box-shadow 0.2s;
        }}
        
        .stTextInput>div>input:focus, .stNumberInput>div>input:focus, .stSelectbox>div>select:focus, .stDateInput>div>input:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 3px {primary_color}40;
            outline: none;
        }}
        
        /* Tables */
        .stDataFrame {{
            overflow: hidden;
        }}
        
        .stDataFrame thead tr th {{
            background-color: #f8fafc;
            font-weight: 600;
            color: var(--text-dark);
            border-bottom: 2px solid var(--primary-light);
        }}
        
        .stDataFrame tbody tr:nth-child(even) {{
            background-color: #f8fafc;
        }}
        
        .stDataFrame tbody tr:hover {{
            background-color: {primary_color}10;
        }}
        
        /* Metrics */
        .stMetric {{
            text-align: center;
        }}
        
        .stMetric label {{
            color: var(--text-muted);
            font-weight: 500;
        }}
        
        .stMetric .css-1wivap2 {{
            font-size: 2rem;
            font-weight: 700;
            color: var(--text-dark);
        }}
        
        /* Headers */
        h1, h2, h3 {{
            color: var(--text-dark);
            font-weight: 600;
            margin-bottom: 1rem;
        }}
        
        h1 {{
            font-size: 2rem;
            border-bottom: 2px solid var(--primary-light);
            padding-bottom: 0.5rem;
        }}
        
        h2 {{
            font-size: 1.5rem;
        }}
        
        h3 {{
            font-size: 1.25rem;
        }}
        
        /* Expanders */
        .streamlit-expanderHeader {{
            font-weight: 600;
            color: var(--text-dark);
            background-color: #f8fafc;
            border-radius: 0.5rem;
            padding: 0.75rem;
        }}
        
        /* Alerts */
        .stAlert {{
            border-radius: 0.5rem;
            border-left-width: 4px;
        }}
        
        .stAlert.success {{
            background-color: #d1fae5;
            border-left-color: var(--success);
        }}
        
        .stAlert.error {{
            background-color: #fee2e2;
            border-left-color: var(--danger);
        }}
        
        .stAlert.warning {{
            background-color: #fef3c7;
            border-left-color: var(--warning);
        }}
        
        .stAlert.info {{
            background-color: #dbeafe;
            border-left-color: var(--info);
        }}
        
        /* Toast */
        .stToast {{
            border-radius: 0.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        
        /* Mobile responsiveness */
        @media (max-width: 768px) {{
            .main .block-container {{
                padding: 1rem;
            }}
            
            .stMetric {{
                padding: 1rem;
            }}
            
            .stButton>button {{
                width: 100%;
            }}
            
            [data-testid="stSidebar"] {{
                width: 100%;
            }}
        }}
    </style>
    """, unsafe_allow_html=True)

# -------------------- Session State --------------------
if "user" not in st.session_state:
    st.session_state.user = None
if "page" not in st.session_state:
    st.session_state.page = "Dashboard"
if "edit_id" not in st.session_state:
    st.session_state.edit_id = None
if "edit_table" not in st.session_state:
    st.session_state.edit_table = None
if "ingredients" not in st.session_state:
    st.session_state.ingredients = [{"item": "", "qty": 0.0, "unit": "g"}]
if "last_notification" not in st.session_state:
    st.session_state.last_notification = datetime.datetime.now().isoformat()
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = {}

# -------------------- Login Page --------------------
def login_page():
    st.markdown("<h1 style='text-align: center;'>Catering Management System</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        with st.form("login_form"):
            if logo_url := get_logo_url():
                st.markdown(f'<div style="text-align: center;"><img src="{logo_url}" style="max-height:80px;"></div>', unsafe_allow_html=True)
            email = st.text_input("Email", placeholder="super@catering.com")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                user = login_user(email, password)
                if user:
                    st.session_state.user = user
                    st.session_state.page = "Dashboard"
                    log_audit("Login", f"User {email} logged in")
                    st.rerun()
                else:
                    st.error("Invalid credentials or inactive account")

# -------------------- Dashboard --------------------
def dashboard():
    user = st.session_state.user
    role = user["role"]
    primary_color = get_primary_color()
    apply_custom_css(primary_color, get_logo_url())

    # Notifications
    check_low_stock_notifications()

    with st.sidebar:
        if logo_url := get_logo_url():
            st.markdown(f'<div class="sidebar-logo"><img src="{logo_url}"></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="user-info"><h4>{user["email"]}</h4><p>Role: {role}</p></div>', unsafe_allow_html=True)

        menu_options = {
            "SuperUser": [
                ("📊 Dashboard", "Dashboard"),
                ("👥 Users", "Users"),
                ("👤 Employees", "Employees"),
                ("📦 Raw Materials", "Raw Materials"),
                ("🍽️ Recipes", "Recipes"),
                ("💰 Purchases", "Purchases"),
                ("📅 Monthly Ration", "Monthly Ration"),
                ("📈 Reports", "Reports"),
                ("⚙️ Settings", "Settings"),
                ("📋 Audit", "Audit"),
            ],
            "Admin": [
                ("📊 Dashboard", "Dashboard"),
                ("👥 Users", "Users"),
                ("👤 Employees", "Employees"),
                ("📦 Raw Materials", "Raw Materials"),
                ("🍽️ Recipes", "Recipes"),
                ("💰 Purchases", "Purchases"),
                ("📅 Monthly Ration", "Monthly Ration"),
                ("📈 Reports", "Reports"),
                ("📋 Audit", "Audit"),
            ],
            "Receiver": [
                ("📊 Dashboard", "Dashboard"),
                ("📥 Receive Material", "Receive Material"),
            ],
            "Chef": [
                ("📊 Dashboard", "Dashboard"),
                ("📝 Plan Menu", "Plan Menu"),
                ("🍳 Production", "Production"),
                ("🗑️ Wastage", "Wastage"),
                ("💬 Feedback Insights", "Feedback Insights"),
            ],
            "Cashier": [
                ("📊 Dashboard", "Dashboard"),
                ("🧾 Billing", "Billing"),
                ("📋 Today's Summary", "Today's Summary"),
            ],
            "Employee": [
                ("📊 Dashboard", "Dashboard"),
                ("⭐ Give Feedback", "Give Feedback"),
                ("📜 My Feedback History", "My Feedback History"),
                ("🏆 My Points", "My Points"),
            ]
        }

        items = menu_options.get(role, [("📊 Dashboard", "Dashboard")])
        for label, page in items:
            if st.button(label, key=f"nav_{page}", use_container_width=True):
                st.session_state.page = page
                st.rerun()

        if st.button("🚪 Logout", use_container_width=True):
            log_audit("Logout", f"User {user['email']} logged out")
            st.session_state.user = None
            st.rerun()

    # Render selected page
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
    pages[st.session_state.page]()

# -------------------- Dashboard Stats --------------------
@st.cache_data(ttl=60)
def get_dashboard_stats():
    today = datetime.date.today().isoformat()
    sales = supabase.table("sales").select("*").eq("date", today).execute()
    total_sales = sum(item["total"] for item in sales.data) if sales.data else 0
    meals_served = len(sales.data) if sales.data else 0
    employees = get_employees_all()
    active_employees = sum(1 for e in employees if e.get('status') == 'Active')
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
    with st.spinner("Loading dashboard..."):
        stats = get_dashboard_stats()
        sales_trend = get_last_7_days_sales()
        wastage_trend = get_last_7_days_wastage()
        feedback_trend = get_last_7_days_feedback_ratings()
        top_dishes = get_top_dishes_last_7_days()
        wastage_reasons = get_wastage_by_reason_last_7_days()

    # KPIs
    cols = st.columns(4)
    cols[0].metric("Today's Sales", f"Rs {stats['today_sales']:,.0f}")
    cols[1].metric("Meals Served", stats['meals_served'])
    cols[2].metric("Active Employees", stats['active_employees'])
    cols[3].metric("Low Stock Items", stats['low_stock'])

    # Second row: Average Rating (as a large metric)
    st.metric("Average Rating (All Time)", f"{stats['avg_rating']:.1f} / 5")

    # Low stock alerts
    if stats['low_stock_details']:
        st.subheader("⚠️ Low Stock Alerts")
        for item in stats['low_stock_details']:
            reorder = supabase.table("raw_materials").select("reorder_level").eq("name", item["item"]).execute().data
            level = reorder[0]["reorder_level"] if reorder else 0
            st.warning(f"{item['item']} only {item['quantity']} {item['unit']} left (Reorder level: {level})")

    # Charts row 1: Sales Trend and Top Dishes
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Sales Trend (Last 7 Days)")
        if not sales_trend.empty:
            fig = px.line(sales_trend, x='date', y='total', title="Daily Sales")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No sales data in last 7 days")
    with col2:
        st.subheader("Top 5 Dishes (Last 7 Days)")
        if not top_dishes.empty:
            fig = px.bar(top_dishes, x='Dish', y='Quantity', title="Top Dishes by Quantity")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No dish sales in last 7 days")

    # Charts row 2: Wastage Trend and Wastage by Reason
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Wastage Trend (Last 7 Days)")
        if not wastage_trend.empty:
            fig = px.line(wastage_trend, x='date', y='quantity', title="Daily Wastage Quantity")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No wastage data in last 7 days")
    with col2:
        st.subheader("Wastage by Reason (Last 7 Days)")
        if not wastage_reasons.empty:
            fig = px.pie(wastage_reasons, values='quantity', names='reason', title="Wastage Distribution")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No wastage data")

    # Charts row 3: Feedback Rating Trend
    st.subheader("Average Feedback Rating (Last 7 Days)")
    if not feedback_trend.empty:
        fig = px.line(feedback_trend, x='date', y='rating', title="Daily Average Rating", range_y=[1,5])
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No feedback in last 7 days")

# -------------------- CRUD Helper (with friendly expander title) --------------------
def render_crud_table(table_name, columns, display_columns, form_fields, fetch_func, insert_func, update_func, delete_func, key_field="id", searchable=True, title_field=None):
    st.subheader(table_name.replace("_", " ").title())
    
    # Add button
    if st.button(f"➕ Add {table_name[:-1].title()}"):
        st.session_state[f"add_{table_name}"] = True

    # Add form
    if st.session_state.get(f"add_{table_name}", False):
        with st.form(f"form_add_{table_name}", clear_on_submit=True):
            row_data = {}
            for field in form_fields:
                if field["type"] == "text":
                    row_data[field["name"]] = st.text_input(field["label"])
                elif field["type"] == "number":
                    row_data[field["name"]] = st.number_input(field["label"], value=0.0, step=0.01, format="%.2f")
                elif field["type"] == "select":
                    row_data[field["name"]] = st.selectbox(field["label"], field["options"])
                elif field["type"] == "date":
                    row_data[field["name"]] = st.date_input(field["label"], datetime.date.today()).isoformat()
            if st.form_submit_button("Save"):
                with st.spinner("Saving..."):
                    if insert_func(row_data):
                        st.success("Added successfully")
                        st.session_state[f"add_{table_name}"] = False
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("Failed to add")

    # Fetch data
    data = fetch_func()
    if not data:
        st.info("No records found")
        return

    df = pd.DataFrame(data)

    # Search box
    if searchable:
        search_term = st.text_input(f"🔍 Search {table_name}", key=f"search_{table_name}").lower()
        if search_term:
            mask = df.apply(lambda row: row.astype(str).str.lower().str.contains(search_term).any(), axis=1)
            df = df[mask]

    # Pagination
    page_size = 10
    total_pages = (len(df) + page_size - 1) // page_size
    if total_pages > 0:
        page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1, key=f"page_{table_name}")
        start = (page - 1) * page_size
        end = start + page_size
        df_page = df.iloc[start:end]
    else:
        df_page = df

    # Main table (hide key field)
    st.dataframe(df_page[display_columns], use_container_width=True)

    # Expandable details for each record with inline edit
    for idx, row in df_page.iterrows():
        record_id = row[key_field]
        # Determine a friendly title for the expander
        if title_field and title_field in row:
            friendly_id = row[title_field]
        else:
            friendly_id = f"Record {idx+1}"
        expander_key = f"expander_{table_name}_{record_id}"
        with st.expander(f"Details for {friendly_id}"):
            # Check if this record is in edit mode
            edit_key = f"edit_mode_{table_name}_{record_id}"
            if st.session_state.edit_mode.get(edit_key, False):
                # Edit form
                with st.form(key=f"edit_form_{table_name}_{record_id}"):
                    updated_data = {}
                    for field in form_fields:
                        current_value = row.get(field["name"], "")
                        if field["type"] == "text":
                            updated_data[field["name"]] = st.text_input(field["label"], value=current_value)
                        elif field["type"] == "number":
                            updated_data[field["name"]] = st.number_input(field["label"], value=float(current_value), step=0.01, format="%.2f")
                        elif field["type"] == "select":
                            options = field["options"]
                            default_index = options.index(current_value) if current_value in options else 0
                            updated_data[field["name"]] = st.selectbox(field["label"], options, index=default_index)
                        elif field["type"] == "date":
                            date_val = datetime.datetime.strptime(current_value, "%Y-%m-%d").date() if current_value else datetime.date.today()
                            updated_data[field["name"]] = st.date_input(field["label"], date_val).isoformat()
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.form_submit_button("💾 Save"):
                            if update_func(record_id, updated_data):
                                st.success("Updated")
                                st.session_state.edit_mode[edit_key] = False
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error("Update failed")
                    with col2:
                        if st.form_submit_button("❌ Cancel"):
                            st.session_state.edit_mode[edit_key] = False
                            st.rerun()
            else:
                # Display record details in a clean format
                cols = st.columns(2)
                field_index = 0
                for col_name in display_columns:
                    with cols[field_index % 2]:
                        st.markdown(f"**{col_name}:** {row[col_name]}")
                    field_index += 1
                # Buttons
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"✏️ Edit", key=f"edit_{table_name}_{record_id}"):
                        st.session_state.edit_mode[edit_key] = True
                        st.rerun()
                with col2:
                    if st.button(f"🗑️ Delete", key=f"delete_{table_name}_{record_id}"):
                        if delete_func(record_id):
                            st.success("Deleted")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("Delete failed")

    # Export links
    st.markdown(get_csv_download_link(df[display_columns], f"{table_name}.csv"), unsafe_allow_html=True)
    st.markdown(get_excel_download_link(df[display_columns], f"{table_name}.xlsx"), unsafe_allow_html=True)

# -------------------- User Management --------------------
def users_management():
    st.header("User Management")
    def fetch(): return supabase.table("users").select("*").execute().data
    def insert(data):
        try:
            supabase.table("users").insert(data).execute()
            log_audit("Add User", data["email"])
            return True
        except Exception as e:
            st.error(str(e))
            return False
    def update(id, data):
        try:
            supabase.table("users").update(data).eq("id", id).execute()
            log_audit("Update User", data["email"])
            return True
        except Exception as e:
            st.error(str(e))
            return False
    def delete(id):
        try:
            supabase.table("users").delete().eq("id", id).execute()
            log_audit("Delete User", str(id))
            return True
        except Exception as e:
            st.error(str(e))
            return False
    form_fields = [
        {"name": "email", "label": "Email", "type": "text"},
        {"name": "role", "label": "Role", "type": "select", "options": ["SuperUser","Admin","Receiver","Chef","Cashier","Employee"]},
        {"name": "password", "label": "Password", "type": "text"},
        {"name": "status", "label": "Status", "type": "select", "options": ["Active","Inactive"]}
    ]
    render_crud_table("users", ["id","email","role","status"], ["email","role","status"], form_fields, fetch, insert, update, delete, title_field="email")

# -------------------- Employees Management --------------------
def employees_management():
    st.header("Employees Management")
    def fetch(): return supabase.table("employees").select("*").execute().data
    def insert(data):
        try:
            supabase.table("employees").insert(data).execute()
            log_audit("Add Employee", data["emp_id"])
            return True
        except Exception as e:
            st.error(str(e))
            return False
    def update(id, data):
        try:
            supabase.table("employees").update(data).eq("emp_id", id).execute()
            log_audit("Update Employee", id)
            return True
        except Exception as e:
            st.error(str(e))
            return False
    def delete(id):
        try:
            supabase.table("employees").delete().eq("emp_id", id).execute()
            log_audit("Delete Employee", id)
            return True
        except Exception as e:
            st.error(str(e))
            return False
    form_fields = [
        {"name": "emp_id", "label": "Employee ID", "type": "text"},
        {"name": "name", "label": "Name", "type": "text"},
        {"name": "department", "label": "Department", "type": "text"},
        {"name": "designation", "label": "Designation", "type": "text"},
        {"name": "status", "label": "Status", "type": "select", "options": ["Active","Inactive"]},
        {"name": "dietary_pref", "label": "Dietary Preference", "type": "select", "options": ["Regular","Vegetarian","Jain","Gluten-Free"]}
    ]
    render_crud_table("employees", ["emp_id","name","department","status"], ["emp_id","name","department","status"], form_fields, fetch, insert, update, delete, key_field="emp_id", title_field="name")

# -------------------- Raw Materials --------------------
def raw_materials_management():
    st.header("Raw Materials")
    def fetch(): return get_raw_materials()
    def insert(data):
        try:
            supabase.table("raw_materials").insert(data).execute()
            # create stock entry
            stock = supabase.table("stock").select("*").eq("item", data["name"]).execute()
            if not stock.data:
                supabase.table("stock").insert({"item": data["name"], "quantity": 0, "unit": data["unit"]}).execute()
            log_audit("Add Raw Material", data["name"])
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(str(e))
            return False
    def update(id, data):
        try:
            supabase.table("raw_materials").update(data).eq("id", id).execute()
            supabase.table("stock").update({"unit": data["unit"]}).eq("item", data["name"]).execute()
            log_audit("Update Raw Material", data["name"])
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(str(e))
            return False
    def delete(id):
        try:
            item = supabase.table("raw_materials").select("name").eq("id", id).execute().data[0]["name"]
            supabase.table("stock").delete().eq("item", item).execute()
            supabase.table("raw_materials").delete().eq("id", id).execute()
            log_audit("Delete Raw Material", item)
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(str(e))
            return False
    form_fields = [
        {"name": "name", "label": "Item Name", "type": "text"},
        {"name": "unit", "label": "Unit", "type": "select", "options": ["KG","Liter","Pieces"]},
        {"name": "current_rate", "label": "Current Rate (Rs)", "type": "number"},
        {"name": "reorder_level", "label": "Reorder Level", "type": "number"}
    ]
    render_crud_table("raw_materials", ["id","name","unit","current_rate","reorder_level"], ["name","unit","current_rate","reorder_level"], form_fields, fetch, insert, update, delete, title_field="name")

# -------------------- Recipes Management (Fixed) --------------------
def recipes_management():
    st.header("Recipes")
    raw_materials = get_raw_materials()
    item_options = [rm["name"] for rm in raw_materials] if raw_materials else []

    # Initialize session state for ingredients if not present
    if "ingredients" not in st.session_state:
        st.session_state.ingredients = [{"item": "", "qty": 0.0, "unit": "g"}]

    # Buttons to add/clear ingredients
    col1, col2 = st.columns(2)
    with col1:
        if st.button("➕ Add Ingredient"):
            st.session_state.ingredients.append({"item": "", "qty": 0.0, "unit": "g"})
            st.rerun()
    with col2:
        if st.button("🗑️ Clear All"):
            st.session_state.ingredients = [{"item": "", "qty": 0.0, "unit": "g"}]
            st.rerun()

    # Display ingredient rows
    st.write("---")
    total_cost = 0.0
    for i, ing in enumerate(st.session_state.ingredients):
        cols = st.columns([4, 2, 2, 1])
        with cols[0]:
            # Dropdown for item
            default_index = 0
            if ing["item"] in item_options:
                default_index = item_options.index(ing["item"])
            selected_item = st.selectbox(
                f"Item {i+1}",
                options=item_options,
                index=default_index,
                key=f"item_{i}"
            )
            st.session_state.ingredients[i]["item"] = selected_item
        with cols[1]:
            qty = st.number_input(
                f"Qty {i+1}",
                min_value=0.0,
                step=0.1,
                value=ing["qty"],
                key=f"qty_{i}",
                format="%.2f"
            )
            st.session_state.ingredients[i]["qty"] = qty
        with cols[2]:
            unit = st.selectbox(
                f"Unit {i+1}",
                ["g", "ml", "pcs"],
                index=["g", "ml", "pcs"].index(ing["unit"]),
                key=f"unit_{i}"
            )
            st.session_state.ingredients[i]["unit"] = unit
        with cols[3]:
            if i > 0 and st.button("❌", key=f"remove_{i}"):
                st.session_state.ingredients.pop(i)
                st.rerun()

        # Calculate ingredient cost contribution (real‑time)
        if selected_item and qty > 0:
            # Find current rate of the selected raw material
            rate_data = supabase.table("raw_materials").select("current_rate").eq("name", selected_item).execute().data
            if rate_data:
                rate = rate_data[0]["current_rate"]
                qty_kg = qty / 1000 if unit in ["g", "ml"] else qty
                cost_contrib = rate * qty_kg
                total_cost += cost_contrib
                st.caption(f"Cost: Rs {cost_contrib:.2f}")
    st.write("---")

    # Recipe name and selling price
    dish_name = st.text_input("Dish Name")
    # Show total cost
    st.metric("Total Cost per Plate", f"Rs {total_cost:.2f}")
    selling_price = st.number_input("Selling Price", min_value=0.0, step=0.01, format="%.2f")

    if st.button("💾 Save Recipe"):
        # Prepare ingredients list (only those with item and qty > 0)
        valid_ingredients = [ing for ing in st.session_state.ingredients if ing["item"] and ing["qty"] > 0]
        if not valid_ingredients:
            st.error("At least one valid ingredient required.")
        elif not dish_name:
            st.error("Dish name required.")
        elif selling_price <= 0:
            st.error("Selling price must be greater than zero.")
        else:
            # Calculate final cost (using the same logic, but we already have total_cost)
            # Insert into database
            try:
                data = {
                    "dish_name": dish_name,
                    "ingredients": json.dumps(valid_ingredients),
                    "selling_price": selling_price,
                    "cost_per_plate": total_cost
                }
                supabase.table("recipes").insert(data).execute()
                st.success("Recipe saved!")
                # Clear the form
                st.session_state.ingredients = [{"item": "", "qty": 0.0, "unit": "g"}]
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Error saving recipe: {e}")

    st.write("---")
    st.subheader("Existing Recipes")
    recipes = get_recipes()
    if recipes:
        df = pd.DataFrame(recipes)
        search = st.text_input("🔍 Search Recipes").lower()
        if search:
            df = df[df['dish_name'].str.lower().str.contains(search)]
        st.dataframe(df[["dish_name", "selling_price", "cost_per_plate"]], use_container_width=True)
        for _, row in df.iterrows():
            with st.expander(f"{row['dish_name']} - Rs {row['selling_price']}"):
                st.write(f"**Cost per plate:** Rs {row['cost_per_plate']:.2f}")
                st.write("**Ingredients:**")
                for ing in json.loads(row['ingredients']):
                    st.write(f"- {ing['item']}: {ing['qty']}{ing['unit']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✏️ Edit", key=f"edit_{row['id']}"):
                        st.info("Edit feature coming soon.")
                with col2:
                    if st.button("🗑️ Delete", key=f"delete_{row['id']}"):
                        supabase.table("recipes").delete().eq("id", row['id']).execute()
                        st.success("Deleted")
                        st.cache_data.clear()
                        st.rerun()
        # Export links
        st.markdown(get_csv_download_link(df[["dish_name", "selling_price", "cost_per_plate"]], "recipes.csv"), unsafe_allow_html=True)
        st.markdown(get_excel_download_link(df[["dish_name", "selling_price", "cost_per_plate"]], "recipes.xlsx"), unsafe_allow_html=True)

# -------------------- Purchases Management (with dropdown) --------------------
def purchases_management():
    st.header("Purchases")
    raw_materials = get_raw_materials()
    item_options = [rm["name"] for rm in raw_materials] if raw_materials else []
    
    def fetch(): return supabase.table("purchases").select("*").order("date", desc=True).execute().data
    def insert(data):
        try:
            data["total"] = data["quantity"] * data["rate"]
            supabase.table("purchases").insert(data).execute()
            # update stock
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
            # update raw material rate
            supabase.table("raw_materials").update({"current_rate": data["rate"]}).eq("name", data["item"]).execute()
            log_audit("Add Purchase", f"{data['item']} {data['quantity']}{data['unit']}")
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(str(e))
            return False
    def update(id, data):
        try:
            supabase.table("purchases").update(data).eq("id", id).execute()
            st.warning("Purchase updated. Stock was not automatically adjusted; please check manually.")
            log_audit("Update Purchase", str(id))
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(str(e))
            return False
    def delete(id):
        try:
            supabase.table("purchases").delete().eq("id", id).execute()
            log_audit("Delete Purchase", str(id))
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(str(e))
            return False
    form_fields = [
        {"name": "date", "label": "Date", "type": "date"},
        {"name": "item", "label": "Item", "type": "select", "options": item_options},
        {"name": "quantity", "label": "Quantity", "type": "number"},
        {"name": "unit", "label": "Unit", "type": "select", "options": ["KG","Liter","Pieces"]},
        {"name": "rate", "label": "Rate (Rs)", "type": "number"},
        {"name": "supplier", "label": "Supplier", "type": "text"}
    ]
    render_crud_table("purchases", ["id","date","item","quantity","unit","rate","total","supplier"], ["date","item","quantity","unit","rate","total","supplier"], form_fields, fetch, insert, update, delete, title_field="item")

# -------------------- Monthly Ration --------------------
def monthly_ration_management():
    st.header("Monthly Ration")
    def fetch(): return supabase.table("monthly_ration").select("*").order("month", desc=True).execute().data
    def insert(data):
        try:
            supabase.table("monthly_ration").insert(data).execute()
            log_audit("Add Monthly Ration", f"{data['month']} {data['item']}")
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(str(e))
            return False
    def update(id, data):
        try:
            supabase.table("monthly_ration").update(data).eq("id", id).execute()
            log_audit("Update Monthly Ration", str(id))
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(str(e))
            return False
    def delete(id):
        try:
            supabase.table("monthly_ration").delete().eq("id", id).execute()
            log_audit("Delete Monthly Ration", str(id))
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(str(e))
            return False
    form_fields = [
        {"name": "month", "label": "Month (YYYY-MM)", "type": "text"},
        {"name": "item", "label": "Item", "type": "text"},
        {"name": "target_qty", "label": "Target Quantity", "type": "number"},
        {"name": "unit", "label": "Unit", "type": "select", "options": ["KG","Liter","Pieces"]}
    ]
    render_crud_table("monthly_ration", ["id","month","item","target_qty","unit"], ["month","item","target_qty","unit"], form_fields, fetch, insert, update, delete, title_field="item")

# -------------------- Receiver --------------------
def receive_material_page():
    st.header("Receive Material")
    with st.form("receive_form", clear_on_submit=True):
        date = st.date_input("Date", datetime.date.today())
        item = st.text_input("Item")
        month = get_current_month()
        ration = supabase.table("monthly_ration").select("target_qty").eq("month", month).eq("item", item).execute().data
        expected = ration[0]["target_qty"] if ration else 0.0
        st.info(f"Expected this month: {expected}")
        expected_input = st.number_input("Expected Quantity", value=expected, min_value=0.0, step=0.01, format="%.2f")
        received = st.number_input("Received Quantity", min_value=0.0, step=0.01, format="%.2f")
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
                # update stock
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
                st.cache_data.clear()
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
    recipes = get_recipes()
    if not recipes:
        st.warning("No recipes found")
        return
    production_data = []
    for r in recipes:
        persons = st.number_input(f"Persons for {r['dish_name']}", min_value=0, step=1, key=r['id'])
        if persons > 0:
            production_data.append({"dish": r['dish_name'], "persons": persons})
    if st.button("Check Stock & Confirm"):
        with st.spinner("Checking stock..."):
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
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(f"Insufficient stock for items: {', '.join(set(insufficient_items))}")

def production_page():
    st.header("Today's Production")
    today = datetime.date.today().isoformat()
    prods = supabase.table("production").select("*").eq("date", today).execute().data
    if prods:
        st.dataframe(pd.DataFrame(prods), use_container_width=True)

def wastage_page():
    st.header("Wastage Entry")
    with st.form("wastage_form", clear_on_submit=True):
        date = st.date_input("Date", datetime.date.today())
        item = st.text_input("Item/Dish")
        qty = st.number_input("Quantity", min_value=0.0, step=0.01, format="%.2f")
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
    fig = px.bar(avg_rating, x="dish", y="rating", title="Dish Ratings", color="dish")
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
        payment = st.radio("Payment Status", ["PAID","UNPAID"], horizontal=True)
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
            st.cache_data.clear()
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
        st.markdown(get_excel_download_link(df, "today_sales.xlsx"), unsafe_allow_html=True)
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
            with st.form("feedback_form", clear_on_submit=True):
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
                    st.success("Thank you! You earned 10 points.")
                    log_audit("Feedback", f"{emp_id} {dish}")
                    st.cache_data.clear()
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
            st.markdown(get_csv_download_link(df, f"feedback_{emp_id}.csv"), unsafe_allow_html=True)
            st.markdown(get_excel_download_link(df, f"feedback_{emp_id}.xlsx"), unsafe_allow_html=True)
        else:
            st.info("No feedback yet")

def my_points():
    st.header("My Loyalty Points")
    emp_id = st.text_input("Employee ID")
    if emp_id:
        points = get_employee_points(emp_id)
        st.metric("Total Points", points)

# -------------------- Monthly Ration Analysis --------------------
def monthly_ration_analysis():
    st.header("Monthly Ration Analysis")
    months = get_available_months()
    if not months:
        st.info("No monthly ration data available")
        return
    month = st.selectbox("Select Month", months)
    if not month:
        return

    target_data = supabase.table("monthly_ration").select("*").eq("month", month).execute().data
    if not target_data:
        st.warning(f"No target set for {month}")
        return

    year, month_num = map(int, month.split('-'))
    last_day = calendar.monthrange(year, month_num)[1]
    start_date = f"{month}-01"
    end_date = f"{month}-{last_day}"
    productions = supabase.table("production").select("*").gte("date", start_date).lte("date", end_date).execute().data

    consumption = {}
    for prod in productions:
        ingredients = json.loads(prod['raw_material_used'])
        for ing in ingredients:
            qty = ing['qty'] * prod['persons']
            if ing['unit'] == 'g':
                qty = qty / 1000
            elif ing['unit'] == 'ml':
                qty = qty / 1000
            consumption[ing['item']] = consumption.get(ing['item'], 0) + qty

    stock_data = get_all_stock()
    stock_map = {s['item']: s['quantity'] for s in stock_data}

    report = []
    for target in target_data:
        item = target['item']
        target_qty = target['target_qty']
        consumed = consumption.get(item, 0)
        remaining = target_qty - consumed
        current_stock = stock_map.get(item, 0)
        report.append({
            "Item": item,
            "Target (kg/ltr)": target_qty,
            "Consumed (kg/ltr)": round(consumed, 2),
            "Remaining from Target": round(remaining, 2),
            "Current Stock": current_stock,
            "Stock vs Target": round(current_stock - remaining, 2)
        })

    df = pd.DataFrame(report)
    st.dataframe(df, use_container_width=True)

    fig = px.bar(df, x="Item", y=["Consumed (kg/ltr)", "Remaining from Target"], barmode="group",
                 title=f"Monthly Ration Consumption - {month}")
    st.plotly_chart(fig, use_container_width=True)

    # Export
    st.markdown(get_csv_download_link(df, f"monthly_ration_{month}.csv"), unsafe_allow_html=True)
    st.markdown(get_excel_download_link(df, f"monthly_ration_{month}.xlsx"), unsafe_allow_html=True)
    if st.button("📥 Download PDF Report"):
        pdf_bytes = generate_professional_pdf(
            title=f"Monthly Ration Analysis - {month}",
            data=df.values.tolist(),
            headers=df.columns.tolist(),
            filename=f"monthly_ration_{month}.pdf",
            landscape=True,
            logo_url=get_logo_url(),
            company_name=get_settings().get("company_name", "")
        )
        st.markdown(get_pdf_download_link(pdf_bytes, f"monthly_ration_{month}.pdf"), unsafe_allow_html=True)

# -------------------- Employee Details Report --------------------
def employee_details_report():
    st.header("Employee Details Report")
    employees = get_employees_all()
    if not employees:
        st.info("No employees found")
        return
    df = pd.DataFrame(employees)
    # Filter by department
    depts = df['department'].unique()
    selected_dept = st.selectbox("Filter by Department", ["All"] + list(depts))
    if selected_dept != "All":
        df = df[df['department'] == selected_dept]
    st.dataframe(df, use_container_width=True)
    st.markdown(get_csv_download_link(df, "employee_details.csv"), unsafe_allow_html=True)
    st.markdown(get_excel_download_link(df, "employee_details.xlsx"), unsafe_allow_html=True)
    if st.button("📥 Download PDF Report"):
        pdf_bytes = generate_professional_pdf(
            title="Employee Details Report",
            data=df.values.tolist(),
            headers=df.columns.tolist(),
            filename="employee_details.pdf",
            landscape=True,
            logo_url=get_logo_url(),
            company_name=get_settings().get("company_name", "")
        )
        st.markdown(get_pdf_download_link(pdf_bytes, "employee_details.pdf"), unsafe_allow_html=True)

# -------------------- Inventory Report --------------------
def inventory_report():
    st.header("Inventory Report")
    stock = get_all_stock()
    raw_materials = get_raw_materials()
    if not stock:
        st.info("No stock data")
        return
    # Merge with raw materials to get rates
    df_stock = pd.DataFrame(stock)
    df_raw = pd.DataFrame(raw_materials)
    merged = pd.merge(df_stock, df_raw[['name','current_rate','reorder_level']], left_on='item', right_on='name', how='left')
    merged['value'] = merged['quantity'] * merged['current_rate']
    merged['status'] = merged.apply(lambda row: 'Low Stock' if row['quantity'] <= row['reorder_level'] else 'OK', axis=1)
    display_cols = ['item', 'quantity', 'unit', 'current_rate', 'value', 'reorder_level', 'status', 'last_updated']
    st.dataframe(merged[display_cols], use_container_width=True)
    st.markdown(get_csv_download_link(merged[display_cols], "inventory_report.csv"), unsafe_allow_html=True)
    st.markdown(get_excel_download_link(merged[display_cols], "inventory_report.xlsx"), unsafe_allow_html=True)
    if st.button("📥 Download PDF Report"):
        pdf_bytes = generate_professional_pdf(
            title="Inventory Report",
            data=merged[display_cols].values.tolist(),
            headers=display_cols,
            filename="inventory_report.pdf",
            landscape=True,
            logo_url=get_logo_url(),
            company_name=get_settings().get("company_name", "")
        )
        st.markdown(get_pdf_download_link(pdf_bytes, "inventory_report.pdf"), unsafe_allow_html=True)

# -------------------- Custom Report Builder --------------------
def custom_report_builder():
    st.header("Custom Report Builder")
    tables = {
        "Sales": supabase.table("sales").select("*").execute().data,
        "Purchases": supabase.table("purchases").select("*").execute().data,
        "Production": supabase.table("production").select("*").execute().data,
        "Wastage": supabase.table("wastage").select("*").execute().data,
        "Feedback": supabase.table("feedback").select("*").execute().data,
        "Employees": supabase.table("employees").select("*").execute().data,
        "Raw Materials": supabase.table("raw_materials").select("*").execute().data,
        "Stock": supabase.table("stock").select("*").execute().data,
        "Monthly Ration": supabase.table("monthly_ration").select("*").execute().data,
    }
    selected_table = st.selectbox("Select Table", list(tables.keys()))
    if selected_table:
        data = tables[selected_table]
        if not data:
            st.info("No data in this table")
            return
        df = pd.DataFrame(data)
        # Column selection
        all_columns = df.columns.tolist()
        selected_columns = st.multiselect("Select Columns to Display", all_columns, default=all_columns[:5])
        if not selected_columns:
            st.warning("Please select at least one column")
            return
        df_display = df[selected_columns]
        # Filters (simple text filter on first column)
        filter_col = st.selectbox("Filter by Column (optional)", ["None"] + selected_columns)
        if filter_col != "None":
            filter_val = st.text_input(f"Filter value for {filter_col}")
            if filter_val:
                df_display = df_display[df_display[filter_col].astype(str).str.contains(filter_val, case=False)]
        st.dataframe(df_display, use_container_width=True)
        # Export
        st.markdown(get_csv_download_link(df_display, f"custom_report.csv"), unsafe_allow_html=True)
        st.markdown(get_excel_download_link(df_display, f"custom_report.xlsx"), unsafe_allow_html=True)
        if st.button("📥 Download PDF Report"):
            pdf_bytes = generate_professional_pdf(
                title=f"Custom Report - {selected_table}",
                data=df_display.values.tolist(),
                headers=df_display.columns.tolist(),
                filename="custom_report.pdf",
                landscape=True,
                logo_url=get_logo_url(),
                company_name=get_settings().get("company_name", "")
            )
            st.markdown(get_pdf_download_link(pdf_bytes, "custom_report.pdf"), unsafe_allow_html=True)

# -------------------- Advanced Reports --------------------
def reports_page():
    st.header("Advanced Reports")
    report_type = st.selectbox("Report Type", [
        "Sales Overview",
        "Dish Popularity",
        "Employee Consumption",
        "Wastage Trend",
        "Profit Margin Trend",
        "Monthly Ration Analysis",
        "Employee Details",
        "Inventory Report",
        "Custom Report"
    ])
    if report_type == "Monthly Ration Analysis":
        monthly_ration_analysis()
        return
    elif report_type == "Employee Details":
        employee_details_report()
        return
    elif report_type == "Inventory Report":
        inventory_report()
        return
    elif report_type == "Custom Report":
        custom_report_builder()
        return
    start = st.date_input("Start Date")
    end = st.date_input("End Date")
    if st.button("Generate Report"):
        with st.spinner("Generating report..."):
            if report_type == "Sales Overview":
                sales = get_sales_range(start.isoformat(), end.isoformat())
                if sales:
                    df = pd.DataFrame(sales)
                    st.subheader("Sales Data")
                    st.dataframe(df[["date","order_id","emp_id","total","payment_status"]], use_container_width=True)
                    sales_by_date = df.groupby("date")["total"].sum().reset_index()
                    fig = px.line(sales_by_date, x="date", y="total", title="Sales Trend")
                    st.plotly_chart(fig, use_container_width=True)
                    payment_counts = df["payment_status"].value_counts().reset_index()
                    payment_counts.columns = ["Status","Count"]
                    fig2 = px.pie(payment_counts, values="Count", names="Status", title="Payment Status")
                    st.plotly_chart(fig2, use_container_width=True)
                    # PDF
                    if st.button("📥 Download PDF Report (Sales)"):
                        pdf_bytes = generate_professional_pdf(
                            title=f"Sales Report {start} to {end}",
                            data=df[["date","order_id","emp_id","total","payment_status"]].values.tolist(),
                            headers=["Date","Order ID","Employee","Total","Status"],
                            filename="sales_report.pdf",
                            landscape=True,
                            logo_url=get_logo_url(),
                            company_name=get_settings().get("company_name", "")
                        )
                        st.markdown(get_pdf_download_link(pdf_bytes, "sales_report.pdf"), unsafe_allow_html=True)
                else:
                    st.info("No sales data for selected period")

            elif report_type == "Dish Popularity":
                sales = get_sales_range(start.isoformat(), end.isoformat())
                if sales:
                    dish_counts = {}
                    for sale in sales:
                        items = json.loads(sale["items"])
                        for dish, qty in items.items():
                            dish_counts[dish] = dish_counts.get(dish, 0) + qty
                    df = pd.DataFrame(list(dish_counts.items()), columns=["Dish","Quantity Sold"])
                    df = df.sort_values("Quantity Sold", ascending=False)
                    st.subheader("Dish Popularity")
                    fig = px.bar(df, x="Dish", y="Quantity Sold", title="Dish Popularity", color="Dish")
                    st.plotly_chart(fig, use_container_width=True)
                    st.dataframe(df, use_container_width=True)
                    st.markdown(get_csv_download_link(df, "dish_popularity.csv"), unsafe_allow_html=True)
                    st.markdown(get_excel_download_link(df, "dish_popularity.xlsx"), unsafe_allow_html=True)
                    if st.button("📥 Download PDF Report"):
                        pdf_bytes = generate_professional_pdf(
                            title=f"Dish Popularity {start} to {end}",
                            data=df.values.tolist(),
                            headers=["Dish","Quantity Sold"],
                            filename="dish_popularity.pdf",
                            landscape=False,
                            logo_url=get_logo_url(),
                            company_name=get_settings().get("company_name", "")
                        )
                        st.markdown(get_pdf_download_link(pdf_bytes, "dish_popularity.pdf"), unsafe_allow_html=True)
                else:
                    st.info("No sales data")

            elif report_type == "Employee Consumption":
                sales = get_sales_range(start.isoformat(), end.isoformat())
                if sales:
                    emp_counts = {}
                    for sale in sales:
                        emp = sale["emp_id"]
                        emp_counts[emp] = emp_counts.get(emp, 0) + 1
                    df = pd.DataFrame(list(emp_counts.items()), columns=["Employee","Meals"])
                    df = df.sort_values("Meals", ascending=False)
                    st.subheader("Employee Meal Count")
                    fig = px.bar(df, x="Employee", y="Meals", title="Employee Meal Count")
                    st.plotly_chart(fig, use_container_width=True)
                    st.dataframe(df, use_container_width=True)
                    st.markdown(get_csv_download_link(df, "employee_meals.csv"), unsafe_allow_html=True)
                    if st.button("📥 Download PDF Report"):
                        pdf_bytes = generate_professional_pdf(
                            title=f"Employee Consumption {start} to {end}",
                            data=df.values.tolist(),
                            headers=["Employee","Meals"],
                            filename="employee_consumption.pdf",
                            landscape=False,
                            logo_url=get_logo_url(),
                            company_name=get_settings().get("company_name", "")
                        )
                        st.markdown(get_pdf_download_link(pdf_bytes, "employee_consumption.pdf"), unsafe_allow_html=True)
                else:
                    st.info("No sales data")

            elif report_type == "Wastage Trend":
                wastage = get_wastage_range(start.isoformat(), end.isoformat())
                if wastage:
                    df = pd.DataFrame(wastage)
                    wastage_by_date = df.groupby("date")["quantity"].sum().reset_index()
                    fig = px.line(wastage_by_date, x="date", y="quantity", title="Wastage Trend")
                    st.plotly_chart(fig, use_container_width=True)
                    wastage_by_reason = df.groupby("reason")["quantity"].sum().reset_index()
                    fig2 = px.pie(wastage_by_reason, values="quantity", names="reason", title="Wastage by Reason")
                    st.plotly_chart(fig2, use_container_width=True)
                    st.dataframe(df, use_container_width=True)
                    st.markdown(get_csv_download_link(df, "wastage_report.csv"), unsafe_allow_html=True)
                    if st.button("📥 Download PDF Report"):
                        pdf_bytes = generate_professional_pdf(
                            title=f"Wastage Report {start} to {end}",
                            data=df[["date","item","quantity","unit","reason"]].values.tolist(),
                            headers=["Date","Item","Quantity","Unit","Reason"],
                            filename="wastage_report.pdf",
                            landscape=True,
                            logo_url=get_logo_url(),
                            company_name=get_settings().get("company_name", "")
                        )
                        st.markdown(get_pdf_download_link(pdf_bytes, "wastage_report.pdf"), unsafe_allow_html=True)
                else:
                    st.info("No wastage data")

            elif report_type == "Profit Margin Trend":
                sales = get_sales_range(start.isoformat(), end.isoformat())
                purchases = get_purchases_range(start.isoformat(), end.isoformat())
                if sales and purchases:
                    sales_df = pd.DataFrame(sales)
                    purchases_df = pd.DataFrame(purchases)
                    sales_by_date = sales_df.groupby("date")["total"].sum().reset_index()
                    purchases_by_date = purchases_df.groupby("date")["total"].sum().reset_index()
                    merged = pd.merge(sales_by_date, purchases_by_date, on="date", how="outer").fillna(0)
                    merged["profit"] = merged["total_x"] - merged["total_y"]
                    merged["margin"] = (merged["profit"] / merged["total_x"] * 100).fillna(0)
                    fig = px.line(merged, x="date", y="profit", title="Daily Profit Trend")
                    st.plotly_chart(fig, use_container_width=True)
                    fig2 = px.line(merged, x="date", y="margin", title="Daily Profit Margin %")
                    st.plotly_chart(fig2, use_container_width=True)
                    st.dataframe(merged, use_container_width=True)
                    st.markdown(get_csv_download_link(merged, "profit_margin.csv"), unsafe_allow_html=True)
                    if st.button("📥 Download PDF Report"):
                        pdf_bytes = generate_professional_pdf(
                            title=f"Profit Margin Report {start} to {end}",
                            data=merged.values.tolist(),
                            headers=["Date","Revenue","Cost","Profit","Margin %"],
                            filename="profit_margin.pdf",
                            landscape=True,
                            logo_url=get_logo_url(),
                            company_name=get_settings().get("company_name", "")
                        )
                        st.markdown(get_pdf_download_link(pdf_bytes, "profit_margin.pdf"), unsafe_allow_html=True)
                else:
                    st.info("Insufficient data")

# -------------------- Settings --------------------
def settings_page():
    st.header("System Settings")
    settings = supabase.table("settings").select("*").execute().data
    settings_dict = {s["key"]: s["value"] for s in settings}
    with st.form("settings_form"):
        app_name = st.text_input("App Name", settings_dict.get("app_name", ""))
        company = st.text_input("Company Name", settings_dict.get("company_name", ""))
        color = st.color_picker("Primary Color", settings_dict.get("primary_color", "#3498db"))
        date_fmt = st.selectbox("Date Format", ["DD-MM-YYYY","MM-DD-YYYY","YYYY-MM-DD"], index=0)
        logo_file = st.file_uploader("Upload Logo", type=["png","jpg","jpeg"])
        if st.form_submit_button("Save"):
            logo_url = settings_dict.get("logo_url", "")
            if logo_file:
                file_bytes = logo_file.read()
                file_name = f"logo_{int(time.time())}.png"
                supabase.storage.from_("logos").upload(file_name, file_bytes, {"content-type": logo_file.type})
                logo_url = file_name
            updates = [("app_name", app_name), ("company_name", company), ("primary_color", color), ("date_format", date_fmt), ("logo_url", logo_url)]
            for key, val in updates:
                supabase.table("settings").upsert({"key": key, "value": val}).execute()
            st.success("Settings saved")
            log_audit("Settings", "Updated")
            st.cache_data.clear()
            st.rerun()

# -------------------- Audit Log --------------------
def audit_page():
    st.header("Audit Log")
    logs = supabase.table("audit_log").select("*").order("timestamp", desc=True).limit(100).execute().data
    if logs:
        df = pd.DataFrame(logs)
        st.dataframe(df, use_container_width=True)
        st.markdown(get_csv_download_link(df, "audit_log.csv"), unsafe_allow_html=True)
        st.markdown(get_excel_download_link(df, "audit_log.xlsx"), unsafe_allow_html=True)

# -------------------- Main --------------------
def main():
    if st.session_state.user is None:
        login_page()
    else:
        dashboard()

if __name__ == "__main__":
    main()
