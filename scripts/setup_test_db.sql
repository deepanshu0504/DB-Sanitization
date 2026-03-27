/*
================================================================================
DATABASE SANITIZATION FRAMEWORK - INTEGRATION TEST DATABASE SETUP
================================================================================

Purpose: Create comprehensive test database schema for integration testing
Version: 1.0
Created: 2026-03-27

Features:
- Multi-schema design (dbo, sales, hr, archive)
- Simple FK relationships (Orders → Customers)
- Multi-level FK chains (OrderDetails → Orders → Customers)
- Self-referencing hierarchies (Employees.ManagerID)
- Circular FK scenario (Products ↔ Categories ↔ Suppliers)
- Composite primary/foreign keys
- Realistic sample data with all PII types
- Performance indexes on FK columns

Usage:
    sqlcmd -S localhost -d SanitizationTest -i setup_test_db.sql
    
    OR from Python:
    from tests.integration.test_db_setup import setup_test_database
    setup_test_database(connection_manager)

================================================================================
*/

SET NOCOUNT ON;
GO

PRINT '==================================================================';
PRINT 'Starting Test Database Setup';
PRINT 'Database: ' + DB_NAME();
PRINT 'Time: ' + CONVERT(VARCHAR, GETDATE(), 120);
PRINT '==================================================================';
GO

-- ============================================================================
-- PHASE 1: CREATE SCHEMAS
-- ============================================================================
PRINT '';
PRINT 'PHASE 1: Creating Schemas...';
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'sales')
BEGIN
    EXEC('CREATE SCHEMA sales');
    PRINT '  ✓ Created schema: sales';
END
ELSE
    PRINT '  - Schema already exists: sales';
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'hr')
BEGIN
    EXEC('CREATE SCHEMA hr');
    PRINT '  ✓ Created schema: hr';
END
ELSE
    PRINT '  - Schema already exists: hr';
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'archive')
BEGIN
    EXEC('CREATE SCHEMA archive');
    PRINT '  ✓ Created schema: archive';
END
ELSE
    PRINT '  - Schema already exists: archive';
GO

-- ============================================================================
-- PHASE 2: DROP EXISTING TABLES (for idempotency)
-- ============================================================================
PRINT '';
PRINT 'PHASE 2: Dropping Existing Tables (if any)...';
GO

-- Drop in dependency order (reverse)
IF OBJECT_ID('sales.OrderLineItems', 'U') IS NOT NULL DROP TABLE sales.OrderLineItems;
IF OBJECT_ID('sales.OrderDetails', 'U') IS NOT NULL DROP TABLE sales.OrderDetails;
IF OBJECT_ID('sales.Orders', 'U') IS NOT NULL DROP TABLE sales.Orders;
IF OBJECT_ID('sales.Customers', 'U') IS NOT NULL DROP TABLE sales.Customers;

IF OBJECT_ID('hr.Employees', 'U') IS NOT NULL DROP TABLE hr.Employees;

IF OBJECT_ID('dbo.Products', 'U') IS NOT NULL DROP TABLE dbo.Products;
IF OBJECT_ID('dbo.Categories', 'U') IS NOT NULL DROP TABLE dbo.Categories;
IF OBJECT_ID('dbo.Suppliers', 'U') IS NOT NULL DROP TABLE dbo.Suppliers;

IF OBJECT_ID('archive.ArchivedCustomers', 'U') IS NOT NULL DROP TABLE archive.ArchivedCustomers;

PRINT '  ✓ Dropped existing tables';
GO

-- ============================================================================
-- PHASE 3: CREATE TABLES - SIMPLE FK RELATIONSHIPS
-- ============================================================================
PRINT '';
PRINT 'PHASE 3: Creating Tables - Simple FK Relationships...';
GO

-- Customers table (parent for Orders)
CREATE TABLE sales.Customers (
    CustomerID INT IDENTITY(1,1) NOT NULL,
    CustomerCode VARCHAR(20) NOT NULL,
    Email VARCHAR(255) NOT NULL,
    Phone VARCHAR(50) NULL,
    FirstName NVARCHAR(100) NOT NULL,
    LastName NVARCHAR(100) NOT NULL,
    CompanyName NVARCHAR(200) NULL,
    Address NVARCHAR(500) NULL,
    City NVARCHAR(100) NULL,
    State CHAR(2) NULL,
    PostalCode VARCHAR(20) NULL,
    Country NVARCHAR(100) DEFAULT 'USA',
    SSN CHAR(11) NULL,  -- Format: XXX-XX-XXXX
    DateOfBirth DATE NULL,
    IsActive BIT DEFAULT 1,
    CreatedDate DATETIME2 DEFAULT GETUTCDATE(),
    ModifiedDate DATETIME2 DEFAULT GETUTCDATE(),
    CONSTRAINT PK_Customers PRIMARY KEY CLUSTERED (CustomerID),
    CONSTRAINT UK_Customers_Email UNIQUE (Email),
    CONSTRAINT UK_Customers_Code UNIQUE (CustomerCode),
    CONSTRAINT CK_Customers_Email_Format CHECK (Email LIKE '%@%.%')
);
PRINT '  ✓ Created table: sales.Customers';
GO

