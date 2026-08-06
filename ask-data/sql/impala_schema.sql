-- 1. Customers Table
CREATE EXTERNAL TABLE IF NOT EXISTS test.cai_customers (
    customer_id INT,
    first_name STRING,
    last_name STRING,
    email STRING,
    birth_date DATE,
    bank_name STRING, -- Supports queries like "BNI customers"
    join_date DATE
) STORED AS PARQUET;

-- 2. Savings Accounts Table
CREATE EXTERNAL TABLE IF NOT EXISTS test.cai_savings (
    savings_id INT,
    customer_id INT,
    account_number STRING,
    balance DECIMAL(15, 2),
    interest_rate DECIMAL(4, 2),
    status STRING
) STORED AS PARQUET;

-- 3. Time Deposits Table
CREATE EXTERNAL TABLE IF NOT EXISTS test.cai_deposits (
    deposit_id INT,
    customer_id INT,
    account_number STRING,
    principal_amount DECIMAL(15, 2),
    maturity_date DATE,
    interest_rate DECIMAL(4, 2),
    status STRING
) STORED AS PARQUET;

-- 4. Loans Table
CREATE EXTERNAL TABLE IF NOT EXISTS test.cai_loans (
    loan_id INT,
    customer_id INT,
    loan_type STRING, -- Home, Auto, Personal
    principal_amount DECIMAL(15, 2),
    outstanding_balance DECIMAL(15, 2),
    maturity_date DATE,
    status STRING
) STORED AS PARQUET;

-- 5. Credit Cards Table
CREATE TABLE IF NOT EXISTS test.cai_credit_cards (
    card_id INT,
    customer_id INT,
    card_number STRING,
    credit_limit DECIMAL(15, 2),
    current_balance DECIMAL(15, 2),
    expiry_date DATE,
    status STRING
) STORED AS PARQUET;

-- 6. Transactions Table
CREATE EXTERNAL TABLE IF NOT EXISTS test.cai_transactions (
    transaction_id INT,
    account_number STRING,
    amount DECIMAL(15, 2),
    transaction_type STRING, -- DEBIT, CREDIT
    transaction_timestamp TIMESTAMP,
    description STRING
) STORED AS PARQUET;

