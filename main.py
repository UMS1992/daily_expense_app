# expense_tracker_hybrid_fixed.py
import streamlit as st
import pandas as pd
from datetime import datetime, date
import os
import plotly.express as px
import plotly.graph_objects as go
import hashlib
import time
import sqlite3
import json
import calendar
from pathlib import Path

# Must be the first Streamlit command
st.set_page_config(
    page_title="Hybrid Expense Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.user = None
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.offline_mode = False
    st.session_state.last_sync = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.sync_status = "No sync yet"
    st.session_state.pending_changes = 0
    st.session_state.current_page = "Dashboard"
    st.session_state.show_connection_setup = False

# File paths
EXCEL_FILE = "expenses_data.xlsx"
USERS_FILE = "users.xlsx"
SYNC_DB = "sync_status.db"
MYSQL_CONFIG = "mysql_config.json"

# Define all categories
CATEGORIES = [
    'Rent', 'Transportation', 'Laundry', 'Water', 'Offer', 'Internet',
    'Lottery', 'Health Care', 'Food', 'Snacks', 'Clothing/Cosmetic',
    'Education/Knowledge', 'Entertainment', 'Social', 'Home/Family',
    'N.T/S.T', 'Others'
]

# Custom CSS
st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        color: #2E86C1;
        text-align: center;
        margin-bottom: 2rem;
    }
    .sub-header {
        font-size: 1.5rem;
        color: #2874A6;
        margin-bottom: 1rem;
    }
    .total-amount {
        font-size: 2rem;
        color: #27AE60;
        font-weight: bold;
        text-align: center;
    }
    .login-box {
        background-color: #f0f2f6;
        padding: 2rem;
        border-radius: 10px;
        margin: 2rem auto;
        max-width: 400px;
    }
    .stButton > button {
        width: 100%;
    }
    .success-msg {
        color: #27AE60;
        font-weight: bold;
    }
    .error-msg {
        color: #E74C3C;
        font-weight: bold;
    }
    .info-box {
        background-color: #e1f5fe;
        padding: 1rem;
        border-radius: 5px;
        margin: 1rem 0;
    }
    .sync-status {
        padding: 0.5rem;
        border-radius: 5px;
        margin: 0.5rem 0;
    }
    .online {
        background-color: #d4edda;
        color: #155724;
    }
    .offline {
        background-color: #fff3cd;
        color: #856404;
    }
    </style>