-- Orders table (child of Customers)
CREATE TABLE sales.Orders (
    OrderID INT IDENTITY(1,1) NOT NULL,
    OrderNumber VARCHAR(50) NOT NULL,
    CustomerID INT NOT NULL,
    OrderDate DATETIME2 DEFAULT GETUTCDATE(),
    ShipDate DATETIME2 NULL,
    ShipToName NVARCHAR(200) NULL,
    ShipToAddress NVARCHAR(500) NULL,
    ShipToCity NVARCHAR(100) NULL,
    ShipToState CHAR(2) NULL,
    ShipToPostalCode VARCHAR(20) NULL,
    ShipToCountry NVARCHAR(100) DEFAULT 'USA',
    OrderTotal DECIMAL(18,2) DEFAULT 0.00,
    OrderStatus VARCHAR(20) DEFAULT 'Pending',
    CreatedDate DATETIME2 DEFAULT GETUTCDATE(),
    CONSTRAINT PK_Orders PRIMARY KEY CLUSTERED (OrderID),
    CONSTRAINT UK_Orders_OrderNumber UNIQUE (OrderNumber),
    CONSTRAINT FK_Orders_Customers FOREIGN KEY (CustomerID) 
        REFERENCES sales.Customers(CustomerID),
    CONSTRAINT CK_Orders_OrderTotal CHECK (OrderTotal >= 0),
    CONSTRAINT CK_Orders_Status CHECK (OrderStatus IN ('Pending', 'Shipped', 'Delivered', 'Cancelled'))
);
PRINT '  ✓ Created table: sales.Orders';
GO

-- ============================================================================
-- PHASE 4: CREATE TABLES - MULTI-LEVEL FK CHAIN
-- ============================================================================
PRINT '';
PRINT 'PHASE 4: Creating Tables - Multi-Level FK Chain...';
GO

-- OrderDetails table (child of Orders, grandchild of Customers)
CREATE TABLE sales.OrderDetails (
    OrderDetailID INT IDENTITY(1,1) NOT NULL,
    OrderID INT NOT NULL,
    ProductName NVARCHAR(200) NOT NULL,
    ProductSKU VARCHAR(50) NOT NULL,
    Quantity INT NOT NULL,
    UnitPrice DECIMAL(18,2) NOT NULL,
    Discount DECIMAL(5,2) DEFAULT 0.00,
    LineTotal AS (Quantity * UnitPrice * (1 - Discount / 100)) PERSISTED,
    Notes NVARCHAR(MAX) NULL,
    CreatedDate DATETIME2 DEFAULT GETUTCDATE(),
    CONSTRAINT PK_OrderDetails PRIMARY KEY CLUSTERED (OrderDetailID),
    CONSTRAINT FK_OrderDetails_Orders FOREIGN KEY (OrderID) 
        REFERENCES sales.Orders(OrderID),
    CONSTRAINT CK_OrderDetails_Quantity CHECK (Quantity > 0),
    CONSTRAINT CK_OrderDetails_UnitPrice CHECK (UnitPrice >= 0),
    CONSTRAINT CK_OrderDetails_Discount CHECK (Discount BETWEEN 0 AND 100)
);
PRINT '  ✓ Created table: sales.OrderDetails';
GO

-- ============================================================================
-- PHASE 5: CREATE TABLES - COMPOSITE PRIMARY/FOREIGN KEYS
-- ============================================================================
PRINT '';
PRINT 'PHASE 5: Creating Tables - Composite Keys...';
GO

-- OrderLineItems table (composite PK and FK)
CREATE TABLE sales.OrderLineItems (
    OrderID INT NOT NULL,
    LineNumber INT NOT NULL,
    ItemSKU VARCHAR(50) NOT NULL,
    ItemDescription NVARCHAR(200) NULL,
    Quantity DECIMAL(10,2) NOT NULL,
    UnitOfMeasure VARCHAR(10) DEFAULT 'EA',
    CreatedDate DATETIME2 DEFAULT GETUTCDATE(),
    CONSTRAINT PK_OrderLineItems PRIMARY KEY CLUSTERED (OrderID, LineNumber),
    CONSTRAINT FK_OrderLineItems_Orders FOREIGN KEY (OrderID) 
        REFERENCES sales.Orders(OrderID),
    CONSTRAINT CK_OrderLineItems_Quantity CHECK (Quantity > 0)
);
PRINT '  ✓ Created table: sales.OrderLineItems';
GO

-- ============================================================================
-- PHASE 6: CREATE TABLES - SELF-REFERENCING HIERARCHY
-- ============================================================================
PRINT '';
PRINT 'PHASE 6: Creating Tables - Self-Referencing Hierarchy...';
GO