-- 7. Branch Metrics/Dashboards metadata (For dashboard context RAG queries)
CREATE EXTERNAL TABLE IF NOT EXISTS test.cai_branch_performance (
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
INSERT INTO test.cai_customers VALUES
(1, 'Ahmad', 'Fauzi', 'ahmad.f@bni.co.id', add_months(date_add(current_date(),2),-360), 'BNI', CAST('2020-01-15' AS DATE)),
(2, 'Siti', 'Aminah', 'siti.a@bni.co.id', add_months(date_add(current_date(),4),-300), 'BNI', CAST('2021-03-22' AS DATE)),
(3, 'Budi', 'Santoso', 'budi.s@abc.com', add_months(date_add(current_date(),1),-540), 'ABC', CAST('2019-11-02' AS DATE)),
(4, 'John', 'Doe', 'john.doe@abc.com', CAST('1988-05-12' AS DATE), 'ABC', CAST('2022-06-18' AS DATE)),
(5, 'Jane', 'Smith', 'jane.smith@bni.co.id', CAST('1992-09-25' AS DATE), 'BNI', CAST('2023-02-10' AS DATE));

-- 2. SAVINGS
INSERT INTO test.cai_savings VALUES
(1, 1, 'SAV-BNI-001', 25000000.00, 2.50, 'ACTIVE'),
(2, 2, 'SAV-BNI-002', 75000000.00, 2.75, 'ACTIVE'),
(3, 3, 'SAV-ABC-003', 120000000.00, 3.00, 'ACTIVE'),
(4, 4, 'SAV-ABC-004', 5000000.00, 1.50, 'DORMANT');

-- 3. DEPOSITS
INSERT INTO test.cai_deposits VALUES
(1, 1, 'SAV-BNI-001', 100000000.00, date_add(current_date(),3), 5.25, 'ACTIVE'),
(2, 3, 'SAV-ABC-003', 500000000.00, date_add(current_date(),6), 5.50, 'ACTIVE'),
(3, 4, 'SAV-ABC-004', 50000000.00, date_add(current_date(),180), 4.75, 'ACTIVE');

-- 4. LOANS
INSERT INTO test.cai_loans VALUES
(1, 2, 'Personal', 50000000.00, 4500000.00, date_add(current_date(),5), 'ACTIVE'),
(2, 3, 'Mortgage', 1200000000.00, 980000000.00, add_months(current_date(),120), 'ACTIVE');

-- 5. CREDIT CARDS
INSERT INTO test.cai_credit_cards VALUES
(1, 1, '4560-1234-8888-1111', 50000000.00, 12500000.00, add_months(current_date(),24), 'ACTIVE'),
(2, 4, '4560-1234-8888-2222', 20000000.00, 19500000.00, add_months(current_date(),1), 'WARNING');

-- 6. TRANSACTIONS
INSERT INTO test.cai_transactions VALUES
(1, 'SAV-BNI-001', 500000.00, 'DEBIT', CAST(from_unixtime(unix_timestamp()-7200) AS TIMESTAMP), 'ATM Withdrawal'),
(2, 'SAV-ABC-003', 1500000.00, 'CREDIT', CAST(from_unixtime(unix_timestamp()-86400) AS TIMESTAMP), 'Payroll Transfer');

-- 7. BRANCH PERFORMANCE
INSERT INTO test.cai_branch_performance VALUES
(1, 'Jakarta Main Branch', 'DKI Jakarta', 12500, 104.50),
(2, 'Surabaya Cluster', 'East Java', 8400, 92.10);

/*
TRUNCATE TABLE test.cai_branch_performance;
TRUNCATE TABLE test.cai_credit_cards;
TRUNCATE TABLE test.cai_customers;
TRUNCATE TABLE test.cai_deposits;
TRUNCATE TABLE test.cai_loans;
TRUNCATE TABLE test.cai_savings;
TRUNCATE TABLE test.cai_transactions;
*/

-- ============================================================================
-- DOMAIN 1: CUSTOMER MANAGEMENT
-- ============================================================================

CREATE EXTERNAL TABLE test.cai_customers (
    customer_id BIGINT,
    first_name STRING,
    last_name STRING,
    date_of_birth TIMESTAMP,
    gender STRING,
    created_at TIMESTAMP,
    status STRING
) STORED AS PARQUET;

INSERT INTO test.cai_customers VALUES
(1001, 'Sophia', 'Chen', '1985-04-12 00:00:00', 'F', '2018-01-15 08:30:00', 'ACTIVE'),
(1002, 'Marcus', 'Vance', '1990-11-23 00:00:00', 'M', '2019-03-22 10:15:00', 'ACTIVE'),
(1003, 'Elena', 'Rostova', '1978-07-08 00:00:00', 'F', '2020-06-10 14:00:00', 'ACTIVE'),
(1004, 'David', 'Kim', '1995-02-19 00:00:00', 'M', '2021-09-01 11:45:00', 'INACTIVE'),
(1005, 'Amara', 'Okonkwo', '1982-12-30 00:00:00', 'F', '2022-02-14 09:20:00', 'ACTIVE');

CREATE EXTERNAL TABLE test.cai_customer_addresses (
    address_id BIGINT,
    customer_id BIGINT,
    street_address STRING,
    city STRING,
    state STRING,
    zip_code STRING,
    country STRING,
    is_primary BOOLEAN
) STORED AS PARQUET;

INSERT INTO test.cai_customer_addresses VALUES
(1, 1001, '742 Evergreen Terrace', 'Springfield', 'OR', '97477', 'USA', TRUE),
(2, 1002, '10880 Wilshire Blvd', 'Los Angeles', 'CA', '90024', 'USA', TRUE),
(3, 1003, '200 Park Ave', 'New York', 'NY', '10166', 'USA', TRUE),
(4, 1004, '500 Tech Edge Way', 'Austin', 'TX', '78701', 'USA', TRUE),
(5, 1005, '100 Peachtree St NW', 'Atlanta', 'GA', '30303', 'USA', TRUE);

CREATE EXTERNAL TABLE test.cai_customer_contacts (
    contact_id BIGINT,
    customer_id BIGINT,
    contact_type STRING,
    contact_value STRING,
    is_verified BOOLEAN,
    updated_at TIMESTAMP
) STORED AS PARQUET;

INSERT INTO test.cai_customer_contacts VALUES
(1, 1001, 'EMAIL', 'sophia.chen@example.com', TRUE, '2023-01-10 09:00:00'),
(2, 1001, 'PHONE', '+15550192834', TRUE, '2023-01-10 09:05:00'),
(3, 1002, 'EMAIL', 'm.vance@example.com', TRUE, '2023-02-11 10:00:00'),
(4, 1003, 'EMAIL', 'elena.rostova@example.com', FALSE, '2023-03-15 11:20:00'),
(5, 1005, 'PHONE', '+15550183746', TRUE, '2023-04-01 16:45:00');

CREATE EXTERNAL TABLE test.cai_customer_identifications (
    ident_id BIGINT,
    customer_id BIGINT,
    doc_type STRING,
    doc_number STRING,
    issue_date TIMESTAMP,
    expiry_date TIMESTAMP
) STORED AS PARQUET;

INSERT INTO test.cai_customer_identifications VALUES
(1, 1001, 'PASSPORT', 'A12345678', '2015-05-10 00:00:00', '2025-05-10 00:00:00'),
(2, 1002, 'DRIVERS_LICENSE', 'DL-992019', '2020-01-15 00:00:00', '2028-01-15 00:00:00'),
(3, 1003, 'PASSPORT', 'B98765432', '2018-08-20 00:00:00', '2028-08-20 00:00:00'),
(4, 1004, 'SSN_HASH', 'HASH882910', '2013-03-01 00:00:00', '2099-12-31 00:00:00'),
(5, 1005, 'PASSPORT', 'C55443322', '2019-11-11 00:00:00', '2029-11-11 00:00:00');

CREATE EXTERNAL TABLE test.cai_customer_segments (
    segment_id INT,
    segment_name STRING,
    min_balance DECIMAL(15,2),
    max_balance DECIMAL(15,2),
    description STRING
) STORED AS PARQUET;

INSERT INTO test.cai_customer_segments VALUES
(1, 'STANDARD', 0.00, 9999.99, 'Standard Retail Customer'),
(2, 'GOLD', 10000.00, 99999.99, 'Gold Tier Preferred Banking'),
(3, 'PLATINUM', 100000.00, 499999.99, 'High Balance Preferred'),
(4, 'PRIVATE_BANKING', 500000.00, 9999999.99, 'Ultra High Net Worth Segment'),
(5, 'STUDENT', 0.00, 2500.00, 'Student Discounted Tier');

CREATE EXTERNAL TABLE test.cai_customer_kyc (
    kyc_id BIGINT,
    customer_id BIGINT,
    risk_score INT,
    verification_status STRING,
    last_reviewed_at TIMESTAMP,
    reviewer_employee_id BIGINT
) STORED AS PARQUET;

INSERT INTO test.cai_customer_kyc VALUES
(1, 1001, 12, 'PASSED', '2024-01-10 10:00:00', 5001),
(2, 1002, 45, 'PASSED', '2024-01-12 11:30:00', 5002),
(3, 1003, 85, 'FLAGGED', '2024-02-01 14:15:00', 5001),
(4, 1004, 5, 'PASSED', '2023-11-20 09:00:00', 5003),
(5, 1005, 20, 'PASSED', '2024-01-05 15:00:00', 5002);

-- ============================================================================
-- DOMAIN 2: ACCOUNT MANAGEMENT
-- ============================================================================

CREATE EXTERNAL TABLE test.cai_account_types (
    type_id INT,
    type_name STRING,
    interest_rate DECIMAL(5,4),
    monthly_fee DECIMAL(10,2),
    min_balance_req DECIMAL(12,2)
) STORED AS PARQUET;

INSERT INTO test.cai_type_id_data VALUES -- mapped directly into account_types table syntax below
(1, 'CHECKING', 0.0005, 12.00, 500.00);

CREATE EXTERNAL TABLE test.cai_account_statuses (
    status_id INT,
    status_code STRING,
    description STRING,
    allow_withdrawals BOOLEAN,
    allow_deposits BOOLEAN
) STORED AS PARQUET;

INSERT INTO test.cai_account_statuses VALUES
(1, 'ACTIVE', 'Account operating normally', TRUE, TRUE),
(2, 'FROZEN', 'Account frozen due to suspicious activity', FALSE, FALSE),
(3, 'DORMANT', 'No activity for 12+ months', FALSE, TRUE),
(4, 'OVERDRAWN', 'Negative balance state', FALSE, TRUE),
(5, 'CLOSED', 'Account permanently closed', FALSE, FALSE);

INSERT INTO test.cai_account_types VALUES
(1, 'CHECKING', 0.0005, 12.00, 500.00),
(2, 'SAVINGS', 0.0425, 0.00, 100.00),
(3, 'MONEY_MARKET', 0.0480, 15.00, 2500.00),
(4, 'CERTIFICATE_OF_DEPOSIT', 0.0510, 0.00, 1000.00),
(5, 'BUSINESS_CHECKING', 0.0010, 25.00, 5000.00);

CREATE EXTERNAL TABLE test.cai_accounts (
    account_id BIGINT,
    customer_id BIGINT,
    type_id INT,
    branch_id INT,
    account_number STRING,
    currency STRING,
    open_date TIMESTAMP,
    status_id INT
) STORED AS PARQUET;

INSERT INTO test.cai_accounts VALUES
(2001, 1001, 1, 10, 'ACC-9901001', 'USD', '2018-01-15 09:00:00', 1),
(2002, 1001, 2, 10, 'ACC-9901002', 'USD', '2018-01-16 10:00:00', 1),
(2003, 1002, 1, 11, 'ACC-9902001', 'USD', '2019-03-22 11:00:00', 1),
(2004, 1003, 3, 12, 'ACC-9903001', 'USD', '2020-06-10 15:30:00', 2),
(2005, 1005, 1, 10, 'ACC-9905001', 'USD', '2022-02-14 10:00:00', 1);

CREATE EXTERNAL TABLE test.cai_account_balances (
    balance_id BIGINT,
    account_id BIGINT,
    available_balance DECIMAL(15,2),
    current_balance DECIMAL(15,2),
    pending_balance DECIMAL(15,2),
    last_updated TIMESTAMP
) STORED AS PARQUET;

INSERT INTO test.cai_account_balances VALUES
(1, 2001, 4250.50, 4500.50, 250.00, '2024-03-01 12:00:00'),
(2, 2002, 18500.00, 18500.00, 0.00, '2024-03-01 12:00:00'),
(3, 2003, 120.10, 120.10, 0.00, '2024-03-01 11:30:00'),
(4, 2004, 150200.75, 150200.75, 0.00, '2024-03-01 10:15:00'),
(5, 2005, 8930.22, 9130.22, 200.00, '2024-03-01 14:22:00');

CREATE EXTERNAL TABLE test.cai_joint_account_owners (
    joint_id BIGINT,
    account_id BIGINT,
    customer_id BIGINT,
    relationship_type STRING,
    added_date TIMESTAMP
) STORED AS PARQUET;

INSERT INTO test.cai_joint_account_owners VALUES
(1, 2001, 1002, 'SPOUSE', '2019-05-01 00:00:00'),
(2, 2004, 1001, 'BUSINESS_PARTNER', '2021-01-10 00:00:00'),
(3, 2002, 1005, 'BENEFICIARY', '2022-03-01 00:00:00'),
(4, 2005, 1004, 'SIBLING', '2022-06-15 00:00:00'),
(5, 2003, 1003, 'GUARANTOR', '2023-01-20 00:00:00');

-- ============================================================================
-- DOMAIN 3: BRANCH & HUMAN RESOURCES
-- ============================================================================

CREATE EXTERNAL TABLE test.cai_departments (
    dept_id INT,
    dept_name STRING,
    manager_employee_id BIGINT,
    budget DECIMAL(15,2),
    location_floor INT
) STORED AS PARQUET;

INSERT INTO test.cai_departments VALUES
(100, 'Retail Banking', 5001, 1500000.00, 1),
(101, 'Wealth Management', 5002, 3000000.00, 4),
(102, 'Risk & Compliance', 5003, 2000000.00, 3),
(103, 'Commercial Lending', 5004, 5000000.00, 2),
(104, 'IT & Infrastructure', 5005, 8000000.00, 5);

CREATE EXTERNAL TABLE test.cai_employee_roles (
    role_id INT,
    role_title STRING,
    access_level INT,
    min_salary DECIMAL(10,2),
    max_salary DECIMAL(10,2)
) STORED AS PARQUET;

INSERT INTO test.cai_employee_roles VALUES
(1, 'Bank Teller', 1, 35000.00, 50000.00),
(2, 'Personal Banker', 2, 55000.00, 80000.00),
(3, 'Branch Manager', 4, 90000.00, 140000.00),
(4, 'Compliance Officer', 3, 75000.00, 110000.00),
(5, 'Portfolio Manager', 4, 120000.00, 220000.00);

CREATE EXTERNAL TABLE test.cai_branches (
    branch_id INT,
    branch_code STRING,
    branch_name STRING,
    city STRING,
    state STRING,
    manager_id BIGINT,
    established_date TIMESTAMP
) STORED AS PARQUET;

INSERT INTO test.cai_branches VALUES
(10, 'BR-NYC-01', 'Manhattan Central', 'New York', 'NY', 5001, '2010-06-01 00:00:00'),
(11, 'BR-LAX-01', 'Downtown LA', 'Los Angeles', 'CA', 5002, '2012-09-15 00:00:00'),
(12, 'BR-CHI-01', 'Loop Plaza', 'Chicago', 'IL', 5003, '2015-03-20 00:00:00'),
(13, 'BR-HOU-01', 'Houston Main', 'Houston', 'TX', 5004, '2018-11-05 00:00:00'),
(14, 'BR-MIA-01', 'Biscayne Bay', 'Miami', 'FL', 5005, '2020-01-10 00:00:00');

CREATE EXTERNAL TABLE test.cai_employees (
    employee_id BIGINT,
    first_name STRING,
    last_name STRING,
    dept_id INT,
    branch_id INT,
    role_id INT,
    hire_date TIMESTAMP,
    salary DECIMAL(12,2)
) STORED AS PARQUET;

INSERT INTO test.cai_employees VALUES
(5001, 'Robert', 'Miller', 100, 10, 3, '2012-04-01 00:00:00', 115000.00),
(5002, 'Alice', 'Smith', 101, 11, 5, '2015-08-15 00:00:00', 165000.00),
(5003, 'James', 'Wilson', 102, 12, 4, '2017-01-10 00:00:00', 92000.00),
(5004, 'Karen', 'Davis', 103, 13, 2, '2019-05-20 00:00:00', 68000.00),
(5005, 'John', 'Doe', 100, 10, 1, '2021-09-01 00:00:00', 42000.00);

-- ============================================================================
-- DOMAIN 4: TRANSACTION PROCESSING
-- ============================================================================

CREATE EXTERNAL TABLE test.cai_transaction_types (
    type_id INT,
    type_code STRING,
    description STRING,
    requires_approval BOOLEAN,
    default_fee DECIMAL(8,2)
) STORED AS PARQUET;

INSERT INTO test.cai_transaction_types VALUES
(1, 'DEPOSIT', 'Standard cash or check deposit', FALSE, 0.00),
(2, 'WITHDRAWAL', 'ATM or teller cash withdrawal', FALSE, 0.00),
(3, 'WIRE_OUT', 'Outbound wire transfer', TRUE, 25.00),
(4, 'POS_PAYMENT', 'Point-of-sale card transaction', FALSE, 0.00),
(5, 'FEE_CHARGE', 'Monthly account service charge', FALSE, 0.00);

CREATE EXTERNAL TABLE test.cai_transaction_categories (
    category_id INT,
    category_name STRING,
    is_expense BOOLEAN,
    parent_category_id INT,
    description STRING
) STORED AS PARQUET;

INSERT INTO test.cai_transaction_categories VALUES
(1, 'Payroll', FALSE, NULL, 'Incoming Salary/Income'),
(2, 'Groceries', TRUE, NULL, 'Supermarket purchases'),
(3, 'Utilities', TRUE, NULL, 'Electricity, Water, Gas'),
(4, 'Investment Transfer', FALSE, NULL, 'Capital transfer to wealth accounts'),
(5, 'Internal Fee', TRUE, NULL, 'Service fees levied by bank');

CREATE EXTERNAL TABLE test.cai_transactions (
    transaction_id BIGINT,
    account_id BIGINT,
    type_id INT,
    category_id INT,
    amount DECIMAL(15,2),
    currency STRING,
    tx_timestamp TIMESTAMP,
    status STRING
) STORED AS PARQUET;

INSERT INTO test.cai_transactions VALUES
(3001, 2001, 1, 1, 3000.00, 'USD', '2024-02-01 09:00:00', 'COMPLETED'),
(3002, 2001, 4, 2, -150.25, 'USD', '2024-02-02 14:22:00', 'COMPLETED'),
(3003, 2003, 2, 3, -80.00, 'USD', '2024-02-03 16:00:00', 'COMPLETED'),
(3004, 2004, 3, 4, -50000.00, 'USD', '2024-02-05 11:10:00', 'FLAGGED'),
(3005, 2005, 1, 1, 4500.00, 'USD', '2024-02-10 08:30:00', 'COMPLETED');

CREATE EXTERNAL TABLE test.cai_card_transactions (
    card_tx_id BIGINT,
    transaction_id BIGINT,
    card_id BIGINT,
    merchant_name STRING,
    merchant_category_code STRING,
    terminal_id STRING
) STORED AS PARQUET;

INSERT INTO test.cai_card_transactions VALUES
(1, 3002, 4001, 'Whole Foods Market', '5411', 'TERM-99182'),
(2, 3003, 4003, 'Shell Oil Express', '5541', 'TERM-11029'),
(3, 3001, 4001, 'Branch Deposit Kiosk', '6011', 'TERM-00010'),
(4, 3005, 4005, 'Target Store #102', '5311', 'TERM-44312'),
(5, 3004, 4004, 'Luxury Watches LLC', '5944', 'TERM-88123');

CREATE EXTERNAL TABLE test.cai_wire_transfers (
    wire_id BIGINT,
    transaction_id BIGINT,
    sender_iban STRING,
    receiver_iban STRING,
    swift_code STRING,
    routing_number STRING
) STORED AS PARQUET;

INSERT INTO test.cai_wire_transfers VALUES
(1, 3004, 'US89BANK9903001', 'DE89370400440532013000', 'DBEKDEFFXXX', '021000021'),
(2, 3001, 'US12BANK1002931', 'US89BANK9901001', 'CHASUS33XXX', '021000021'),
(3, 3005, 'US44BANK8830192', 'US89BANK9905001', 'BOFAUS3NXXX', '121000358'),
(4, 3002, 'US89BANK9901001', 'US33BANK1102938', 'WFBIUS6SXXX', '121000358'),
(5, 3003, 'US89BANK9902001', 'US44BANK8810293', 'PNCBUS33XXX', '071000013');

-- ============================================================================
-- DOMAIN 5: CARDS & ATM INFRASTRUCTURE
-- ============================================================================

CREATE EXTERNAL TABLE test.cai_card_types (
    card_type_id INT,
    type_name STRING,
    network STRING,
    credit_limit_max DECIMAL(12,2),
    annual_fee DECIMAL(8,2)
) STORED AS PARQUET;

INSERT INTO test.cai_card_types VALUES
(1, 'DEBIT_STANDARD', 'VISA', 0.00, 0.00),
(2, 'CREDIT_GOLD', 'MASTERCARD', 10000.00, 95.00),
(3, 'CREDIT_PLATINUM', 'VISA', 50000.00, 495.00),
(4, 'DEBIT_BUSINESS', 'VISA', 0.00, 0.00),
(5, 'CREDIT_BLACK', 'AMEX', 250000.00, 2500.00);

CREATE EXTERNAL TABLE test.cai_cards (
    card_id BIGINT,
    account_id BIGINT,
    card_type_id INT,
    card_number_masked STRING,
    expiry_date TIMESTAMP,
    cvv_hash STRING,
    is_active BOOLEAN
) STORED AS PARQUET;

INSERT INTO test.cai_cards VALUES
(4001, 2001, 1, '4111-XXXX-XXXX-1111', '2026-12-31 00:00:00', 'E2FC3F10', TRUE),
(4002, 2001, 2, '5412-XXXX-XXXX-2222', '2027-05-31 00:00:00', '8C1A182B', TRUE),
(4003, 2003, 1, '4111-XXXX-XXXX-3333', '2025-08-31 00:00:00', 'A4D59011', TRUE),
(4004, 2004, 3, '4000-XXXX-XXXX-4444', '2028-01-31 00:00:00', '66A3F109', FALSE),
(4005, 2005, 1, '4111-XXXX-XXXX-5555', '2027-11-30 00:00:00', '77B12C33', TRUE);

CREATE EXTERNAL TABLE test.cai_card_pin_history (
    history_id BIGINT,
    card_id BIGINT,
    changed_at TIMESTAMP,
    ip_address STRING,
    channel STRING
) STORED AS PARQUET;

INSERT INTO test.cai_card_pin_history VALUES
(1, 4001, '2023-01-15 10:00:00', '192.168.1.1', 'MOBILE_APP'),
(2, 4002, '2023-05-10 14:20:00', '10.0.4.12', 'ATM'),
(3, 4003, '2023-08-01 09:12:00', '172.16.0.45', 'WEB_PORTAL'),
(4, 4004, '2024-01-02 11:45:00', '192.168.1.50', 'BRANCH_POS'),
(5, 4005, '2024-02-14 16:30:00', '10.0.4.18', 'ATM');

CREATE EXTERNAL TABLE test.cai_atm_locations (
    atm_id INT,
    branch_id INT,
    atm_code STRING,
    location_address STRING,
    status STRING,
    cash_capacity DECIMAL(12,2)
) STORED AS PARQUET;

INSERT INTO test.cai_atm_locations VALUES
(1, 10, 'ATM-NYC-01', '742 Broadway, NY', 'ONLINE', 250000.00),
(2, 10, 'ATM-NYC-02', '10 Wall St, NY', 'ONLINE', 300000.00),
(3, 11, 'ATM-LAX-01', '500 S Spring St, LA', 'OFFLINE', 150000.00),
(4, 12, 'ATM-CHI-01', '100 N Michigan Ave, Chicago', 'ONLINE', 200000.00),
(5, 13, 'ATM-HOU-01', '1000 Main St, Houston', 'MAINTENANCE', 180000.00);

-- ============================================================================
-- DOMAIN 6: LENDING & CREDIT SERVICES
-- ============================================================================

CREATE EXTERNAL TABLE test.cai_loan_products (
    product_id INT,
    product_name STRING,
    base_interest_rate DECIMAL(5,4),
    max_term_months INT,
    min_credit_score INT
) STORED AS PARQUET;

INSERT INTO test.cai_loan_products VALUES
(1, '30Y Fixed Mortgage', 0.0650, 360, 680),
(2, 'Auto Loan Preferred', 0.0499, 72, 640),
(3, 'Personal Unsecured', 0.1099, 60, 660),
(4, 'Commercial Real Estate', 0.0725, 240, 700),
(5, 'HELOC Standard', 0.0850, 120, 720);

CREATE EXTERNAL TABLE test.cai_loan_applications (
    app_id BIGINT,
    customer_id BIGINT,
    product_id INT,
    requested_amount DECIMAL(15,2),
    app_date TIMESTAMP,
    status STRING
) STORED AS PARQUET;

INSERT INTO test.cai_loan_applications VALUES
(6001, 1001, 1, 450000.00, '2023-03-01 10:00:00', 'APPROVED'),
(6002, 1002, 2, 35000.00, '2023-04-15 11:30:00', 'APPROVED'),
(6003, 1003, 4, 1200000.00, '2023-06-20 14:00:00', 'UNDER_REVIEW'),
(6004, 1004, 3, 15000.00, '2023-09-10 09:15:00', 'REJECTED'),
(6005, 1005, 5, 100000.00, '2023-11-01 15:45:00', 'APPROVED');

CREATE EXTERNAL TABLE test.cai_loans (
    loan_id BIGINT,
    app_id BIGINT,
    customer_id BIGINT,
    principal_amount DECIMAL(15,2),
    interest_rate DECIMAL(5,4),
    term_months INT,
    start_date TIMESTAMP,
    status STRING
) STORED AS PARQUET;

INSERT INTO test.cai_loans VALUES
(7001, 6001, 1001, 450000.00, 0.0650, 360, '2023-04-01 00:00:00', 'ACTIVE'),
(7002, 6002, 1002, 35000.00, 0.0499, 72, '2023-05-01 00:00:00', 'ACTIVE'),
(7003, 6005, 1005, 100000.00, 0.0850, 120, '2023-11-15 00:00:00', 'ACTIVE'),
(7004, 6001, 1001, 20000.00, 0.0700, 24, '2021-01-10 00:00:00', 'PAID_OFF'),
(7005, 6003, 1003, 1200000.00, 0.0725, 240, '2024-01-01 00:00:00', 'DEFAULTED');

CREATE EXTERNAL TABLE test.cai_loan_payments (
    payment_id BIGINT,
    loan_id BIGINT,
    transaction_id BIGINT,
    principal_paid DECIMAL(12,2),
    interest_paid DECIMAL(12,2),
    payment_date TIMESTAMP
) STORED AS PARQUET;

INSERT INTO test.cai_loan_payments VALUES
(1, 7001, 3001, 410.25, 2437.50, '2024-01-01 00:00:00'),
(2, 7001, 3005, 412.47, 2435.28, '2024-02-01 00:00:00'),
(3, 7002, 3002, 415.00, 145.54, '2024-01-15 00:00:00'),
(4, 7002, 3003, 416.73, 143.81, '2024-02-15 00:00:00'),
(5, 7003, 3004, 520.00, 708.33, '2024-01-20 00:00:00');

CREATE EXTERNAL TABLE test.cai_collaterals (
    collateral_id BIGINT,
    loan_id BIGINT,
    collateral_type STRING,
    estimated_value DECIMAL(15,2),
    valuation_date TIMESTAMP
) STORED AS PARQUET;

INSERT INTO test.cai_collaterals VALUES
(1, 7001, 'REAL_ESTATE', 550000.00, '2023-02-15 00:00:00'),
(2, 7002, 'VEHICLE', 42000.00, '2023-04-10 00:00:00'),
(3, 7003, 'REAL_ESTATE', 180000.00, '2023-10-20 00:00:00'),
(4, 7005, 'COMMERCIAL_PROPERTY', 1600000.00, '2023-12-01 00:00:00'),
(5, 7004, 'CERTIFICATE_OF_DEPOSIT', 25000.00, '2021-01-01 00:00:00');

-- ============================================================================
-- DOMAIN 7: INVESTMENT & WEALTH MANAGEMENT
-- ============================================================================

CREATE EXTERNAL TABLE test.cai_investment_accounts (
    inv_account_id BIGINT,
    customer_id BIGINT,
    risk_tolerance STRING,
    portfolio_value DECIMAL(15,2),
    created_at TIMESTAMP
) STORED AS PARQUET;

INSERT INTO test.cai_investment_accounts VALUES
(8001, 1001, 'MODERATE', 125000.50, '2019-06-01 09:00:00'),
(8002, 1002, 'AGGRESSIVE', 45000.00, '2020-01-15 10:30:00'),
(8003, 1003, 'CONSERVATIVE', 2100000.00, '2020-08-20 14:00:00'),
(8004, 1004, 'VERY_AGGRESSIVE', 8500.25, '2022-03-10 11:00:00'),
(8005, 1005, 'MODERATE', 340000.75, '2022-09-01 16:15:00');

CREATE EXTERNAL TABLE test.cai_securities (
    security_id INT,
    ticker_symbol STRING,
    company_name STRING,
    asset_type STRING,
    current_price DECIMAL(12,4)
) STORED AS PARQUET;

INSERT INTO test.cai_securities VALUES
(1, 'AAPL', 'Apple Inc.', 'EQUITY', 182.5000),
(2, 'MSFT', 'Microsoft Corporation', 'EQUITY', 405.1500),
(3, 'UST10Y', 'US Treasury 10-Year Bond', 'FIXED_INCOME', 98.2500),
(4, 'SPY', 'SPDR S&P 500 ETF Trust', 'ETF', 500.4000),
(5, 'NVDA', 'NVIDIA Corporation', 'EQUITY', 780.2000);

CREATE EXTERNAL TABLE test.cai_portfolios (
    portfolio_id BIGINT,
    inv_account_id BIGINT,
    security_id INT,
    quantity DECIMAL(15,4),
    avg_buy_price DECIMAL(12,4)
) STORED AS PARQUET;

INSERT INTO test.cai_portfolios VALUES
(1, 8001, 1, 200.0000, 150.2500),
(2, 8001, 4, 150.0000, 420.0000),
(3, 8002, 5, 50.0000, 520.1000),
(4, 8003, 3, 10000.0000, 99.5000),
(5, 8005, 2, 400.0000, 310.8000);

CREATE EXTERNAL TABLE test.cai_trade_orders (
    order_id BIGINT,
    inv_account_id BIGINT,
    security_id INT,
    order_type STRING,
    quantity DECIMAL(15,4),
    price DECIMAL(12,4),
    order_timestamp TIMESTAMP,
    status STRING
) STORED AS PARQUET;

INSERT INTO test.cai_trade_orders VALUES
(9001, 8001, 1, 'BUY', 50.0000, 180.0000, '2024-02-01 10:00:00', 'EXECUTED'),
(9002, 8002, 5, 'BUY', 10.0000, 775.0000, '2024-02-02 11:15:00', 'EXECUTED'),
(9003, 8003, 3, 'SELL', 500.0000, 98.5000, '2024-02-03 14:30:00', 'EXECUTED'),
(9004, 8004, 4, 'BUY', 5.0000, 502.0000, '2024-02-05 09:45:00', 'CANCELLED'),
(9005, 8005, 2, 'BUY', 25.0000, 400.0000, '2024-02-10 15:00:00', 'EXECUTED');