""", unsafe_allow_html=True)


# ============================================
# SYNC DATABASE (SQLite for tracking changes)
# ============================================

def init_sync_db():
    """Initialize sync tracking database"""
    conn = sqlite3.connect(SYNC_DB)
    c = conn.cursor()

    # Create sync status table
    c.execute('''
        CREATE TABLE IF NOT EXISTS sync_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT,
            record_id TEXT,
            operation TEXT,
            data TEXT,
            sync_status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            synced_at TIMESTAMP
        )
    ''')

    # Create sync log table
    c.execute('''
        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_time TIMESTAMP,
            records_synced INTEGER,
            status TEXT
        )
    ''')

    conn.commit()
    conn.close()


def add_pending_change(table_name, record_id, operation, data):
    """Add a pending change to sync queue"""
    conn = sqlite3.connect(SYNC_DB)
    c = conn.cursor()
    c.execute('''
        INSERT INTO sync_status (table_name, record_id, operation, data, sync_status)
        VALUES (?, ?, ?, ?, 'pending')
    ''', (table_name, str(record_id), operation, json.dumps(data, default=str)))
    conn.commit()
    conn.close()
    st.session_state.pending_changes = get_pending_count()


def get_pending_count():
    """Get count of pending changes"""
    conn = sqlite3.connect(SYNC_DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM sync_status WHERE sync_status = 'pending'")
    count = c.fetchone()[0]
    conn.close()
    return count


def get_pending_changes():
    """Get all pending changes"""
    conn = sqlite3.connect(SYNC_DB)
    c = conn.cursor()
    c.execute("SELECT * FROM sync_status WHERE sync_status = 'pending' ORDER BY created_at")
    changes = c.fetchall()
    conn.close()
    return changes


def mark_as_synced(change_id):
    """Mark a change as synced"""
    conn = sqlite3.connect(SYNC_DB)
    c = conn.cursor()
    c.execute('''
        UPDATE sync_status 
        SET sync_status = 'synced', synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (change_id,))
    conn.commit()
    conn.close()


def log_sync(records_synced, status):
    """Log sync operation"""
    conn = sqlite3.connect(SYNC_DB)
    c = conn.cursor()
    c.execute('''
        INSERT INTO sync_log (sync_time, records_synced, status)
        VALUES (CURRENT_TIMESTAMP, ?, ?)
    ''', (records_synced, status))
    conn.commit()
    conn.close()


# Initialize sync database
init_sync_db()
st.session_state.pending_changes = get_pending_count()


# ============================================
# MYSQL CONFIGURATION
# ============================================

def load_mysql_config():
    """Load MySQL configuration"""
    default_config = {
        "host": "localhost",
        "user": "root",
        "password": "",
        "database": "expense_tracker",
        "port": 3306,
        "connected": False
    }

    if os.path.exists(MYSQL_CONFIG):
        try:
            with open(MYSQL_CONFIG, 'r') as f:
                return json.load(f)
        except:
            return default_config
    else:
        with open(MYSQL_CONFIG, 'w') as f:
            json.dump(default_config, f, indent=4)
        return default_config


def save_mysql_config(config):
    """Save MySQL configuration"""
    with open(MYSQL_CONFIG, 'w') as f:
        json.dump(config, f, indent=4)


def test_mysql_connection(config):
    """Test MySQL connection"""
    try:
        import mysql.connector
        conn = mysql.connector.connect(
            host=config['host'],
            user=config['user'],
            password=config['password'],
            database=config['database'],
            port=config['port'],
            connection_timeout=5
        )
        conn.close()
        return True, "Connected successfully"
    except ImportError:
        return False, "mysql-connector-python not installed. Run: pip install mysql-connector-python"
    except Exception as e:
        return False, str(e)


def init_mysql_tables(config):
    """Initialize MySQL tables"""
    try:
        import mysql.connector
        conn = mysql.connector.connect(
            host=config['host'],
            user=config['user'],
            password=config['password'],
            database=config['database'],
            port=config['port']
        )
        cursor = conn.cursor()

        # Create users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(64) NOT NULL,
                email VARCHAR(100),
                full_name VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP NULL,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)

        # Create categories table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                category_id INT AUTO_INCREMENT PRIMARY KEY,
                category_name VARCHAR(50) UNIQUE NOT NULL,
                icon VARCHAR(10) DEFAULT '📌',
                budget_limit DECIMAL(10,2) DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)

        # Insert default categories if not exists
        default_categories = [
            ('Rent', '🏠'), ('Transportation', '🚗'), ('Laundry', '👕'),
            ('Water', '💧'), ('Offer', '🎁'), ('Internet', '🌐'),
            ('Lottery', '🎰'), ('Health Care', '🏥'), ('Food', '🍔'),
            ('Snacks', '🍪'), ('Clothing/Cosmetic', '👔'), ('Education/Knowledge', '📚'),
            ('Entertainment', '🎬'), ('Social', '👥'), ('Home/Family', '🏡'),
            ('N.T/S.T', '📦'), ('Others', '📌')
        ]

        for cat_name, icon in default_categories:
            cursor.execute("""
                INSERT IGNORE INTO categories (category_name, icon) 
                VALUES (%s, %s)
            """, (cat_name, icon))

        # Create expenses table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                expense_id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT,
                date DATE NOT NULL,
                category_id INT,
                amount DECIMAL(10,2) NOT NULL,
                description VARCHAR(200),
                payment_mode VARCHAR(50),
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (category_id) REFERENCES categories(category_id)
            )
        """)

        # Create payment_modes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_modes (
                mode_id INT AUTO_INCREMENT PRIMARY KEY,
                mode_name VARCHAR(50) UNIQUE NOT NULL
            )
        """)

        # Insert default payment modes
        payment_modes = ['Cash', 'Credit Card', 'Debit Card', 'UPI', 'Net Banking', 'Wallet']
        for mode in payment_modes:
            cursor.execute("""
                INSERT IGNORE INTO payment_modes (mode_name) VALUES (%s)
            """, (mode,))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"MySQL init error: {str(e)}")
        return False


# ============================================
# EXCEL FILE OPERATIONS
# ============================================

def init_excel_file():
    """Initialize Excel file if it doesn't exist"""
    if not os.path.exists(EXCEL_FILE):
        columns = ['expense_id', 'user_id', 'date', 'category_name', 'amount',
                   'description', 'payment_mode', 'notes', 'created_at', 'sync_status']
        df = pd.DataFrame(columns=columns)
        df.to_excel(EXCEL_FILE, index=False)
        return df
    else:
        return pd.read_excel(EXCEL_FILE)


def save_to_excel(df):
    """Save DataFrame to Excel"""
    df.to_excel(EXCEL_FILE, index=False)


def load_from_excel():
    """Load data from Excel"""
    if os.path.exists(EXCEL_FILE):
        return pd.read_excel(EXCEL_FILE)
    else:
        return init_excel_file()


# ============================================
# USER AUTHENTICATION FUNCTIONS
# ============================================

def init_users_file():
    """Initialize users Excel file"""
    if not os.path.exists(USERS_FILE):
        columns = ['user_id', 'username', 'password_hash', 'email', 'full_name', 'created_at']
        df = pd.DataFrame(columns=columns)
        df.to_excel(USERS_FILE, index=False)
        return df
    return pd.read_excel(USERS_FILE)