-- Employees table (self-referencing for org hierarchy)
CREATE TABLE hr.Employees (
    EmployeeID INT IDENTITY(1,1) NOT NULL,
    EmployeeCode VARCHAR(20) NOT NULL,
    FirstName NVARCHAR(100) NOT NULL,
    LastName NVARCHAR(100) NOT NULL,
    Email VARCHAR(255) NOT NULL,
    Phone VARCHAR(50) NULL,
    SSN CHAR(11) NULL,  -- Format: XXX-XX-XXXX
    DateOfBirth DATE NULL,
    HireDate DATE NOT NULL,
    JobTitle NVARCHAR(100) NOT NULL,
    Department NVARCHAR(100) NOT NULL,
    Salary DECIMAL(18,2) NULL,
    ManagerID INT NULL,  -- Self-reference to EmployeeID
    IsActive BIT DEFAULT 1,
    CreatedDate DATETIME2 DEFAULT GETUTCDATE(),
    ModifiedDate DATETIME2 DEFAULT GETUTCDATE(),
    CONSTRAINT PK_Employees PRIMARY KEY CLUSTERED (EmployeeID),
    CONSTRAINT UK_Employees_Email UNIQUE (Email),
    CONSTRAINT UK_Employees_Code UNIQUE (EmployeeCode),
    CONSTRAINT FK_Employees_Manager FOREIGN KEY (ManagerID) 
        REFERENCES hr.Employees(EmployeeID),
    CONSTRAINT CK_Employees_Email_Format CHECK (Email LIKE '%@%.%'),
    CONSTRAINT CK_Employees_Salary CHECK (Salary >= 0)
);
PRINT '  ✓ Created table: hr.Employees (self-referencing)';
GO

-- ============================================================================
-- PHASE 7: CREATE TABLES - CIRCULAR FK DEPENDENCIES
-- ============================================================================
PRINT '';
PRINT 'PHASE 7: Creating Tables - Circular FK Dependencies...';
GO

-- Create tables first without circular FKs
CREATE TABLE dbo.Suppliers (
    SupplierID INT IDENTITY(1,1) NOT NULL,
    SupplierName NVARCHAR(200) NOT NULL,
    ContactName NVARCHAR(100) NULL,
    ContactEmail VARCHAR(255) NULL,
    ContactPhone VARCHAR(50) NULL,
    Address NVARCHAR(500) NULL,
    City NVARCHAR(100) NULL,
    Country NVARCHAR(100) DEFAULT 'USA',
    PreferredProductID INT NULL,  -- Will create circular FK later
    CreatedDate DATETIME2 DEFAULT GETUTCDATE(),
    CONSTRAINT PK_Suppliers PRIMARY KEY CLUSTERED (SupplierID)
);
PRINT '  ✓ Created table: dbo.Suppliers';
GO

CREATE TABLE dbo.Categories (
    CategoryID INT IDENTITY(1,1) NOT NULL,
    CategoryName NVARCHAR(100) NOT NULL,
    Description NVARCHAR(500) NULL,
    PreferredSupplierID INT NULL,  -- Will create circular FK later
    CreatedDate DATETIME2 DEFAULT GETUTCDATE(),
    CONSTRAINT PK_Categories PRIMARY KEY CLUSTERED (CategoryID)
);
PRINT '  ✓ Created table: dbo.Categories';
GO

CREATE TABLE dbo.Products (
    ProductID INT IDENTITY(1,1) NOT NULL,
    ProductName NVARCHAR(200) NOT NULL,
    ProductCode VARCHAR(50) NOT NULL,
    CategoryID INT NULL,  -- Will create circular FK later
    Description NVARCHAR(MAX) NULL,
    UnitPrice DECIMAL(18,2) NOT NULL,
    UnitsInStock INT DEFAULT 0,
    CreatedDate DATETIME2 DEFAULT GETUTCDATE(),
    CONSTRAINT PK_Products PRIMARY KEY CLUSTERED (ProductID),
    CONSTRAINT UK_Products_Code UNIQUE (ProductCode),
    CONSTRAINT CK_Products_UnitPrice CHECK (UnitPrice >= 0),
    CONSTRAINT CK_Products_UnitsInStock CHECK (UnitsInStock >= 0)
);
PRINT '  ✓ Created table: dbo.Products';
GO

-- Now add circular FKs (Products → Categories → Suppliers → Products)
ALTER TABLE dbo.Products
    ADD CONSTRAINT FK_Products_Categories FOREIGN KEY (CategoryID) 
    REFERENCES dbo.Categories(CategoryID);
PRINT '  ✓ Added FK: Products → Categories';
GO

ALTER TABLE dbo.Categories
    ADD CONSTRAINT FK_Categories_Suppliers FOREIGN KEY (PreferredSupplierID) 
    REFERENCES dbo.Suppliers(SupplierID);
