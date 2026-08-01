-- 1. Customers Table
CREATE EXTERNAL TABLE IF NOT EXISTS sb.customers (
    customer_id INT,
    first_name STRING,
    last_name STRING,
    email STRING,
    birth_date DATE,
    bank_name STRING, -- Supports queries like "BNI customers"
    join_date DATE
) STORED AS PARQUET;

-- 2. Savings Accounts Table
CREATE EXTERNAL TABLE IF NOT EXISTS sb.savings (
    savings_id INT,
    customer_id INT,
    account_number STRING,
    balance DECIMAL(15, 2),
    interest_rate DECIMAL(4, 2),
    status STRING
) STORED AS PARQUET;

-- 3. Time Deposits Table
CREATE EXTERNAL TABLE IF NOT EXISTS sb.deposits (
    deposit_id INT,
    customer_id INT,
    account_number STRING,
    principal_amount DECIMAL(15, 2),
    maturity_date DATE,
    interest_rate DECIMAL(4, 2),
    status STRING
) STORED AS PARQUET;

-- 4. Loans Table
CREATE EXTERNAL TABLE IF NOT EXISTS sb.loans (
    loan_id INT,
    customer_id INT,
    loan_type STRING, -- Home, Auto, Personal
    principal_amount DECIMAL(15, 2),
    outstanding_balance DECIMAL(15, 2),
    maturity_date DATE,
    status STRING
) STORED AS PARQUET;

-- 5. Credit Cards Table
CREATE TABLE IF NOT EXISTS sb.credit_cards (
    card_id INT,
    customer_id INT,
    card_number STRING,
    credit_limit DECIMAL(15, 2),
    current_balance DECIMAL(15, 2),
    expiry_date DATE,
    status STRING
) STORED AS PARQUET;

-- 6. Transactions Table
CREATE EXTERNAL TABLE IF NOT EXISTS sb.transactions (
    transaction_id INT,
    account_number STRING,
    amount DECIMAL(15, 2),
    transaction_type STRING, -- DEBIT, CREDIT
    transaction_timestamp TIMESTAMP,
    description STRING
) STORED AS PARQUET;

-- 7. Branch Metrics/Dashboards metadata (For dashboard context RAG queries)
CREATE EXTERNAL TABLE IF NOT EXISTS sb.branch_performance (
    branch_id INT,
    branch_name STRING,
    region STRING,
    total_active_customers INT,
    monthly_target_achieved DECIMAL(5,2)
) STORED AS PARQUET;

-- =====================================================================
-- SEED DUMMY DATA WITH DYNAMIC DATE LOGIC
-- =====================================================================

-- 1. CUSTOMERS
INSERT INTO sb.customers VALUES
(1, 'Ahmad', 'Fauzi', 'ahmad.f@bni.co.id', add_months(date_add(current_date(),2),-360), 'BNI', CAST('2020-01-15' AS DATE)),
(2, 'Siti', 'Aminah', 'siti.a@bni.co.id', add_months(date_add(current_date(),4),-300), 'BNI', CAST('2021-03-22' AS DATE)),
(3, 'Budi', 'Santoso', 'budi.s@abc.com', add_months(date_add(current_date(),1),-540), 'ABC', CAST('2019-11-02' AS DATE)),
(4, 'John', 'Doe', 'john.doe@abc.com', CAST('1988-05-12' AS DATE), 'ABC', CAST('2022-06-18' AS DATE)),
(5, 'Jane', 'Smith', 'jane.smith@bni.co.id', CAST('1992-09-25' AS DATE), 'BNI', CAST('2023-02-10' AS DATE));

-- 2. SAVINGS
INSERT INTO sb.savings VALUES
(1, 1, 'SAV-BNI-001', 25000000.00, 2.50, 'ACTIVE'),
(2, 2, 'SAV-BNI-002', 75000000.00, 2.75, 'ACTIVE'),
(3, 3, 'SAV-ABC-003', 120000000.00, 3.00, 'ACTIVE'),
(4, 4, 'SAV-ABC-004', 5000000.00, 1.50, 'DORMANT');

-- 3. DEPOSITS
INSERT INTO sb.deposits VALUES
(1, 1, 'DEP-BNI-101', 100000000.00, date_add(current_date(),3), 5.25, 'ACTIVE'),
(2, 3, 'DEP-ABC-102', 500000000.00, date_add(current_date(),6), 5.50, 'ACTIVE'),
(3, 4, 'DEP-ABC-103', 50000000.00, date_add(current_date(),180), 4.75, 'ACTIVE');

-- 4. LOANS
INSERT INTO sb.loans VALUES
(1, 2, 'Personal', 50000000.00, 4500000.00, date_add(current_date(),5), 'ACTIVE'),
(2, 3, 'Mortgage', 1200000000.00, 980000000.00, add_months(current_date(),120), 'ACTIVE');

-- 5. CREDIT CARDS
INSERT INTO sb.credit_cards VALUES
(1, 1, '4560-1234-8888-1111', 50000000.00, 12500000.00, add_months(current_date(),24), 'ACTIVE'),
(2, 4, '4560-1234-8888-2222', 20000000.00, 19500000.00, add_months(current_date(),1), 'WARNING');

-- 6. TRANSACTIONS
INSERT INTO sb.transactions VALUES
(1, 'SAV-BNI-001', 500000.00, 'DEBIT', CAST(from_unixtime(unix_timestamp()-7200) AS TIMESTAMP), 'ATM Withdrawal'),
(2, 'SAV-ABC-003', 1500000.00, 'CREDIT', CAST(from_unixtime(unix_timestamp()-86400) AS TIMESTAMP), 'Payroll Transfer');

-- 7. BRANCH PERFORMANCE
INSERT INTO sb.branch_performance VALUES
(1, 'Jakarta Main Branch', 'DKI Jakarta', 12500, 104.50),
(2, 'Surabaya Cluster', 'East Java', 8400, 92.10);