import os
import json
import sqlite3
from datetime import datetime
import matplotlib.pyplot as plt
import io, base64

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # Replace with a strong secret key
DATABASE = 'finance.db'

# Setup Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ----- Database Initialization -----
def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    # Users table
    c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )
    ''')
    # Account configuration table
    c.execute('''
    CREATE TABLE IF NOT EXISTS account_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        account_name TEXT,
        account_type TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    ''')
    # Snapshots table
    c.execute('''
    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        date TEXT,
        data TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    ''')
    # Payments table
    c.execute('''
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        card_name TEXT,
        due_date TEXT,
        amount_due REAL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    ''')
    conn.commit()
    conn.close()

init_db()

# ----- User Loader for Flask-Login -----
class User(UserMixin):
    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = password

def get_user_by_id(user_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, username, password FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return User(row[0], row[1], row[2])
    return None

@login_manager.user_loader
def load_user(user_id):
    return get_user_by_id(user_id)

# ----- User Registration -----
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_pw = generate_password_hash(password)
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_pw))
            conn.commit()
        except sqlite3.IntegrityError:
            flash("Username already exists. Please choose another.")
            return redirect(url_for('register'))
        conn.close()
        flash("Registration successful. Please log in.")
        return redirect(url_for('login'))
    return render_template('register.html')

# ----- User Login -----
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("SELECT id, username, password FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        conn.close()
        if row and check_password_hash(row[2], password):
            user = User(row[0], row[1], row[2])
            login_user(user)
            flash("Logged in successfully.")
            return redirect(url_for('index'))
        else:
            flash("Invalid username or password.")
            return redirect(url_for('login'))
    return render_template('login.html')

# ----- User Logout -----
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.")
    return redirect(url_for('login'))

# ----- Helper Functions -----
def get_account_config(user_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, account_name, account_type FROM account_config WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{"id": row[0], "name": row[1], "type": row[2]} for row in rows]

def get_latest_fast_cash(user_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT date, data FROM snapshots WHERE user_id = ? ORDER BY date DESC LIMIT 1", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        data = json.loads(row[1])
        accounts = get_account_config(user_id)
        fast_cash = 0
        for acc in accounts:
            if acc['type'] == 'asset_debit':
                acc_id = str(acc['id'])
                fast_cash += data.get(acc_id, 0)
        return fast_cash
    return None

# ----- Main Routes (Login Required) -----
@app.route('/')
@login_required
def index():
    # Fetch the latest snapshot for the current user (sorted by date descending, limit 1)
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, date FROM snapshots WHERE user_id = ? ORDER BY date DESC LIMIT 1", (current_user.id,))
    row = c.fetchone()
    conn.close()

    latest_snapshot = None
    if row:
        latest_snapshot = {"id": row[0], "date": row[1]}

    return render_template('index.html', latest_snapshot=latest_snapshot)

# Configure accounts
@app.route('/configure_accounts', methods=['GET', 'POST'])
@login_required
def configure_accounts():
    if request.method == 'POST':
        account_name = request.form['account_name']
        account_type = request.form['account_type']
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("INSERT INTO account_config (user_id, account_name, account_type) VALUES (?, ?, ?)",
                  (current_user.id, account_name, account_type))
        conn.commit()
        conn.close()
        return redirect(url_for('configure_accounts'))
    accounts = get_account_config(current_user.id)
    return render_template('configure_accounts.html', accounts=accounts)

# Delete account route
@app.route('/delete_account/<int:account_id>', methods=['POST'])
@login_required
def delete_account(account_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("DELETE FROM account_config WHERE id = ? AND user_id = ?", (account_id, current_user.id))
    conn.commit()
    conn.close()
    return redirect(url_for('configure_accounts'))

# Add snapshot record (dynamic form)
@app.route('/add_snapshot', methods=['GET', 'POST'])
@login_required
def add_snapshot():
    accounts = get_account_config(current_user.id)
    # Group accounts by type
    liquid_accounts = [acc for acc in accounts if acc['type'] in ['asset_debit', 'asset_other']]
    savings_accounts = [acc for acc in accounts if acc['type'] == 'asset_savings']
    debt_accounts   = [acc for acc in accounts if acc['type'] == 'debt']

    if request.method == 'POST':
        date_str = request.form['date']
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return "Invalid date format. Use YYYY-MM-DD.", 400
        snapshot_data = {}

        # Process liquid and savings asset accounts (one input per account)
        for acc in liquid_accounts + savings_accounts:
            acc_id = str(acc['id'])
            value = request.form.get(f"account_{acc_id}", "0")
            try:
                snapshot_data[acc_id] = float(value)
            except ValueError:
                snapshot_data[acc_id] = 0.0

        # Process debt accounts (two inputs: current and statement balances)
        for acc in debt_accounts:
            acc_id = str(acc['id'])
            val_current = request.form.get(f"account_{acc_id}_current", "0")
            val_statement = request.form.get(f"account_{acc_id}_statement", "0")
            try:
                snapshot_data[acc_id] = {
                    "current": float(val_current),
                    "statement": float(val_statement)
                }
            except ValueError:
                snapshot_data[acc_id] = {"current": 0.0, "statement": 0.0}

        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("INSERT INTO snapshots (user_id, date, data) VALUES (?, ?, ?)",
                  (current_user.id, date_str, json.dumps(snapshot_data)))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))
    return render_template("add_snapshot.html",
                           liquid_accounts=liquid_accounts,
                           savings_accounts=savings_accounts,
                           debt_accounts=debt_accounts)


@app.route('/edit_snapshot/<int:snapshot_id>', methods=['GET', 'POST'])
@login_required
def edit_snapshot(snapshot_id):
    # Retrieve the snapshot for the current user.
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT date, data FROM snapshots WHERE id = ? AND user_id = ?", (snapshot_id, current_user.id))
    row = c.fetchone()
    conn.close()
    if not row:
        flash("Snapshot not found.")
        return redirect(url_for('index'))

    snapshot_date, data_json = row
    snapshot_data = json.loads(data_json)

    # Get the account configuration and group them.
    accounts = get_account_config(current_user.id)
    liquid_accounts = [acc for acc in accounts if acc['type'] in ['asset_debit', 'asset_other']]
    savings_accounts = [acc for acc in accounts if acc['type'] == 'asset_savings']
    debt_accounts   = [acc for acc in accounts if acc['type'] == 'debt']

    # Pre-populate each account's value from the snapshot.
    for acc in liquid_accounts:
        acc_id = str(acc['id'])
        acc['value'] = snapshot_data.get(acc_id, "")
    for acc in savings_accounts:
        acc_id = str(acc['id'])
        acc['value'] = snapshot_data.get(acc_id, "")
    for acc in debt_accounts:
        acc_id = str(acc['id'])
        debt_info = snapshot_data.get(acc_id, {"current": "", "statement": ""})
        acc['current_value'] = debt_info.get("current", "")
        acc['statement_value'] = debt_info.get("statement", "")

    if request.method == 'POST':
        # Update the snapshot data from the submitted form.
        for acc in liquid_accounts + savings_accounts:
            acc_id = str(acc['id'])
            value = request.form.get(f"account_{acc_id}", "0")
            try:
                snapshot_data[acc_id] = float(value)
            except ValueError:
                snapshot_data[acc_id] = 0.0
        for acc in debt_accounts:
            acc_id = str(acc['id'])
            val_current = request.form.get(f"account_{acc_id}_current", "0")
            val_statement = request.form.get(f"account_{acc_id}_statement", "0")
            try:
                snapshot_data[acc_id] = {
                    "current": float(val_current),
                    "statement": float(val_statement)
                }
            except ValueError:
                snapshot_data[acc_id] = {"current": 0.0, "statement": 0.0}
        # Update the snapshot record.
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("UPDATE snapshots SET data = ? WHERE id = ? AND user_id = ?",
                  (json.dumps(snapshot_data), snapshot_id, current_user.id))
        conn.commit()
        conn.close()
        flash("Snapshot updated successfully!")
        return redirect(url_for('index'))

    return render_template("edit_snapshot.html",
                           date=snapshot_date,
                           liquid_accounts=liquid_accounts,
                           savings_accounts=savings_accounts,
                           debt_accounts=debt_accounts,
                           snapshot_id=snapshot_id)


# Charts (spending and accessible net worth)
@app.route('/charts')
@login_required
def charts():
    accounts = get_account_config(current_user.id)
    acc_types = {str(acc['id']): acc['type'] for acc in accounts}

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT date, data FROM snapshots WHERE user_id = ? ORDER BY date", (current_user.id,))
    rows = c.fetchall()
    conn.close()

    dates = []
    spending_list = []   # Sum of statement balances from debt accounts
    networth_list = []   # Accessible net worth calculation

    for row in rows:
        date_str, data_json = row
        try:
            record_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            continue
        dates.append(record_date)
        data = json.loads(data_json)
        spending = 0
        total_current_debt = 0
        total_statement_debt = 0
        accessible_assets = 0

        for acc_id, value in data.items():
            acc_type = acc_types.get(acc_id)
            if not acc_type:
                continue
            if acc_type == 'debt':
                total_current_debt += value.get("current", 0)
                total_statement_debt += value.get("statement", 0)
                spending += value.get("statement", 0)
            elif acc_type in ['asset_debit', 'asset_other']:
                accessible_assets += value
        adjusted_debt = total_current_debt - total_statement_debt
        accessible_net_worth = accessible_assets - adjusted_debt
        spending_list.append(spending)
        networth_list.append(accessible_net_worth)

    charts = {}
    # Spending chart
    fig1, ax1 = plt.subplots()
    ax1.plot(dates, spending_list, marker='o', linestyle='-')
    ax1.set_title('Spending Over Time')
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Spending')
    ax1.grid(True)
    ax1.tick_params(axis='x', rotation=45)  # Rotate x-axis labels by 45 degrees
    buf1 = io.BytesIO()
    fig1.savefig(buf1, format='png')
    buf1.seek(0)
    charts['spending'] = base64.b64encode(buf1.getvalue()).decode('utf8')
    plt.close(fig1)

    # Accessible Net Worth Chart
    fig2, ax2 = plt.subplots()
    ax2.plot(dates, networth_list, marker='o', linestyle='-', color='green')
    ax2.set_title('Accessible Net Worth Over Time')
    ax2.set_xlabel('Date')
    ax2.set_ylabel('Accessible Net Worth')
    ax2.grid(True)
    ax2.tick_params(axis='x', rotation=45)  # Rotate x-axis labels by 45 degrees
    buf2 = io.BytesIO()
    fig2.savefig(buf2, format='png')
    buf2.seek(0)
    charts['networth'] = base64.b64encode(buf2.getvalue()).decode('utf8')
    plt.close(fig2)

    return render_template('charts.html', charts=charts)

# Payment Due Entry
@app.route('/add_payment', methods=['GET', 'POST'])
@login_required
def add_payment():
    if request.method == 'POST':
        card_name = request.form['card_name']
        due_date = request.form['due_date']
        try:
            datetime.strptime(due_date, '%Y-%m-%d')
        except ValueError:
            return "Invalid date format. Use YYYY-MM-DD.", 400
        try:
            amount_due = float(request.form['amount_due'])
        except ValueError:
            return "Invalid amount.", 400
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("INSERT INTO payments (user_id, card_name, due_date, amount_due) VALUES (?, ?, ?, ?)",
                  (current_user.id, card_name, due_date, amount_due))
        conn.commit()
        conn.close()
        return redirect(url_for('payments'))
    return render_template('add_payment.html')

# Payment Tracker
@app.route('/payments')
@login_required
def payments():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT card_name, due_date, amount_due FROM payments WHERE user_id = ? ORDER BY due_date", (current_user.id,))
    payment_rows = c.fetchall()
    conn.close()

    total_due = sum(row[2] for row in payment_rows)
    available_cash = get_latest_fast_cash(current_user.id)
    warning = None
    if available_cash is not None and total_due > available_cash:
        warning = f"Warning: Total payment due (${total_due:.2f}) exceeds available fast-access cash (${available_cash:.2f})."

    payments_list = [{"card_name": row[0], "due_date": row[1], "amount_due": row[2]} for row in payment_rows]

    return render_template('payments.html', payments=payments_list, total_due=total_due, available_cash=available_cash, warning=warning)

# Run the app with port provided by Render or default 5000
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