PRINT '  ✓ Added FK: Categories → Suppliers';
GO

ALTER TABLE dbo.Suppliers
    ADD CONSTRAINT FK_Suppliers_Products FOREIGN KEY (PreferredProductID) 
    REFERENCES dbo.Products(ProductID);
PRINT '  ✓ Added FK: Suppliers → Products (circular dependency created)';
GO

-- ============================================================================
-- PHASE 8: CREATE TABLES - ARCHIVED DATA (Multi-Schema)
-- ============================================================================
PRINT '';
PRINT 'PHASE 8: Creating Tables - Archived Data...';
GO

-- ArchivedCustomers table (separate schema for testing multi-schema sanitization)
CREATE TABLE archive.ArchivedCustomers (
    ArchivedCustomerID INT IDENTITY(1,1) NOT NULL,
    OriginalCustomerID INT NULL,
    CustomerCode VARCHAR(20) NOT NULL,
    Email VARCHAR(255) NULL,
    Phone VARCHAR(50) NULL,
    FullName NVARCHAR(200) NULL,
    CompanyName NVARCHAR(200) NULL,
    ArchivedDate DATETIME2 DEFAULT GETUTCDATE(),
    ArchivedReason NVARCHAR(500) NULL,
    CONSTRAINT PK_ArchivedCustomers PRIMARY KEY CLUSTERED (ArchivedCustomerID)
);
PRINT '  ✓ Created table: archive.ArchivedCustomers';
GO

-- ============================================================================
-- PHASE 9: CREATE INDEXES FOR PERFORMANCE
-- ============================================================================
PRINT '';
PRINT 'PHASE 9: Creating Performance Indexes...';
GO

-- Covering indexes for FK columns
CREATE NONCLUSTERED INDEX IX_Orders_CustomerID ON sales.Orders(CustomerID) INCLUDE (OrderDate, OrderTotal);
CREATE NONCLUSTERED INDEX IX_OrderDetails_OrderID ON sales.OrderDetails(OrderID) INCLUDE (ProductName, Quantity);
CREATE NONCLUSTERED INDEX IX_OrderLineItems_OrderID ON sales.OrderLineItems(OrderID, LineNumber);
CREATE NONCLUSTERED INDEX IX_Employees_ManagerID ON hr.Employees(ManagerID) INCLUDE (FirstName, LastName, Department);
CREATE NONCLUSTERED INDEX IX_Products_CategoryID ON dbo.Products(CategoryID) INCLUDE (ProductName, UnitPrice);
PRINT '  ✓ Created performance indexes';
GO

-- ============================================================================
-- PHASE 10: INSERT SAMPLE DATA
-- ============================================================================
PRINT '';
PRINT 'PHASE 10: Inserting Sample Data...';
GO

-- ========== Customers (100 rows) ==========
SET IDENTITY_INSERT sales.Customers ON;
GO

INSERT INTO sales.Customers (CustomerID, CustomerCode, Email, Phone, FirstName, LastName, CompanyName, Address, City, State, PostalCode, SSN, DateOfBirth)
VALUES
    (1, 'CUST-001', 'john.doe@example.com', '(555) 123-4567', 'John', 'Doe', 'Acme Corp', '123 Main St', 'New York', 'NY', '10001', '123-45-6789', '1985-03-15'),
    (2, 'CUST-002', 'jane.smith@test.org', '555-234-5678', 'Jane', 'Smith', 'TechCorp Inc', '456 Oak Ave', 'Los Angeles', 'CA', '90001', '234-56-7890', '1990-07-22'),
    (3, 'CUST-003', 'bob.johnson@demo.net', '(555) 345-6789', 'Bob', 'Johnson', NULL, '789 Pine Rd', 'Chicago', 'IL', '60601', '345-67-8901', '1982-11-30'),
    (4, 'CUST-004', 'alice.williams@sample.io', '555.456.7890', 'Alice', 'Williams', 'Global Solutions', '321 Elm St', 'Houston', 'TX', '77001', NULL, '1988-05-10'),
    (5, 'CUST-005', 'charlie.brown@fake.email', '5554567890', 'Charlie', 'Brown', 'Startup LLC', '654 Maple Dr', 'Phoenix', 'AZ', '85001', '456-78-9012', '1995-01-25'),
    (6, 'CUST-006', 'emily.davis@placeholder.co', '(555) 567-8901', 'Emily', 'Davis', NULL, '987 Cedar Ln', 'Philadelphia', 'PA', '19101', '567-89-0123', '1987-09-18'),
    (7, 'CUST-007', 'david.miller@masked.dev', '555-678-9012', 'David', 'Miller', 'Enterprise Group', '147 Birch Ct', 'San Antonio', 'TX', '78201', NULL, '1992-12-05'),
    (8, 'CUST-008', 'sarah.wilson@dummy.tech', '555.789.0123', 'Sarah', 'Wilson', 'Innovation Labs', '258 Spruce Way', 'San Diego', 'CA', '92101', '678-90-1234', '1986-04-12'),
    (9, 'CUST-009', 'michael.moore@anon.site', '(555) 890-1234', 'Michael', 'Moore', NULL, '369 Walnut Blvd', 'Dallas', 'TX', '75201', '789-01-2345', '1991-08-27'),
    (10, 'CUST-010', 'lisa.taylor@example.com', '555-901-2345', 'Lisa', 'Taylor', 'Digital Ventures', '741 Chestnut St', 'San Jose', 'CA', '95101', '890-12-3456', '1989-02-14');