def hash_password(password):
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


def create_user(username, password, email=None, fullname=None):
    """Create a new user"""
    users_df = init_users_file()

    # Check if user exists
    if username in users_df['username'].values:
        return None

    new_id = 1 if users_df.empty else users_df['user_id'].max() + 1
    new_user = pd.DataFrame([{
        'user_id': new_id,
        'username': username,
        'password_hash': hash_password(password),
        'email': email,
        'full_name': fullname,
        'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }])

    users_df = pd.concat([users_df, new_user], ignore_index=True)
    users_df.to_excel(USERS_FILE, index=False)

    return new_id


def authenticate_user(username, password):
    """Authenticate user from Excel"""
    if not os.path.exists(USERS_FILE):
        return None

    users_df = pd.read_excel(USERS_FILE)
    user = users_df[users_df['username'] == username]

    if not user.empty and user.iloc[0]['password_hash'] == hash_password(password):
        return (
            user.iloc[0]['user_id'],
            user.iloc[0]['username'],
            user.iloc[0]['full_name'],
            user.iloc[0]['email']
        )
    return None


# ============================================
# CATEGORY AND PAYMENT MODES FUNCTIONS
# ============================================

def get_categories():
    """Get list of categories"""
    return pd.DataFrame({
        'category_id': range(1, len(CATEGORIES) + 1),
        'category_name': CATEGORIES,
        'icon': ['🏠', '🚗', '👕', '💧', '🎁', '🌐', '🎰', '🏥', '🍔', '🍪', '👔', '📚', '🎬', '👥', '🏡', '📦', '📌']
    })


def get_payment_modes():
    """Get list of payment modes"""
    return ['Cash', 'Credit Card', 'Debit Card', 'UPI', 'Net Banking', 'Wallet', 'Google Pay', 'PhonePe', 'Paytm']


# ============================================
# HYBRID EXPENSE MANAGER
# ============================================

class HybridExpenseManager:
    def __init__(self):
        self.mysql_config = load_mysql_config()
        self.excel_df = load_from_excel()
        self.mysql_connected = False
        self.test_mysql_connection()

    def test_mysql_connection(self):
        """Test MySQL connection"""
        if self.mysql_config.get('connected', False):
            self.mysql_connected = True
            return True

        success, _ = test_mysql_connection(self.mysql_config)
        self.mysql_connected = success
        return success

    def add_expense(self, user_id, date_val, category_name, amount, description, payment_mode, notes):
        """Add expense to both Excel and MySQL if connected"""
        expense_data = {
            'date': date_val.strftime("%Y-%m-%d") if isinstance(date_val, date) else date_val,
            'category_name': category_name,
            'amount': amount,
            'description': description,
            'payment_mode': payment_mode,
            'notes': notes,
            'user_id': user_id,
            'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # Always save to Excel (offline storage)
        if self.excel_df.empty:
            new_id = 1
        else:
            new_id = self.excel_df['expense_id'].max() + 1

        expense_data['expense_id'] = new_id
        expense_data['sync_status'] = 'pending' if not self.mysql_connected else 'synced'

        new_row = pd.DataFrame([expense_data])
        self.excel_df = pd.concat([self.excel_df, new_row], ignore_index=True)
        save_to_excel(self.excel_df)

        # If MySQL connected, save there too
        if self.mysql_connected:
            if self.save_to_mysql(expense_data):
                # Update sync status in Excel
                self.excel_df.loc[self.excel_df['expense_id'] == new_id, 'sync_status'] = 'synced'
                save_to_excel(self.excel_df)
            else:
                # Add to sync queue
                add_pending_change('expenses', new_id, 'INSERT', expense_data)
        else:
            # Add to sync queue
            add_pending_change('expenses', new_id, 'INSERT', expense_data)

        return True

    def save_to_mysql(self, expense_data):
        """Save expense to MySQL"""
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=self.mysql_config['host'],
                user=self.mysql_config['user'],
                password=self.mysql_config['password'],
                database=self.mysql_config['database'],
                port=self.mysql_config['port']
            )
            cursor = conn.cursor()

            # Get category_id
            cursor.execute("SELECT category_id FROM categories WHERE category_name = %s",
                           (expense_data['category_name'],))
            cat_result = cursor.fetchone()
            if not cat_result:
                # Insert category if not exists
                cursor.execute("INSERT INTO categories (category_name) VALUES (%s)",
                               (expense_data['category_name'],))
                category_id = cursor.lastrowid
            else:
                category_id = cat_result[0]

            cursor.execute("""
                INSERT INTO expenses (user_id, date, category_id, amount, description, payment_mode, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                expense_data['user_id'],
                expense_data['date'],
                category_id,
                expense_data['amount'],
                expense_data['description'],
                expense_data['payment_mode'],
                expense_data['notes']
            ))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            st.error(f"MySQL save error: {str(e)}")
            return False

    def get_expenses(self, user_id, start_date=None, end_date=None, category=None):
        """Get expenses from Excel (always works offline)"""
        if self.excel_df.empty:
            return pd.DataFrame()

        df = self.excel_df[self.excel_df['user_id'] == user_id].copy()

        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])

            if start_date and end_date:
                mask = (df['date'].dt.date >= start_date) & (df['date'].dt.date <= end_date)
                df = df[mask]

            if category and category != 'All':
                df = df[df['category_name'] == category]

            df = df.sort_values('date', ascending=False)

        return df

    def update_expense(self, expense_id, date_val, category_name, amount, description, payment_mode, notes):
        """Update expense in Excel and queue for MySQL sync"""
        # Update in Excel
        mask = self.excel_df['expense_id'] == expense_id
        if mask.any():
            self.excel_df.loc[mask, 'date'] = date_val.strftime("%Y-%m-%d") if isinstance(date_val, date) else date_val
            self.excel_df.loc[mask, 'category_name'] = category_name
            self.excel_df.loc[mask, 'amount'] = amount
            self.excel_df.loc[mask, 'description'] = description
            self.excel_df.loc[mask, 'payment_mode'] = payment_mode
            self.excel_df.loc[mask, 'notes'] = notes
            self.excel_df.loc[mask, 'sync_status'] = 'pending'
            save_to_excel(self.excel_df)

            # Add to sync queue
            expense_data = self.excel_df.loc[mask].iloc[0].to_dict()
            add_pending_change('expenses', expense_id, 'UPDATE', expense_data)

            return True
        return False

    def delete_expense(self, expense_id):
        """Delete expense from Excel and queue for MySQL sync"""
        mask = self.excel_df['expense_id'] == expense_id
        if mask.any():
            expense_data = self.excel_df.loc[mask].iloc[0].to_dict()
            self.excel_df = self.excel_df[~mask].reset_index(drop=True)
            save_to_excel(self.excel_df)

            # Add to sync queue
            add_pending_change('expenses', expense_id, 'DELETE', expense_data)

            return True
        return False

    def sync_with_mysql(self):
        """Sync pending changes with MySQL"""
        if not self.test_mysql_connection():
            return False, "MySQL not connected"

        pending = get_pending_changes()
        if not pending:
            return True, "No pending changes"

        synced_count = 0
        errors = []

        for change in pending:
            change_id = change[0]
            table = change[1]
            record_id = change[2]
            operation = change[3]
            data_json = change[4]
            data = json.loads(data_json)

            try:
                if operation == 'INSERT':
                    self.save_to_mysql(data)
                elif operation == 'UPDATE':
                    self.update_in_mysql(record_id, data)
                elif operation == 'DELETE':
                    self.delete_from_mysql(record_id)

                mark_as_synced(change_id)
                synced_count += 1

                # Update Excel sync status
                if operation != 'DELETE':
                    mask = self.excel_df['expense_id'] == int(record_id)
                    if mask.any():
                        self.excel_df.loc[mask, 'sync_status'] = 'synced'
                        save_to_excel(self.excel_df)

            except Exception as e:
                errors.append(str(e))

        log_sync(synced_count, 'success' if not errors else 'partial')
        st.session_state.pending_changes = get_pending_count()
        st.session_state.last_sync = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if errors:
            return False, f"Synced {synced_count} records with {len(errors)} errors"
        else:
            return True, f"Successfully synced {synced_count} records"

    def update_in_mysql(self, record_id, data):
        """Update expense in MySQL"""
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=self.mysql_config['host'],
                user=self.mysql_config['user'],
                password=self.mysql_config['password'],
                database=self.mysql_config['database'],
                port=self.mysql_config['port']
            )
            cursor = conn.cursor()

            cursor.execute("SELECT category_id FROM categories WHERE category_name = %s",
                           (data['category_name'],))
            cat_result = cursor.fetchone()
            if not cat_result:
                cursor.execute("INSERT INTO categories (category_name) VALUES (%s)",
                               (data['category_name'],))
                category_id = cursor.lastrowid
            else:
                category_id = cat_result[0]

            cursor.execute("""
                UPDATE expenses 
                SET date = %s, category_id = %s, amount = %s, 
                    description = %s, payment_mode = %s, notes = %s
                WHERE expense_id = %s
            """, (
                data['date'], category_id, data['amount'],
                data['description'], data['payment_mode'], data['notes'],
                record_id
            ))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            raise e

    def delete_from_mysql(self, record_id):
        """Delete expense from MySQL"""
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=self.mysql_config['host'],
                user=self.mysql_config['user'],
                password=self.mysql_config['password'],
                database=self.mysql_config['database'],
                port=self.mysql_config['port']
            )
            cursor = conn.cursor()
            cursor.execute("DELETE FROM expenses WHERE expense_id = %s", (record_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            raise e


# Initialize hybrid manager
if 'expense_manager' not in st.session_state:
    st.session_state.expense_manager = HybridExpenseManager()


# ============================================
# UI PAGES
# ============================================

def show_connection_setup():
    st.markdown('<h1 class="main-header">🔌 MySQL Connection Setup</h1>', unsafe_allow_html=True)

    st.markdown('<div class="info-box">', unsafe_allow_html=True)
    st.info("""
    Configure MySQL connection for online sync. 
    - The app always works offline with Excel
    - MySQL sync happens when connection is available
    - Install mysql-connector-python: pip install mysql-connector-python
    """)
    st.markdown('</div>', unsafe_allow_html=True)

    config = st.session_state.expense_manager.mysql_config

    col1, col2 = st.columns(2)

    with col1:
        host = st.text_input("Host", value=config.get('host', 'localhost'))
        user = st.text_input("User", value=config.get('user', 'root'))
        database = st.text_input("Database Name", value=config.get('database', 'expense_tracker'))

    with col2:
        port = st.number_input("Port", value=config.get('port', 3306))
        password = st.text_input("Password", type="password", value=config.get('password', ''))

    # Update config
    config.update({
        'host': host,
        'user': user,
        'password': password,
        'database': database,
        'port': port
    })

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Test Connection", use_container_width=True):
            success, msg = test_mysql_connection(config)
            if success:
                st.success(f"✅ {msg}")
                config['connected'] = True
                save_mysql_config(config)
                st.session_state.expense_manager.mysql_connected = True

                # Initialize tables
                if init_mysql_tables(config):
                    st.success("✅ Database tables initialized")
            else:
                st.error(f"❌ {msg}")
                config['connected'] = False

    with col2:
        if st.button("Save Configuration", use_container_width=True):
            save_mysql_config(config)
            st.success("Configuration saved!")
            st.session_state.expense_manager.mysql_config = config
            st.session_state.expense_manager.test_mysql_connection()

    st.markdown("---")
    if st.button("⬅️ Back to App", use_container_width=True):
        st.session_state.show_connection_setup = False
        st.rerun()


def show_login_page():
    st.markdown('<h1 class="main-header">💰 Hybrid Expense Tracker</h1>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        # Sync status
        if st.session_state.expense_manager.mysql_connected:
            st.success("✅ MySQL Connected - Online mode")
        else:
            st.warning("⚠️ Working in Offline mode (Excel only)")

        if st.session_state.pending_changes > 0:
            st.info(f"📤 {st.session_state.pending_changes} pending changes to sync")

        st.markdown('<div class="login-box">', unsafe_allow_html=True)

        # Connection setup link
        if st.button("⚙️ MySQL Settings", key="db_settings"):
            st.session_state.show_connection_setup = True
            st.rerun()

        tab1, tab2 = st.tabs(["🔐 Login", "📝 Sign Up"])

        with tab1:
            st.subheader("Welcome Back!")

            username = st.text_input("Username", key="login_user")
            password = st.text_input("Password", type="password", key="login_pass")

            if st.button("Login", type="primary", use_container_width=True):
                if username and password:
                    user = authenticate_user(username, password)
                    if user:
                        st.session_state.user = {
                            'id': user[0],
                            'username': user[1],
                            'fullname': user[2],
                            'email': user[3]
                        }
                        st.session_state.user_id = user[0]
                        st.session_state.username = user[1]
                        st.success(f"Welcome back, {user[2] or user[1]}!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Invalid username or password!")
                else:
                    st.warning("Please enter username and password!")

        with tab2:
            st.subheader("Create New Account")

            new_username = st.text_input("Username*", key="signup_user")
            new_fullname = st.text_input("Full Name", key="signup_name")
            new_email = st.text_input("Email", key="signup_email")
            new_password = st.text_input("Password*", type="password", key="signup_pass")
            confirm_password = st.text_input("Confirm Password*", type="password", key="signup_confirm")

            if st.button("Sign Up", type="primary", use_container_width=True):
                if not new_username or not new_password:
                    st.error("Username and password are required!")
                elif new_password != confirm_password:
                    st.error("Passwords do not match!")
                elif len(new_password) < 6:
                    st.error("Password must be at least 6 characters!")
                else:
                    user_id = create_user(new_username, new_password, new_email, new_fullname)
                    if user_id:
                        st.success("Account created successfully! Please login.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Username already exists!")

        st.markdown('</div>', unsafe_allow_html=True)


def show_dashboard():
    st.markdown('<h2 class="sub-header">Dashboard</h2>', unsafe_allow_html=True)

    # Get current month's data
    today = date.today()
    df = st.session_state.expense_manager.get_expenses(
        st.session_state.user_id,
        date(today.year, today.month, 1),
        today
    )

    if not df.empty:
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)

        total_month = df['amount'].sum()
        avg_daily = df['amount'].mean()
        max_expense = df['amount'].max()
        transaction_count = len(df)

        col1.metric("Total This Month", f"฿{total_month:,.2f}")
        col2.metric("Average Expense", f"฿{avg_daily:,.2f}")
        col3.metric("Highest Expense", f"฿{max_expense:,.2f}")
        col4.metric("Transactions", transaction_count)

        # Charts
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Category Breakdown")
            category_data = df.groupby('category_name')['amount'].sum()
            if not category_data.empty:
                fig = px.pie(values=category_data.values, names=category_data.index,
                             title='Expenses by Category')
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Daily Trend")
            daily_data = df.groupby('date')['amount'].sum().reset_index()
            fig = px.line(daily_data, x='date', y='amount',
                          title='Daily Expense Trend')
            st.plotly_chart(fig, use_container_width=True)

        # Recent transactions
        st.subheader("Recent Transactions")
        recent_df = df.head(10)[['date', 'category_name', 'description', 'amount']].copy()
        recent_df['date'] = pd.to_datetime(recent_df['date']).dt.strftime('%Y-%m-%d')
        recent_df['amount'] = recent_df['amount'].apply(lambda x: f"฿{x:,.2f}")
        st.dataframe(recent_df, use_container_width=True)
    else:
        st.info("No expenses this month. Start adding expenses!")


def show_add_expense():
    st.markdown('<h2 class="sub-header">Add New Expense</h2>', unsafe_allow_html=True)

    categories_df = get_categories()
    payment_modes = get_payment_modes()

    col1, col2 = st.columns(2)

    with col1:
        expense_date = st.date_input("Date", datetime.now())

        # Category selection
        category_options = categories_df['category_name'].tolist()
        category_icons = dict(zip(categories_df['category_name'], categories_df['icon']))

        selected_category = st.selectbox(
            "Category",
            options=category_options,
            format_func=lambda x: f"{category_icons.get(x, '📌')} {x}"
        )

        description = st.text_input("Description", placeholder="What did you spend on?")

    with col2:
        amount = st.number_input("Amount (฿)", min_value=0.0, format="%.2f")
        payment_mode = st.selectbox("Payment Mode", payment_modes)
        notes = st.text_area("Notes", placeholder="Additional details...")

    if st.button("💾 Save Expense", type="primary", use_container_width=True):
        if amount > 0 and description:
            if st.session_state.expense_manager.add_expense(
                    st.session_state.user_id,
                    expense_date,
                    selected_category,
                    amount,
                    description,
                    payment_mode,
                    notes
            ):
                st.session_state.pending_changes = get_pending_count()
                st.success("✅ Expense added successfully!")
                st.balloons()
                time.sleep(1)
                st.rerun()
        else:
            st.warning("Please enter amount and description!")


def show_view_expenses():
    st.markdown('<h2 class="sub-header">View Expenses</h2>', unsafe_allow_html=True)

    # Filters
    col1, col2, col3 = st.columns(3)

    with col1:
        date_range = st.date_input(
            "Date Range",
            value=(date.today().replace(day=1), date.today())
        )

    with col2:
        categories_df = get_categories()
        categories = ['All'] + categories_df['category_name'].tolist()
        selected_category = st.selectbox("Category", categories)

    with col3:
        payment_modes = ['All'] + get_payment_modes()
        selected_payment = st.selectbox("Payment Mode", payment_modes)

    # Get data
    if len(date_range) == 2:
        df = st.session_state.expense_manager.get_expenses(
            st.session_state.user_id,
            date_range[0],
            date_range[1],
            selected_category if selected_category != 'All' else None
        )

        # Apply payment mode filter
        if selected_payment != 'All' and not df.empty:
            df = df[df['payment_mode'] == selected_payment]

        if not df.empty:
            # Summary
            total = df['amount'].sum()
            st.metric("Total Expenses", f"฿{total:,.2f}")

            # Display data
            display_df = df[['date', 'category_name', 'description', 'amount', 'payment_mode', 'sync_status']].copy()
            display_df['date'] = pd.to_datetime(display_df['date']).dt.strftime('%Y-%m-%d')
            display_df['amount'] = display_df['amount'].apply(lambda x: f"฿{x:,.2f}")
            display_df.columns = ['Date', 'Category', 'Description', 'Amount', 'Payment Mode', 'Sync Status']

            st.dataframe(display_df, use_container_width=True, height=400)

            # Export
            if st.button("📥 Export to Excel", use_container_width=True):
                output = f"expenses_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                df.to_excel(output, index=False)
                st.success(f"Exported to {output}")
        else:
            st.info("No expenses found")


def show_update_delete():
    st.markdown('<h2 class="sub-header">Update or Delete Expenses</h2>', unsafe_allow_html=True)

    # Get recent expenses
    df = st.session_state.expense_manager.get_expenses(st.session_state.user_id)

    if not df.empty:
        # Create selection
        df['Display'] = df.apply(
            lambda
                x: f"{pd.to_datetime(x['date']).strftime('%Y-%m-%d')} - {x['category_name']} - ฿{x['amount']:,.2f} - {x['description'][:30]}",
            axis=1
        )

        selected = st.selectbox(
            "Select expense to edit/delete",
            range(len(df)),
            format_func=lambda x: df.iloc[x]['Display']
        )

        if selected is not None:
            entry = df.iloc[selected]

            st.write("### Current Values")
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Date:** {pd.to_datetime(entry['date']).strftime('%Y-%m-%d')}")
                st.write(f"**Category:** {entry['category_name']}")
                st.write(f"**Description:** {entry['description']}")
            with col2:
                st.write(f"**Amount:** ฿{entry['amount']:,.2f}")
                st.write(f"**Payment Mode:** {entry['payment_mode']}")
                st.write(f"**Notes:** {entry['notes']}")
                st.write(f"**Sync Status:** {entry.get('sync_status', 'unknown')}")

            st.write("### Update Values")

            categories_df = get_categories()
            payment_modes = get_payment_modes()

            new_date = st.date_input("Date", pd.to_datetime(entry['date']).date())
            new_category = st.selectbox(
                "Category",
                categories_df['category_name'].tolist(),
                index=categories_df['category_name'].tolist().index(entry['category_name']) if entry['category_name'] in
                                                                                               categories_df[
                                                                                                   'category_name'].tolist() else 0
            )
            new_description = st.text_input("Description", entry['description'])
            new_amount = st.number_input("Amount", min_value=0.0, value=float(entry['amount']), format="%.2f")
            new_payment = st.selectbox(
                "Payment Mode",
                payment_modes,
                index=payment_modes.index(entry['payment_mode']) if entry['payment_mode'] in payment_modes else 0
            )
            new_notes = st.text_area("Notes", entry['notes'] if pd.notna(entry['notes']) else "")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Update", type="primary", use_container_width=True):
                    if st.session_state.expense_manager.update_expense(
                            entry['expense_id'],
                            new_date,
                            new_category,
                            new_amount,
                            new_description,
                            new_payment,
                            new_notes
                    ):
                        st.session_state.pending_changes = get_pending_count()
                        st.success("Expense updated!")
                        st.rerun()

            with col2:
                if st.button("🗑️ Delete", type="secondary", use_container_width=True):
                    if st.session_state.expense_manager.delete_expense(entry['expense_id']):
                        st.session_state.pending_changes = get_pending_count()
                        st.success("Expense deleted!")
                        st.rerun()
    else:
        st.info("No expenses to update")


def show_reports():
    st.markdown('<h2 class="sub-header">Expense Reports</h2>', unsafe_allow_html=True)

    # Date selection
    col1, col2 = st.columns(2)
    with col1:
        year = st.number_input("Year", min_value=2020, max_value=2030, value=date.today().year)
    with col2:
        month = st.selectbox("Month", range(1, 13), index=date.today().month - 1)

    # Get data
    last_day = calendar.monthrange(year, month)[1]
    df = st.session_state.expense_manager.get_expenses(
        st.session_state.user_id,
        date(year, month, 1),
        date(year, month, last_day)
    )

    if not df.empty:
        total = df['amount'].sum()
        st.metric(f"Total for {datetime(year, month, 1).strftime('%B %Y')}", f"฿{total:,.2f}")

        # Category summary
        cat_summary = df.groupby('category_name')['amount'].agg(['sum', 'count']).reset_index()
        cat_summary.columns = ['Category', 'Total', 'Count']
        cat_summary = cat_summary.sort_values('Total', ascending=False)

        col1, col2 = st.columns(2)

        with col1:
            fig = px.pie(cat_summary, values='Total', names='Category',
                         title='Category Distribution')
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fig = px.bar(cat_summary, x='Category', y='Total',
                         title='Category-wise Expenses')
            st.plotly_chart(fig, use_container_width=True)

        # Detailed table
        st.subheader("Category Details")
        display_summary = cat_summary.copy()
        display_summary['Total'] = display_summary['Total'].apply(lambda x: f"฿{x:,.2f}")
        st.dataframe(display_summary, use_container_width=True)

        # Daily trend
        st.subheader("Daily Trend")
        daily = df.groupby('date')['amount'].sum().reset_index()
        daily['date'] = pd.to_datetime(daily['date'])
        fig = px.line(daily, x='date', y='amount', title='Daily Expenses')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(f"No data for {datetime(year, month, 1).strftime('%B %Y')}")


def show_settings():
    st.markdown('<h2 class="sub-header">Settings</h2>', unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs(["👤 Profile", "📁 Data", "🔄 Sync", "ℹ️ About"])

    with tab1:
        st.subheader("Profile Settings")

        st.write(f"**Username:** {st.session_state.user['username']}")
        st.write(f"**Full Name:** {st.session_state.user['fullname'] or 'Not set'}")
        st.write(f"**Email:** {st.session_state.user['email'] or 'Not set'}")

        if st.button("Change Password", use_container_width=True):
            st.info("Password change feature coming soon!")

    with tab2:
        st.subheader("Data Management")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("💾 Export to Excel", use_container_width=True):
                df = st.session_state.expense_manager.get_expenses(st.session_state.user_id)
                if not df.empty:
                    output = f"my_expenses_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                    df.to_excel(output, index=False)
                    st.success(f"Data exported to {output}")
                else:
                    st.warning("No data to export")

        with col2:
            if st.button("📂 Open Excel File", use_container_width=True):
                if os.path.exists(EXCEL_FILE):
                    os.startfile(EXCEL_FILE)
                else:
                    st.warning("Excel file not found")

    with tab3:
        st.subheader("Sync Settings")

        st.write(
            f"**MySQL Status:** {'Connected' if st.session_state.expense_manager.mysql_connected else 'Disconnected'}")
        st.write(f"**Pending Changes:** {st.session_state.pending_changes}")
        st.write(f"**Last Sync:** {st.session_state.last_sync}")

        if st.button("🔄 Force Sync Now", use_container_width=True):
            with st.spinner("Syncing..."):
                success, msg = st.session_state.expense_manager.sync_with_mysql()
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
                time.sleep(1)
                st.rerun()

        if st.button("⚙️ Configure MySQL", use_container_width=True):
            st.session_state.show_connection_setup = True
            st.rerun()

    with tab4:
        st.subheader("About")
        st.markdown("""
        ### Hybrid Expense Tracker v1.0

        **Features:**
        - ✅ Works offline with Excel
        - ✅ Syncs with MySQL when online
        - ✅ 17 expense categories
        - ✅ Interactive reports
        - ✅ Data export

        **Files:**
        - `expenses_data.xlsx` - Main data file
        - `users.xlsx` - User accounts
        - `sync_status.db` - Sync queue
        - `mysql_config.json` - MySQL settings

        **How it works:**
        1. Always works offline with Excel
        2. Changes are queued when offline
        3. Auto-sync when MySQL is connected
        4. Manual sync available
        """)


def show_main_app():
    # Sidebar
    with st.sidebar:
        st.image("https://img.icons8.com/color/96/000000/money--v1.png", width=80)
        st.title(f"Welcome, {st.session_state.user['fullname'] or st.session_state.user['username']}! 👋")

        st.markdown("---")

        # Connection status
        if st.session_state.expense_manager.mysql_connected:
            st.markdown('<p class="sync-status online">✅ Online - MySQL connected</p>', unsafe_allow_html=True)
        else:
            st.markdown('<p class="sync-status offline">⚠️ Offline - Excel only</p>', unsafe_allow_html=True)

        if st.session_state.pending_changes > 0:
            st.warning(f"📤 {st.session_state.pending_changes} pending changes")

            if st.button("🔄 Sync Now", use_container_width=True):
                with st.spinner("Syncing..."):
                    success, msg = st.session_state.expense_manager.sync_with_mysql()
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
                    time.sleep(1)
                    st.rerun()

        st.caption(f"Last sync: {st.session_state.last_sync}")

        st.markdown("---")

        # Navigation
        menu = st.radio(
            "Navigation",
            ["📊 Dashboard", "➕ Add Expense", "📋 View Expenses",
             "✏️ Update/Delete", "📈 Reports", "⚙️ Settings"],
            label_visibility="collapsed"
        )

        st.markdown("---")

        # Logout button
        if st.button("🚪 Logout", use_container_width=True):
            for key in ['user', 'user_id', 'username']:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

    # Main content
    st.markdown(f'<h1 class="main-header">📊 Expense Tracker - {st.session_state.user["username"]}</h1>',
                unsafe_allow_html=True)

    if menu == "📊 Dashboard":
        show_dashboard()
    elif menu == "➕ Add Expense":
        show_add_expense()
    elif menu == "📋 View Expenses":
        show_view_expenses()
    elif menu == "✏️ Update/Delete":
        show_update_delete()
    elif menu == "📈 Reports":
        show_reports()
    elif menu == "⚙️ Settings":
        show_settings()


# ============================================
# MAIN EXECUTION
# ============================================

# Check if we need to show connection setup
if st.session_state.get('show_connection_setup', False):
    show_connection_setup()
elif st.session_state.user is None:
    show_login_page()
else:
    show_main_app()

# Footer
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: gray; padding: 10px;'>
        Hybrid Expense Tracker | Works Offline with Excel | Syncs with MySQL
    </div>
    """,
    unsafe_allow_html=True
)