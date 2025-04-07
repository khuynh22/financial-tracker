# Financial Tracker Web App

A dynamic, Flask-based financial tracker that lets users:
- **Configure Their Own Accounts:**
  Define asset accounts (e.g., Debit, Savings, Other) and debt accounts.
- **Input Financial Snapshots:**
  Record balances for each configured account (assets and debts).
  For debt accounts, record both current and statement balances.
- **View Charts:**
  Visualize spending (total statement balances) and accessible net worth (liquid assets minus adjusted debt) over time.
- **Track Card Payments:**
  Add upcoming payment due entries and check if available fast-access cash covers the total due.

> **Note:**
> This project uses multi-user support with Flask-Login so that each user's data is kept separate. All data is stored securely in the database.

## Live Demo

You can access a live demo of the Financial Tracker Web App at:
[https://financial-tracker-yul5.onrender.com](https://financial-tracker-yul5.onrender.com)

## Features

- **Dynamic Account Configuration:**
  Users can add, edit, or delete accounts (assets or debts) to suit their needs.
- **Flexible Snapshot Entry:**
  A dynamic form generated from the account configuration stores snapshot data as JSON in SQLite (or your chosen database).
- **Data Visualization:**
  Charts (rendered with Matplotlib) display spending trends and accessible net worth over time.
- **Payment Tracker:**
  Manage and monitor upcoming card payments compared against fast-access cash.

## Installation

### Prerequisites

- Python 3.x
- Git

### Clone the Repository

```bash
git clone https://github.com/your-username/financial-tracker.git
cd financial-tracker