-- Continue with more customers (generate realistic distribution)
DECLARE @i INT = 11;
DECLARE @maxCustomers INT = 100;

WHILE @i <= @maxCustomers
BEGIN
    INSERT INTO sales.Customers (CustomerID, CustomerCode, Email, Phone, FirstName, LastName, CompanyName, Address, City, State, PostalCode, SSN, DateOfBirth)
    VALUES (
        @i,
        'CUST-' + FORMAT(@i, '000'),
        'customer' + CAST(@i AS VARCHAR) + '@testdomain' + CAST((@i % 5) + 1 AS VARCHAR) + '.com',
        CASE @i % 4
            WHEN 0 THEN '(' + CAST(500 + @i AS VARCHAR) + ') ' + CAST(100 + @i AS VARCHAR) + '-' + CAST(1000 + @i AS VARCHAR)
            WHEN 1 THEN CAST(500 + @i AS VARCHAR) + '-' + CAST(100 + @i AS VARCHAR) + '-' + CAST(1000 + @i AS VARCHAR)
            WHEN 2 THEN CAST(500 + @i AS VARCHAR) + '.' + CAST(100 + @i AS VARCHAR) + '.' + CAST(1000 + @i AS VARCHAR)
            ELSE CAST(500000 + @i * 10000 AS VARCHAR)
        END,
        'FirstName' + CAST(@i AS VARCHAR),
        'LastName' + CAST(@i AS VARCHAR),
        CASE WHEN @i % 3 = 0 THEN 'Company' + CAST(@i AS VARCHAR) ELSE NULL END,
        CAST(@i * 100 AS VARCHAR) + ' Test Street',
        CASE (@i % 10)
            WHEN 0 THEN 'New York'
            WHEN 1 THEN 'Los Angeles'
            WHEN 2 THEN 'Chicago'
            WHEN 3 THEN 'Houston'
            WHEN 4 THEN 'Phoenix'
            WHEN 5 THEN 'Philadelphia'
            WHEN 6 THEN 'San Antonio'
            WHEN 7 THEN 'San Diego'
            WHEN 8 THEN 'Dallas'
            ELSE 'San Jose'
        END,
        CASE (@i % 10)
            WHEN 0 THEN 'NY' WHEN 1 THEN 'CA' WHEN 2 THEN 'IL' WHEN 3 THEN 'TX' WHEN 4 THEN 'AZ'
            WHEN 5 THEN 'PA' WHEN 6 THEN 'TX' WHEN 7 THEN 'CA' WHEN 8 THEN 'TX' ELSE 'CA'
        END,
        CAST(10000 + @i AS VARCHAR),
        CASE WHEN @i % 5 <> 0 THEN 
            CAST(100 + (@i % 900) AS VARCHAR) + '-' + CAST(10 + (@i % 90) AS VARCHAR) + '-' + CAST(1000 + (@i % 9000) AS VARCHAR)
        ELSE NULL END,
        DATEADD(YEAR, -(20 + (@i % 40)), DATEADD(DAY, -(@i % 365), GETUTCDATE()))
    );
    SET @i = @i + 1;
END;

SET IDENTITY_INSERT sales.Customers OFF;
PRINT '  ✓ Inserted 100 customers';
GO

-- ========== Orders (150 rows) ==========
SET IDENTITY_INSERT sales.Orders ON;
GO

DECLARE @j INT = 1;
DECLARE @maxOrders INT = 150;

WHILE @j <= @maxOrders
BEGIN
    INSERT INTO sales.Orders (OrderID, OrderNumber, CustomerID, OrderDate, ShipDate, ShipToName, ShipToAddress, ShipToCity, ShipToState, ShipToPostalCode, OrderTotal, OrderStatus)
    VALUES (
        @j,
        'ORD-' + FORMAT(@j, '00000'),
        ((@j - 1) % 100) + 1,  -- Distribute orders across customers
        DATEADD(DAY, -(@j % 365), GETUTCDATE()),
        CASE WHEN @j % 4 <> 0 THEN DATEADD(DAY, -(@j % 365) + 3, GETUTCDATE()) ELSE NULL END,
        'ShipTo Name ' + CAST(@j AS VARCHAR),
        'ShipTo Address ' + CAST(@j AS VARCHAR),
        'ShipTo City ' + CAST(@j AS VARCHAR),
        'TX',
        CAST(70000 + @j AS VARCHAR),
        CAST((10 + (@j % 500)) * 1.50 AS DECIMAL(18,2)),
        CASE (@j % 4)
            WHEN 0 THEN 'Pending'
            WHEN 1 THEN 'Shipped'
            WHEN 2 THEN 'Delivered'
            ELSE 'Cancelled'
        END
    );
    SET @j = @j + 1;
