from flask import Flask, render_template, request, redirect, url_for
import sqlite3, json
from datetime import datetime
import matplotlib.pyplot as plt
import io, base64
import os

app = Flask(__name__)
DATABASE = 'finance.db'
USER_ID = 1  # Using a fixed user ID for this example

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    # Table for user account configuration
    c.execute('''
    CREATE TABLE IF NOT EXISTS account_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        account_name TEXT,
        account_type TEXT
    )
    ''')
    # Table for snapshot records (balances stored as JSON)
    c.execute('''
    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        date TEXT,
        data TEXT
    )
    ''')
    # Table for payment due entries
    c.execute('''
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        card_name TEXT,
        due_date TEXT,
        amount_due REAL
    )
    ''')
    conn.commit()
    conn.close()

init_db()

# Helper: Get account configuration for the given user
def get_account_config(user_id=USER_ID):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, account_name, account_type FROM account_config WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{"id": row[0], "name": row[1], "type": row[2]} for row in rows]

# Helper: Get latest fast-access cash (sum of all asset_debit accounts from latest snapshot)
def get_latest_fast_cash(user_id=USER_ID):
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

@app.route('/')
def index():
    return render_template('index.html')

# Route: Configure Accounts (initial and later add more)
@app.route('/configure_accounts', methods=['GET', 'POST'])
def configure_accounts():
    if request.method == 'POST':
        account_name = request.form['account_name']
        account_type = request.form['account_type']
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("INSERT INTO account_config (user_id, account_name, account_type) VALUES (?, ?, ?)",
                  (USER_ID, account_name, account_type))
        conn.commit()
        conn.close()
        return redirect(url_for('configure_accounts'))
    accounts = get_account_config(USER_ID)
    return render_template('configure_accounts.html', accounts=accounts)

# Route: Add Snapshot Record (dynamically generated form)
@app.route('/add_snapshot', methods=['GET', 'POST'])
def add_snapshot():
    accounts = get_account_config(USER_ID)
    if request.method == 'POST':
        date_str = request.form['date']
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return "Invalid date format. Use YYYY-MM-DD.", 400
        snapshot_data = {}
        for acc in accounts:
            acc_id = str(acc['id'])
            if acc['type'].startswith('asset'):
                # For asset accounts, one field is needed
                value = request.form.get(f"account_{acc_id}", "0")
                try:
                    snapshot_data[acc_id] = float(value)
                except ValueError:
                    snapshot_data[acc_id] = 0.0
            elif acc['type'] == 'debt':
                # For debt accounts, collect both current and statement values
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
                  (USER_ID, date_str, json.dumps(snapshot_data)))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))
    return render_template('add_snapshot.html', accounts=accounts)

# Route: Charts – dynamically compute spending and accessible net worth over time
@app.route('/charts')
def charts():
    accounts = get_account_config(USER_ID)
    # Build a mapping: account_id -> account_type (as strings)
    acc_types = {str(acc['id']): acc['type'] for acc in accounts}

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT date, data FROM snapshots WHERE user_id = ? ORDER BY date", (USER_ID,))
    rows = c.fetchall()
    conn.close()

    dates = []
    spending_list = []   # Sum of statement balances from all debt accounts
    networth_list = []   # Accessible net worth = (sum of liquid asset values) - (total current debt - total statement debt)

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
                # value is a dict with keys "current" and "statement"
                total_current_debt += value.get("current", 0)
                total_statement_debt += value.get("statement", 0)
                spending += value.get("statement", 0)
            elif acc_type in ['asset_debit', 'asset_other']:
                accessible_assets += value
            # Note: asset_savings is not included in accessible assets.

        adjusted_debt = total_current_debt - total_statement_debt
        accessible_net_worth = accessible_assets - adjusted_debt
        spending_list.append(spending)
        networth_list.append(accessible_net_worth)

    charts = {}
    # Generate Spending Chart
    fig1, ax1 = plt.subplots()
    ax1.plot(dates, spending_list, marker='o', linestyle='-')
    ax1.set_title('Spending Over Time')
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Spending')
    ax1.grid(True)
    buf1 = io.BytesIO()
    fig1.savefig(buf1, format='png')
    buf1.seek(0)
    charts['spending'] = base64.b64encode(buf1.getvalue()).decode('utf8')
    plt.close(fig1)

    # Generate Accessible Net Worth Chart
    fig2, ax2 = plt.subplots()
    ax2.plot(dates, networth_list, marker='o', linestyle='-', color='green')
    ax2.set_title('Accessible Net Worth Over Time')
    ax2.set_xlabel('Date')
    ax2.set_ylabel('Accessible Net Worth')
    ax2.grid(True)
    buf2 = io.BytesIO()
    fig2.savefig(buf2, format='png')
    buf2.seek(0)
    charts['networth'] = base64.b64encode(buf2.getvalue()).decode('utf8')
    plt.close(fig2)

    return render_template('charts.html', charts=charts)

# Route: Add Payment Due Entry
@app.route('/add_payment', methods=['GET', 'POST'])
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
                  (USER_ID, card_name, due_date, amount_due))
        conn.commit()
        conn.close()
        return redirect(url_for('payments'))
    return render_template('add_payment.html')

@app.route('/delete_account/<int:account_id>', methods=['POST'])
def delete_account(account_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    # Delete the account configuration for the given account_id and current user.
    c.execute("DELETE FROM account_config WHERE id = ? AND user_id = ?", (account_id, USER_ID))
    conn.commit()
    conn.close()
    return redirect(url_for('configure_accounts'))

# Route: Payment Tracker
@app.route('/payments')
def payments():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT card_name, due_date, amount_due FROM payments WHERE user_id = ? ORDER BY due_date", (USER_ID,))
    payment_rows = c.fetchall()
    conn.close()

    total_due = sum(row[2] for row in payment_rows)
    available_cash = get_latest_fast_cash(USER_ID)
    warning = None
    if available_cash is not None and total_due > available_cash:
        warning = f"Warning: Total payment due (${total_due:.2f}) exceeds available fast-access cash (${available_cash:.2f})."

    payments_list = [{"card_name": row[0], "due_date": row[1], "amount_due": row[2]} for row in payment_rows]

    return render_template('payments.html', payments=payments_list, total_due=total_due, available_cash=available_cash, warning=warning)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