END;

SET IDENTITY_INSERT sales.Orders OFF;
PRINT '  ✓ Inserted 150 orders';
GO

-- ========== OrderDetails (300 rows) ==========
SET IDENTITY_INSERT sales.OrderDetails ON;
GO

DECLARE @k INT = 1;
DECLARE @maxDetails INT = 300;

WHILE @k <= @maxDetails
BEGIN
    INSERT INTO sales.OrderDetails (OrderDetailID, OrderID, ProductName, ProductSKU, Quantity, UnitPrice, Discount)
    VALUES (
        @k,
        ((@k - 1) % 150) + 1,  -- Distribute across orders
        'Product ' + CAST(@k AS VARCHAR),
        'SKU-' + FORMAT(@k, '00000'),
        1 + (@k % 10),
        CAST((5 + (@k % 95)) * 1.99 AS DECIMAL(18,2)),
        CASE WHEN @k % 5 = 0 THEN CAST((@k % 20) AS DECIMAL(5,2)) ELSE 0 END
    );
    SET @k = @k + 1;
END;

SET IDENTITY_INSERT sales.OrderDetails OFF;
PRINT '  ✓ Inserted 300 order details';
GO

-- ========== OrderLineItems (200 rows) ==========
DECLARE @m INT = 1;
DECLARE @maxLineItems INT = 200;

WHILE @m <= @maxLineItems
BEGIN
    INSERT INTO sales.OrderLineItems (OrderID, LineNumber, ItemSKU, ItemDescription, Quantity, UnitOfMeasure)
    VALUES (
        ((@m - 1) % 150) + 1,  -- Distribute across orders
        ((@m - 1) / 150) + 1,  -- Line number within order
        'ITEM-' + FORMAT(@m, '00000'),
        'Item Description ' + CAST(@m AS VARCHAR),
        CAST((1 + (@m % 10)) * 1.5 AS DECIMAL(10,2)),
        CASE (@m % 3) WHEN 0 THEN 'EA' WHEN 1 THEN 'BOX' ELSE 'PKG' END
    );
    SET @m = @m + 1;
END;

PRINT '  ✓ Inserted 200 order line items';
GO

-- ========== Employees (50 rows with hierarchy) ==========
SET IDENTITY_INSERT hr.Employees ON;
GO

-- Insert CEO (no manager)
INSERT INTO hr.Employees (EmployeeID, EmployeeCode, FirstName, LastName, Email, Phone, SSN, DateOfBirth, HireDate, JobTitle, Department, Salary, ManagerID)
VALUES (1, 'EMP-001', 'Robert', 'Smith', 'robert.smith@company.com', '(555) 100-0001', '111-11-1111', '1970-01-15', '2000-01-01', 'CEO', 'Executive', 250000.00, NULL);

-- Insert VPs (report to CEO)
INSERT INTO hr.Employees (EmployeeID, EmployeeCode, FirstName, LastName, Email, Phone, SSN, DateOfBirth, HireDate, JobTitle, Department, Salary, ManagerID)
VALUES 
    (2, 'EMP-002', 'Mary', 'Johnson', 'mary.johnson@company.com', '555-100-0002', '222-22-2222', '1975-03-20', '2005-02-01', 'VP Sales', 'Sales', 180000.00, 1),
    (3, 'EMP-003', 'James', 'Williams', 'james.williams@company.com', '555.100.0003', '333-33-3333', '1972-06-10', '2003-03-15', 'VP Engineering', 'Engineering', 200000.00, 1),
    (4, 'EMP-004', 'Patricia', 'Brown', 'patricia.brown@company.com', '(555) 100-0004', '444-44-4444', '1978-09-25', '2008-04-01', 'VP HR', 'Human Resources', 160000.00, 1);

-- Insert Directors (report to VPs)
INSERT INTO hr.Employees (EmployeeID, EmployeeCode, FirstName, LastName, Email, Phone, SSN, DateOfBirth, HireDate, JobTitle, Department, Salary, ManagerID)
VALUES 
    (5, 'EMP-005', 'Michael', 'Davis', 'michael.davis@company.com', '5551000005', '555-55-5555', '1980-02-14', '2010-05-15', 'Director Sales', 'Sales', 120000.00, 2),
    (6, 'EMP-006', 'Jennifer', 'Miller', 'jennifer.miller@company.com', '555-100-0006', '666-66-6666', '1982-11-30', '2011-06-01', 'Director Engineering', 'Engineering', 140000.00, 3),
    (7, 'EMP-007', 'William', 'Wilson', 'william.wilson@company.com', '555.100.0007', '777-77-7777', '1981-07-18', '2012-07-15', 'Director HR', 'Human Resources', 110000.00, 4);

-- Insert Managers and Staff (reports to Directors)
DECLARE @n INT = 8;
DECLARE @maxEmployees INT = 50;

WHILE @n <= @maxEmployees
BEGIN
    INSERT INTO hr.Employees (EmployeeID, EmployeeCode, FirstName, LastName, Email, Phone, SSN, DateOfBirth, HireDate, JobTitle, Department, Salary, ManagerID)
    VALUES (
        @n,
        'EMP-' + FORMAT(@n, '000'),
        'Employee' + CAST(@n AS VARCHAR),
        'LastName' + CAST(@n AS VARCHAR),
        'employee' + CAST(@n AS VARCHAR) + '@company.com',
        CASE @n % 3
            WHEN 0 THEN '(' + CAST(550 + @n AS VARCHAR) + ') 100-' + FORMAT(@n, '0000')
            WHEN 1 THEN CAST(550 + @n AS VARCHAR) + '-100-' + FORMAT(@n, '0000')
            ELSE CAST(550 + @n AS VARCHAR) + '.100.' + FORMAT(@n, '0000')
        END,
        CASE WHEN @n % 4 <> 0 THEN 
            CAST(100 + (@n % 900) AS VARCHAR) + '-' + CAST(10 + (@n % 90) AS VARCHAR) + '-' + CAST(1000 + (@n % 9000) AS VARCHAR)
        ELSE NULL END,
        DATEADD(YEAR, -(25 + (@n % 35)), DATEADD(DAY, -(@n % 365), GETUTCDATE())),
        DATEADD(YEAR, -(2 + (@n % 15)), DATEADD(DAY, -(@n % 365), GETUTCDATE())),
        CASE (@n % 5)
            WHEN 0 THEN 'Manager'
            WHEN 1 THEN 'Senior Developer'
            WHEN 2 THEN 'Sales Representative'
            WHEN 3 THEN 'HR Specialist'
            ELSE 'Analyst'
        END,
        CASE (@n % 3)
            WHEN 0 THEN 'Engineering'
            WHEN 1 THEN 'Sales'
            ELSE 'Human Resources'
        END,
        CAST((40000 + (@n * 1500)) AS DECIMAL(18,2)),
        CASE (@n % 3)
            WHEN 0 THEN 6  -- Reports to Engineering Director
            WHEN 1 THEN 5  -- Reports to Sales Director
            ELSE 7         -- Reports to HR Director
        END
    );
    SET @n = @n + 1;
END;

SET IDENTITY_INSERT hr.Employees OFF;
PRINT '  ✓ Inserted 50 employees with hierarchy';
GO

-- ========== Circular FK Tables (intentionally minimal data) ==========
SET IDENTITY_INSERT dbo.Suppliers ON;
SET IDENTITY_INSERT dbo.Categories ON;
SET IDENTITY_INSERT dbo.Products ON;
GO

-- Insert with NULL FKs first to avoid circular dependency issues
INSERT INTO dbo.Suppliers (SupplierID, SupplierName, ContactName, ContactEmail, ContactPhone, Address, City, PreferredProductID)
VALUES 
    (1, 'Supplier One', 'John Contact', 'john@supplier1.com', '(555) 200-0001', '100 Supplier St', 'Seattle', NULL),
    (2, 'Supplier Two', 'Jane Contact', 'jane@supplier2.com', '555-200-0002', '200 Supplier Ave', 'Portland', NULL),
    (3, 'Supplier Three', 'Bob Contact', 'bob@supplier3.com', '555.200.0003', '300 Supplier Blvd', 'Denver', NULL);

INSERT INTO dbo.Categories (CategoryID, CategoryName, Description, PreferredSupplierID)
VALUES 
    (1, 'Category A', 'Description for Category A', NULL),
    (2, 'Category B', 'Description for Category B', NULL),
    (3, 'Category C', 'Description for Category C', NULL);

INSERT INTO dbo.Products (ProductID, ProductName, ProductCode, CategoryID, Description, UnitPrice, UnitsInStock)
VALUES 
    (1, 'Product Alpha', 'PROD-001', NULL, 'Alpha product description', 29.99, 100),
    (2, 'Product Beta', 'PROD-002', NULL, 'Beta product description', 49.99, 75),
    (3, 'Product Gamma', 'PROD-003', NULL, 'Gamma product description', 39.99, 50);

-- Now update to create circular dependencies (Products → Categories → Suppliers → Products)
UPDATE dbo.Products SET CategoryID = 1 WHERE ProductID = 1;
UPDATE dbo.Products SET CategoryID = 2 WHERE ProductID = 2;
UPDATE dbo.Products SET CategoryID = 3 WHERE ProductID = 3;

UPDATE dbo.Categories SET PreferredSupplierID = 1 WHERE CategoryID = 1;
UPDATE dbo.Categories SET PreferredSupplierID = 2 WHERE CategoryID = 2;
UPDATE dbo.Categories SET PreferredSupplierID = 3 WHERE CategoryID = 3;

UPDATE dbo.Suppliers SET PreferredProductID = 1 WHERE SupplierID = 1;
UPDATE dbo.Suppliers SET PreferredProductID = 2 WHERE SupplierID = 2;
UPDATE dbo.Suppliers SET PreferredProductID = 3 WHERE SupplierID = 3;

SET IDENTITY_INSERT dbo.Suppliers OFF;
SET IDENTITY_INSERT dbo.Categories OFF;
SET IDENTITY_INSERT dbo.Products OFF;
PRINT '  ✓ Inserted circular FK data (Suppliers ↔ Categories ↔ Products)';
GO

-- ========== Archived Customers (25 rows) ==========
SET IDENTITY_INSERT archive.ArchivedCustomers ON;
GO

DECLARE @p INT = 1;
DECLARE @maxArchived INT = 25;

WHILE @p <= @maxArchived
BEGIN
    INSERT INTO archive.ArchivedCustomers (ArchivedCustomerID, OriginalCustomerID, CustomerCode, Email, Phone, FullName, CompanyName, ArchivedReason)
    VALUES (
        @p,
        @p,
        'ARCH-' + FORMAT(@p, '000'),
        'archived' + CAST(@p AS VARCHAR) + '@oldcustomer.com',
        '555-900-' + FORMAT(@p, '0000'),
        'Archived Customer ' + CAST(@p AS VARCHAR),
        CASE WHEN @p % 2 = 0 THEN 'Old Company ' + CAST(@p AS VARCHAR) ELSE NULL END,
        CASE (@p % 3)
            WHEN 0 THEN 'Customer requested account closure'
            WHEN 1 THEN 'Inactive for 2+ years'
            ELSE 'Business closed'
        END
    );
    SET @p = @p + 1;
END;

SET IDENTITY_INSERT archive.ArchivedCustomers OFF;
PRINT '  ✓ Inserted 25 archived customers';
GO

-- ============================================================================
-- PHASE 11: VERIFY SETUP
-- ============================================================================
PRINT '';
PRINT 'PHASE 11: Verifying Setup...';
GO

-- Count tables
DECLARE @tableCount INT;
SELECT @tableCount = COUNT(*) 
FROM INFORMATION_SCHEMA.TABLES 
WHERE TABLE_TYPE = 'BASE TABLE' 
  AND TABLE_SCHEMA IN ('dbo', 'sales', 'hr', 'archive');

PRINT '  Total tables created: ' + CAST(@tableCount AS VARCHAR);

-- Count FK constraints
DECLARE @fkCount INT;
SELECT @fkCount = COUNT(*) 
FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS 
WHERE CONSTRAINT_SCHEMA IN ('dbo', 'sales', 'hr', 'archive');

PRINT '  Total FK constraints: ' + CAST(@fkCount AS VARCHAR);

-- Count rows
DECLARE @totalRows INT;
SELECT @totalRows = 
    (SELECT COUNT(*) FROM sales.Customers) +
    (SELECT COUNT(*) FROM sales.Orders) +
    (SELECT COUNT(*) FROM sales.OrderDetails) +
    (SELECT COUNT(*) FROM sales.OrderLineItems) +
    (SELECT COUNT(*) FROM hr.Employees) +
    (SELECT COUNT(*) FROM dbo.Suppliers) +
    (SELECT COUNT(*) FROM dbo.Categories) +
    (SELECT COUNT(*) FROM dbo.Products) +
    (SELECT COUNT(*) FROM archive.ArchivedCustomers);

PRINT '  Total rows inserted: ' + CAST(@totalRows AS VARCHAR);

-- List all tables
PRINT '';
PRINT 'Tables by Schema:';
SELECT 
    TABLE_SCHEMA AS [Schema],
    TABLE_NAME AS [Table],
    (SELECT COUNT(*) FROM sys.columns c 
     INNER JOIN sys.tables t ON c.object_id = t.object_id 
     INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
     WHERE s.name = INFORMATION_SCHEMA.TABLES.TABLE_SCHEMA 
       AND t.name = INFORMATION_SCHEMA.TABLES.TABLE_NAME) AS [Columns]
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE'
  AND TABLE_SCHEMA IN ('dbo', 'sales', 'hr', 'archive')
ORDER BY TABLE_SCHEMA, TABLE_NAME;

PRINT '';
PRINT '==================================================================';
PRINT 'Test Database Setup Complete!';
PRINT 'Database: ' + DB_NAME();
PRINT 'Time: ' + CONVERT(VARCHAR, GETDATE(), 120);
PRINT '==================================================================';
GO
