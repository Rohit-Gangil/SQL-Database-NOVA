
BEGIN
  EXECUTE IMMEDIATE 'DROP TABLE Drugs_Prescribed CASCADE CONSTRAINTS';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/
BEGIN
  EXECUTE IMMEDIATE 'DROP TABLE Prescription CASCADE CONSTRAINTS';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/
BEGIN
  EXECUTE IMMEDIATE 'DROP TABLE Patient CASCADE CONSTRAINTS';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/
BEGIN
  EXECUTE IMMEDIATE 'DROP TABLE Doctor CASCADE CONSTRAINTS';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/
BEGIN
  EXECUTE IMMEDIATE 'DROP TABLE Pharmacy_Sells CASCADE CONSTRAINTS';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/
BEGIN
  EXECUTE IMMEDIATE 'DROP TABLE Contract_With CASCADE CONSTRAINTS';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/
BEGIN
  EXECUTE IMMEDIATE 'DROP TABLE Drugs CASCADE CONSTRAINTS';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/
BEGIN
  EXECUTE IMMEDIATE 'DROP TABLE Pharmaceutical_Company CASCADE CONSTRAINTS';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/
BEGIN
  EXECUTE IMMEDIATE 'DROP TABLE Pharmacy CASCADE CONSTRAINTS';
EXCEPTION WHEN OTHERS THEN NULL;
END;
/
BEGIN
   EXECUTE IMMEDIATE 'DROP TABLE Contract_With CASCADE CONSTRAINTS';
EXCEPTION
   WHEN OTHERS THEN NULL;
END;
/

BEGIN
   EXECUTE IMMEDIATE 'DROP TABLE Drugs CASCADE CONSTRAINTS';
EXCEPTION
   WHEN OTHERS THEN NULL;
END;
/

BEGIN
   EXECUTE IMMEDIATE 'DROP TABLE Pharmaceutical_Company CASCADE CONSTRAINTS';
EXCEPTION
   WHEN OTHERS THEN NULL;
END;
/

BEGIN
   EXECUTE IMMEDIATE 'DROP TABLE Pharmacy CASCADE CONSTRAINTS';
EXCEPTION
   WHEN OTHERS THEN NULL;
END;
/

-- Create tables
CREATE TABLE Pharmacy (
    Ph_name VARCHAR2(100) PRIMARY KEY,
    address VARCHAR2(200),
    phone VARCHAR2(15)
);

CREATE TABLE Pharmaceutical_Company (
    P_name VARCHAR2(100) PRIMARY KEY,
    phone_no VARCHAR2(15)
);

CREATE TABLE Drugs (
    trade_name VARCHAR2(100),
    P_name VARCHAR2(100),
    formula VARCHAR2(200),
    PRIMARY KEY (trade_name, P_name),
    FOREIGN KEY (P_name) REFERENCES Pharmaceutical_Company(P_name) ON DELETE CASCADE
);

CREATE TABLE Doctor (
    aadhar_id VARCHAR2(12) PRIMARY KEY,
    name VARCHAR2(100),
    specialty VARCHAR2(100),
    year_of_exp NUMBER
);


CREATE TABLE Stock (
    pharmacy_1 VARCHAR2(100) PRIMARY KEY,
    stock VARCHAR2(100),
    FOREIGN KEY ( pharmacy_1) REFERENCES Pharmacy(Ph_name)
    
);


CREATE TABLE Patient (
    aadhar_id VARCHAR2(12) PRIMARY KEY,
    name VARCHAR2(100),
    address VARCHAR2(200),
    age NUMBER,
    D_aadhar VARCHAR2(12),
    FOREIGN KEY (D_aadhar) REFERENCES Doctor(aadhar_id)
);

CREATE TABLE Prescription (
    doctor_id VARCHAR2(12),
    patient_id VARCHAR2(12),
    date_prescribed DATE,
    PRIMARY KEY (doctor_id, patient_id, date_prescribed),
    FOREIGN KEY (doctor_id) REFERENCES Doctor(aadhar_id),
    FOREIGN KEY (patient_id) REFERENCES Patient(aadhar_id)
);

CREATE TABLE Drugs_Prescribed (
    P_name VARCHAR2(100),
    trade_name VARCHAR2(100),
    doctor_id VARCHAR2(12),
    patient_id VARCHAR2(12),
    date_prescribed DATE,
    qty NUMBER,
    PRIMARY KEY (P_name, trade_name, doctor_id, patient_id, date_prescribed),
    FOREIGN KEY (P_name) REFERENCES Pharmaceutical_Company(P_name),
    FOREIGN KEY (trade_name, P_name) REFERENCES Drugs(trade_name, P_name),
    FOREIGN KEY (doctor_id, patient_id, date_prescribed)
        REFERENCES Prescription(doctor_id, patient_id, date_prescribed)
);

CREATE TABLE Contract_With (
    P_name VARCHAR2(100),
    Ph_name VARCHAR2(100),
    start_date DATE,
    end_date DATE,
    contract_content VARCHAR2(500),
    supervisor VARCHAR2(100),
    PRIMARY KEY (P_name, Ph_name),
    FOREIGN KEY (P_name) REFERENCES Pharmaceutical_Company(P_name),
    FOREIGN KEY (Ph_name) REFERENCES Pharmacy(Ph_name)
);

CREATE TABLE Pharmacy_Sells (
    Ph_name VARCHAR2(100),
    P_name VARCHAR2(100),
    trade_name VARCHAR2(100),
    price NUMBER(10,2),
    PRIMARY KEY (Ph_name, trade_name, P_name),
    FOREIGN KEY (P_name) REFERENCES Pharmaceutical_Company(P_name),
    FOREIGN KEY (Ph_name) REFERENCES Pharmacy(Ph_name),
    FOREIGN KEY (trade_name, P_name) REFERENCES Drugs(trade_name, P_name)
);

-- Procedures with error handling
CREATE OR REPLACE PROCEDURE add_pharmacy(
    Ph_name VARCHAR2, address VARCHAR2, phone VARCHAR2
) AS
BEGIN
    INSERT INTO Pharmacy VALUES (Ph_name, address, phone);
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Pharmacy added successfully.');
EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
        DBMS_OUTPUT.PUT_LINE('Error: Pharmacy with name ' || Ph_name || ' already exists.');
        ROLLBACK;
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error adding pharmacy: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE delete_pharmacy(p_name VARCHAR2) AS
    v_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_count FROM Pharmacy WHERE Ph_name = p_name;
    
    IF v_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Pharmacy ' || p_name || ' does not exist.');
        RETURN;
    END IF;
    
    DELETE FROM Pharmacy WHERE Ph_name = p_name;
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Pharmacy deleted successfully.');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error deleting pharmacy: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE add_company(
    p_name VARCHAR2, phone_no VARCHAR2
) AS
BEGIN
    INSERT INTO Pharmaceutical_Company VALUES(p_name, phone_no);
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Pharmaceutical company added successfully.');
EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
        DBMS_OUTPUT.PUT_LINE('Error: Company with name ' || p_name || ' already exists.');
        ROLLBACK;
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error adding company: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE delete_company(name VARCHAR2) AS
    v_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_count FROM Pharmaceutical_Company WHERE p_name = name;
    
    IF v_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Company ' || name || ' does not exist.');
        RETURN;
    END IF;
    
    DELETE FROM Pharmaceutical_Company WHERE p_name = name;
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Company deleted successfully.');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error deleting company: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE add_contract(
    p_name VARCHAR2, ph_name VARCHAR2,
    s_date DATE, e_date DATE,
    contract_content VARCHAR2, supervisor VARCHAR2
) AS
    v_company_count NUMBER;
    v_pharmacy_count NUMBER;
BEGIN
    -- Check if company exists
    SELECT COUNT(*) INTO v_company_count FROM Pharmaceutical_Company WHERE P_name = p_name;
    IF v_company_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Company ' || p_name || ' does not exist.');
        RETURN;
    END IF;
    
    -- Check if pharmacy exists
    SELECT COUNT(*) INTO v_pharmacy_count FROM Pharmacy WHERE Ph_name = ph_name;
    IF v_pharmacy_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Pharmacy ' || ph_name || ' does not exist.');
        RETURN;
    END IF;
    
    -- Check if end date is after start date
    IF e_date <= s_date THEN
        DBMS_OUTPUT.PUT_LINE('Error: End date must be after start date.');
        RETURN;
    END IF;
    
    INSERT INTO Contract_With
    VALUES(p_name, ph_name, s_date, e_date, contract_content, supervisor);
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Contract added successfully.');
EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
        DBMS_OUTPUT.PUT_LINE('Error: Contract between ' || p_name || ' and ' || ph_name || ' already exists.');
        ROLLBACK;
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error adding contract: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE delete_contract(p_name VARCHAR2, ph_name VARCHAR2) AS
    v_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_count FROM Contract_With 
    WHERE P_name = p_name AND Ph_name = ph_name;
    
    IF v_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Contract between ' || p_name || ' and ' || ph_name || ' does not exist.');
        RETURN;
    END IF;
    
    DELETE FROM Contract_With WHERE P_name = p_name AND Ph_name = ph_name;
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Contract deleted successfully.');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error deleting contract: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE add_drug(
    trade_name VARCHAR2, p_name VARCHAR2, formula VARCHAR2
) AS
    v_company_count NUMBER;
BEGIN
    -- Check if company exists
    SELECT COUNT(*) INTO v_company_count FROM Pharmaceutical_Company WHERE P_name = p_name;
    IF v_company_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Company ' || p_name || ' does not exist.');
        RETURN;
    END IF;
    
    INSERT INTO Drugs VALUES(trade_name, p_name, formula);
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Drug added successfully.');
EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
        DBMS_OUTPUT.PUT_LINE('Error: Drug ' || trade_name || ' by company ' || p_name || ' already exists.');
        ROLLBACK;
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error adding drug: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE delete_drug(
    p_trade_name VARCHAR2, p_name VARCHAR2
) AS
    v_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_count FROM Drugs
    WHERE trade_name = p_trade_name AND P_name = p_name;
    
    IF v_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Drug ' || p_trade_name || ' by company ' || p_name || ' does not exist.');
        RETURN;
    END IF;
    
    DELETE FROM Drugs
    WHERE trade_name = p_trade_name AND P_name = p_name;
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Drug deleted successfully.');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error deleting drug: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE add_sale(
    ph_name VARCHAR2, p_name VARCHAR2,
    trade_name VARCHAR2, price NUMBER
) AS
    v_pharmacy_count NUMBER;
    v_drug_count NUMBER;
BEGIN
    -- Check if pharmacy exists
    SELECT COUNT(*) INTO v_pharmacy_count FROM Pharmacy WHERE Ph_name = ph_name;
    IF v_pharmacy_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Pharmacy ' || ph_name || ' does not exist.');
        RETURN;
    END IF;
    
    -- Check if drug exists
    SELECT COUNT(*) INTO v_drug_count FROM Drugs
    WHERE trade_name = trade_name AND P_name = p_name;
    IF v_drug_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Drug ' || trade_name || ' by company ' || p_name || ' does not exist.');
        RETURN;
    END IF;
    
    -- Check price is positive
    IF price <= 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Price must be positive.');
        RETURN;
    END IF;
    
    INSERT INTO Pharmacy_Sells VALUES(ph_name, p_name, trade_name, price);
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Sale added successfully.');
EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
        DBMS_OUTPUT.PUT_LINE('Error: Drug ' || trade_name || ' by company ' || p_name || ' is already sold at ' || ph_name);
        ROLLBACK;
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error adding sale: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE delete_sale(
    ph_name VARCHAR2, p_name VARCHAR2, trade_name VARCHAR2
) AS
    v_count NUMBER;
    v_total_drugs NUMBER;
BEGIN
    -- Check if sale exists
    SELECT COUNT(*) INTO v_count FROM Pharmacy_Sells
    WHERE Ph_name = ph_name AND P_name = p_name AND trade_name = trade_name;
    
    IF v_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Sale for drug ' || trade_name || ' by company ' || p_name || ' at pharmacy ' || ph_name || ' does not exist.');
        RETURN;
    END IF;
    
    -- Count total drugs at this pharmacy
    SELECT COUNT(*) INTO v_total_drugs FROM Pharmacy_Sells WHERE Ph_name = ph_name;
    IF v_total_drugs <= 10 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Cannot delete drug. Pharmacy must have at least 10 drugs.');
        RETURN;
    END IF;
    
    DELETE FROM Pharmacy_Sells
    WHERE Ph_name = ph_name AND P_name = p_name AND trade_name = trade_name;
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Sale deleted successfully.');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error deleting sale: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE add_doctor(
    aadhar_id VARCHAR2, name VARCHAR2,
    specialty VARCHAR2, year_of_exp NUMBER
) AS
BEGIN
    -- Check aadhar length
    IF LENGTH(aadhar_id) != 12 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Aadhar ID must be 12 digits.');
        RETURN;
    END IF;
    
    -- Check experience is non-negative
    IF year_of_exp < 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Years of experience cannot be negative.');
        RETURN;
    END IF;
    
    INSERT INTO Doctor VALUES(aadhar_id, name, specialty, year_of_exp);
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Doctor added successfully.');
EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
        DBMS_OUTPUT.PUT_LINE('Error: Doctor with Aadhar ID ' || aadhar_id || ' already exists.');
        ROLLBACK;
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error adding doctor: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE delete_doctor(d_aadhar_id VARCHAR2) AS
    v_count NUMBER;
    v_patient_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_count FROM Doctor WHERE aadhar_id = d_aadhar_id;
    
    IF v_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Doctor with Aadhar ID ' || d_aadhar_id || ' does not exist.');
        RETURN;
    END IF;
    
    -- Check if doctor has patients
    SELECT COUNT(*) INTO v_patient_count FROM Patient WHERE D_aadhar = d_aadhar_id;
    IF v_patient_count > 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Cannot delete doctor. Doctor has ' || v_patient_count || ' patients.');
        RETURN;
    END IF;
    
    DELETE FROM Doctor WHERE aadhar_id = d_aadhar_id;
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Doctor deleted successfully.');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error deleting doctor: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE add_patient(
    aadhar_id VARCHAR2, name VARCHAR2,
    address VARCHAR2, age NUMBER, d_aadhar VARCHAR2
) AS
    v_doctor_count NUMBER;
BEGIN
    -- Check aadhar length
    IF LENGTH(aadhar_id) != 12 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Aadhar ID must be 12 digits.');
        RETURN;
    END IF;
    
    -- Check age is valid
    IF age <= 0 OR age > 120 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Age must be between 1 and 120.');
        RETURN;
    END IF;
    
    -- Check if doctor exists
    SELECT COUNT(*) INTO v_doctor_count FROM Doctor WHERE aadhar_id = d_aadhar;
    IF v_doctor_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Doctor with Aadhar ID ' || d_aadhar || ' does not exist.');
        RETURN;
    END IF;
    
    INSERT INTO Patient VALUES(aadhar_id, name, address, age, d_aadhar);
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Patient added successfully.');
EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
        DBMS_OUTPUT.PUT_LINE('Error: Patient with Aadhar ID ' || aadhar_id || ' already exists.');
        ROLLBACK;
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error adding patient: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE delete_patient(p_aadhar_id VARCHAR2) AS
    v_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_count FROM Patient WHERE aadhar_id = p_aadhar_id;
    
    IF v_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Patient with Aadhar ID ' || p_aadhar_id || ' does not exist.');
        RETURN;
    END IF;
    
    DELETE FROM Patient WHERE aadhar_id = p_aadhar_id;
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Patient deleted successfully.');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error deleting patient: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE add_prescription(
    doc_id VARCHAR2, pat_id VARCHAR2, date_p DATE
) AS
    v_doctor_count NUMBER;
    v_patient_count NUMBER;
    v_existing_count NUMBER;
BEGIN
    -- Check if doctor exists
    SELECT COUNT(*) INTO v_doctor_count FROM Doctor WHERE aadhar_id = doc_id;
    IF v_doctor_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Doctor with Aadhar ID ' || doc_id || ' does not exist.');
        RETURN;
    END IF;
    
    -- Check if patient exists
    SELECT COUNT(*) INTO v_patient_count FROM Patient WHERE aadhar_id = pat_id;
    IF v_patient_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Patient with Aadhar ID ' || pat_id || ' does not exist.');
        RETURN;
    END IF;
    
    -- Check if prescription already exists for that date
    SELECT COUNT(*) INTO v_existing_count FROM Prescription
    WHERE doctor_id = doc_id AND patient_id = pat_id AND date_prescribed = date_p;
    IF v_existing_count > 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Prescription already exists for this doctor, patient, and date.');
        RETURN;
    END IF;
    
    INSERT INTO Prescription VALUES(doc_id, pat_id, date_p);
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Prescription added successfully.');
EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
        DBMS_OUTPUT.PUT_LINE('Error: Prescription already exists.');
        ROLLBACK;
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error adding prescription: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE delete_prescription(
    doc_id VARCHAR2, pat_id VARCHAR2, date_p DATE
) AS
    v_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_count FROM Prescription
    WHERE doctor_id = doc_id AND patient_id = pat_id AND date_prescribed = date_p;
    
    IF v_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Prescription does not exist.');
        RETURN;
    END IF;
    
    DELETE FROM Prescription
    WHERE doctor_id = doc_id AND patient_id = pat_id AND date_prescribed = date_p;
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Prescription deleted successfully.');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error deleting prescription: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE add_drugs_prescribed(
    p_name VARCHAR2, trade_name VARCHAR2,
    doc_id VARCHAR2, pat_id VARCHAR2,
    date_p DATE, qty NUMBER
) AS
    v_drug_count NUMBER;
    v_prescription_count NUMBER;
BEGIN
    -- Check if drug exists
    SELECT COUNT(*) INTO v_drug_count FROM Drugs
    WHERE P_name = p_name AND trade_name = trade_name;
    IF v_drug_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Drug ' || trade_name || ' by company ' || p_name || ' does not exist.');
        RETURN;
    END IF;
    
    -- Check if prescription exists
    SELECT COUNT(*) INTO v_prescription_count FROM Prescription
    WHERE doctor_id = doc_id AND patient_id = pat_id AND date_prescribed = date_p;
    IF v_prescription_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Prescription does not exist for this doctor, patient, and date.');
        RETURN;
    END IF;
    
    -- Check quantity is positive
    IF qty <= 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Quantity must be positive.');
        RETURN;
    END IF;
    
    INSERT INTO Drugs_Prescribed
    VALUES(p_name, trade_name, doc_id, pat_id, date_p, qty);
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Drug prescribed successfully.');
EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
        DBMS_OUTPUT.PUT_LINE('Error: Drug is already prescribed in this prescription.');
        ROLLBACK;
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error prescribing drug: ' || SQLERRM);
        ROLLBACK;
END;
/

CREATE OR REPLACE PROCEDURE delete_drugs_prescribed(
    p_name VARCHAR2, trade_name VARCHAR2,
    doc_id VARCHAR2, pat_id VARCHAR2,
    date_p DATE
) AS
    v_count NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_count FROM Drugs_Prescribed
    WHERE P_name = p_name AND trade_name = trade_name
    AND doctor_id = doc_id AND patient_id = pat_id AND date_prescribed = date_p;
    
    IF v_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Prescribed drug does not exist in this prescription.');
        RETURN;
    END IF;
    
    DELETE FROM Drugs_Prescribed
    WHERE P_name = p_name AND trade_name = trade_name
    AND doctor_id = doc_id AND patient_id = pat_id AND date_prescribed = date_p;
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('Prescribed drug deleted successfully.');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error deleting prescribed drug: ' || SQLERRM);
        ROLLBACK;
END;
/





















CREATE OR REPLACE PROCEDURE prescription_report(
    p_patient_id VARCHAR2, start_period DATE, end_period DATE
) AS
    v_patient_exists NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_patient_exists FROM Patient WHERE aadhar_id = p_patient_id;
    
    IF v_patient_exists = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Patient not found.');
        RETURN;
    END IF;
    
    DBMS_OUTPUT.PUT_LINE('===== Prescription Report for Patient: ' || p_patient_id || ' =====');
    DBMS_OUTPUT.PUT_LINE('Period: ' || TO_CHAR(start_period, 'DD-MON-YYYY') || ' to ' || TO_CHAR(end_period, 'DD-MON-YYYY'));
    DBMS_OUTPUT.PUT_LINE('------------------------------------');
    
    FOR rec IN (
        SELECT p.doctor_id, d.name as doctor_name, p.date_prescribed 
        FROM Prescription p
        JOIN Doctor d ON p.doctor_id = d.aadhar_id
        WHERE p.patient_id = p_patient_id AND p.date_prescribed BETWEEN start_period AND end_period
        ORDER BY p.date_prescribed
    ) LOOP
        DBMS_OUTPUT.PUT_LINE('Doctor: ' || rec.doctor_name || ' (' || rec.doctor_id || '), Date: ' || TO_CHAR(rec.date_prescribed, 'DD-MON-YYYY'));
    END LOOP;
    
    DBMS_OUTPUT.PUT_LINE('------------------------------------');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error generating report: ' || SQLERRM);
END;
/

CREATE OR REPLACE PROCEDURE prescription_details(
    p_patient_id VARCHAR2, prescribed_date DATE
) AS
    v_exists NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_exists FROM Prescription 
    WHERE patient_id = p_patient_id AND date_prescribed = prescribed_date;
    
    IF v_exists = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Prescription not found.');
        RETURN;
    END IF;
    
    DBMS_OUTPUT.PUT_LINE('===== Prescription Details =====');
    DBMS_OUTPUT.PUT_LINE('Patient ID: ' || p_patient_id);
    DBMS_OUTPUT.PUT_LINE('Date: ' || TO_CHAR(prescribed_date, 'DD-MON-YYYY'));
    DBMS_OUTPUT.PUT_LINE('----------------------------');
    
    FOR rec IN (
        SELECT dp.trade_name, c.P_name as company, dp.qty 
        FROM Drugs_Prescribed dp
        JOIN Pharmaceutical_Company c ON dp.P_name = c.P_name
        WHERE dp.patient_id = p_patient_id AND dp.date_prescribed = prescribed_date
    ) LOOP
        DBMS_OUTPUT.PUT_LINE('Drug: ' || rec.trade_name || ' (by ' || rec.company || '), Quantity: ' || rec.qty);
    END LOOP;
    
    DBMS_OUTPUT.PUT_LINE('----------------------------');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error retrieving details: ' || SQLERRM);
END;
/

CREATE OR REPLACE PROCEDURE drugs_by_company(p_name VARCHAR2) AS
    v_exists NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_exists FROM Pharmaceutical_Company WHERE P_name = p_name;
    
    IF v_exists = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Company not found.');
        RETURN;
    END IF;
    
    DBMS_OUTPUT.PUT_LINE('===== Drugs by ' || p_name || ' =====');
    
    FOR rec IN (
        SELECT trade_name, formula FROM Drugs WHERE P_name = p_name
    ) LOOP
        DBMS_OUTPUT.PUT_LINE('Drug: ' || rec.trade_name || ', Formula: ' || rec.formula);
    END LOOP;
    
    DBMS_OUTPUT.PUT_LINE('---------------------------');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error retrieving drugs: ' || SQLERRM);
END;
/

CREATE OR REPLACE PROCEDURE pharmacy_stock(p_name VARCHAR2) AS
    v_exists NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_exists FROM Pharmacy WHERE Ph_name = p_name;
    
    IF v_exists = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Pharmacy not found.');
        RETURN;
    END IF;
    
    DBMS_OUTPUT.PUT_LINE('===== Stock at ' || p_name || ' =====');
    
    FOR rec IN (
        SELECT ps.trade_name, ps.P_name as company, ps.price 
        FROM Pharmacy_Sells ps
        WHERE ps.Ph_name = p_name
    ) LOOP
        DBMS_OUTPUT.PUT_LINE('Drug: ' || rec.trade_name || ' (by ' || rec.company || '), Price: Rs.' || rec.price);
    END LOOP;
    
    DBMS_OUTPUT.PUT_LINE('---------------------------');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error retrieving stock: ' || SQLERRM);
END;
/

CREATE OR REPLACE PROCEDURE contact_details(pharmacy_name VARCHAR2, company_name VARCHAR2) AS
    v_exists NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_exists FROM Contract_With 
    WHERE Ph_name = pharmacy_name AND P_name = company_name;
    
    IF v_exists = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Contract not found.');
        RETURN;
    END IF;
    
    DBMS_OUTPUT.PUT_LINE('===== Contract Details =====');
    DBMS_OUTPUT.PUT_LINE('Pharmacy: ' || pharmacy_name);
    DBMS_OUTPUT.PUT_LINE('Company: ' || company_name);
    
    FOR rec IN (
        SELECT start_date, end_date, supervisor, contract_content FROM Contract_With
        WHERE Ph_name = pharmacy_name AND P_name = company_name
    ) LOOP
        DBMS_OUTPUT.PUT_LINE('Start Date: ' || TO_CHAR(rec.start_date, 'DD-MON-YYYY'));
        DBMS_OUTPUT.PUT_LINE('End Date: ' || TO_CHAR(rec.end_date, 'DD-MON-YYYY'));
        DBMS_OUTPUT.PUT_LINE('Supervisor: ' || rec.supervisor);
        DBMS_OUTPUT.PUT_LINE('Content: ' || rec.contract_content);
    END LOOP;
    
    DBMS_OUTPUT.PUT_LINE('---------------------------');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error retrieving contract: ' || SQLERRM);
END;
/

CREATE OR REPLACE PROCEDURE patients_of_doctor(p_doctor_id VARCHAR2) AS
    v_exists NUMBER;
    v_doctor_name VARCHAR2(100);
BEGIN
    SELECT COUNT(*) INTO v_exists FROM Doctor WHERE aadhar_id = p_doctor_id;
    
    IF v_exists = 0 THEN
        DBMS_OUTPUT.PUT_LINE('Error: Doctor not found.');
        RETURN;
    END IF;
    
    SELECT name INTO v_doctor_name FROM Doctor WHERE aadhar_id = p_doctor_id;
    
    DBMS_OUTPUT.PUT_LINE('===== Patients of Dr. ' || v_doctor_name || ' =====');
    
    FOR rec IN (
        SELECT name, aadhar_id, age FROM Patient WHERE D_aadhar = p_doctor_id
    ) LOOP
        DBMS_OUTPUT.PUT_LINE('Patient: ' || rec.name || ' (ID: ' || rec.aadhar_id || '), Age: ' || rec.age);
    END LOOP;
    
    DBMS_OUTPUT.PUT_LINE('---------------------------');
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error retrieving patients: ' || SQLERRM);
END;
/

-- Insert sample data
-- Insert Pharmacies 
BEGIN
    add_pharmacy('Nova Main', '123 Main St, Delhi', '9876543210');
    add_pharmacy('Nova West', '456 West Blvd, Mumbai', '8765432109');
    add_pharmacy('Nova East', '789 East Ave, Chennai', '7654321098');
    add_pharmacy('Nova North', '101 North Rd, Kolkata', '6543210987');
    add_pharmacy('Nova South', '202 South St, Bangalore', '5432109876');
    add_stock('Nova Main','midcap');
END;
/

-- Insert Pharmaceutical Companies
BEGIN
    add_company('PharmaCo', '1112223334');
    add_company('MedicinePlus', '2223334445');
    add_company('HealthDrugs', '3334445556');
    add_company('CurePharma', '4445556667');
    add_company('LifeMeds', '5556667778');
END;
/

-- Insert Drugs for each company
BEGIN
    -- PharmaCo drugs
    add_drug('Aspirin', 'PharmaCo', 'C9H8O4');
    add_drug('Paracetamol', 'PharmaCo', 'C8H9NO2');
    add_drug('Ibuprofen', 'PharmaCo', 'C13H18O2');
    
    -- MedicinePlus drugs
    add_drug('Amoxicillin', 'MedicinePlus', 'C16H19N3O5S');
    add_drug('Ciprofloxacin', 'MedicinePlus', 'C17H18FN3O3');
    add_drug('Metformin', 'MedicinePlus', 'C4H11N5');
    
    -- HealthDrugs drugs
    add_drug('Atorvastatin', 'HealthDrugs', 'C33H35FN2O5');
    add_drug('Omeprazole', 'HealthDrugs', 'C17H19N3O3S');
    add_drug('Losartan', 'HealthDrugs', 'C22H23ClN6O');
    
    -- CurePharma drugs
    add_drug('Amlodipine', 'CurePharma', 'C20H25ClN2O5');
    add_drug('Sertraline', 'CurePharma', 'C17H17Cl2N');
    add_drug('Citalopram', 'CurePharma', 'C20H21FN2O');
    
    -- LifeMeds drugs
    add_drug('Levothyroxine', 'LifeMeds', 'C15H11I4NO4');
    add_drug('Diazepam', 'LifeMeds', 'C16H13ClN2O');
    add_drug('Warfarin', 'LifeMeds', 'C19H16O4');
END;
/

-- Add drugs to pharmacies
BEGIN
    -- Nova Main pharmacy stocks
    add_sale('Nova Main', 'PharmaCo', 'Aspirin', 15.50);
    add_sale('Nova Main', 'PharmaCo', 'Paracetamol', 12.75);
    add_sale('Nova Main', 'MedicinePlus', 'Amoxicillin', 45.99);
    add_sale('Nova Main', 'MedicinePlus', 'Ciprofloxacin', 65.25);
    add_sale('Nova Main', 'HealthDrugs', 'Atorvastatin', 120.50);
    add_sale('Nova Main', 'HealthDrugs', 'Omeprazole', 85.75);
    add_sale('Nova Main', 'CurePharma', 'Amlodipine', 55.99);
    add_sale('Nova Main', 'CurePharma', 'Sertraline', 75.25);
    add_sale('Nova Main', 'LifeMeds', 'Levothyroxine', 95.50);
    add_sale('Nova Main', 'LifeMeds', 'Diazepam', 35.75);
    
    -- Nova West pharmacy stocks
    add_sale('Nova West', 'PharmaCo', 'Aspirin', 16.50);
    add_sale('Nova West', 'PharmaCo', 'Ibuprofen', 18.25);
    add_sale('Nova West', 'MedicinePlus', 'Metformin', 35.99);
    add_sale('Nova West', 'HealthDrugs', 'Losartan', 110.25);
    add_sale('Nova West', 'CurePharma', 'Citalopram', 82.50);
    add_sale('Nova West', 'LifeMeds', 'Warfarin', 62.75);
    add_sale('Nova West', 'PharmaCo', 'Paracetamol', 13.99);
    add_sale('Nova West', 'MedicinePlus', 'Amoxicillin', 47.25);
    add_sale('Nova West', 'HealthDrugs', 'Atorvastatin', 122.50);
    add_sale('Nova West', 'CurePharma', 'Amlodipine', 58.75);
END;
/

-- Insert Doctors
BEGIN
    add_doctor('123456789012', 'Dr. Alice Smith', 'General Physician', 15);
    add_doctor('234567890123', 'Dr. Bob Johnson', 'Cardiologist', 20);
    add_doctor('345678901234', 'Dr. Carol Williams', 'Dermatologist', 10);
    add_doctor('456789012345', 'Dr. David Brown', 'Pediatrician', 8);
    add_doctor('567890123456', 'Dr. Eve Davis', 'Neurologist', 18);
END;
/

-- Insert Patients
BEGIN
    add_patient('987654321098', 'John Doe', '123 Elm St, Delhi', 35, '123456789012');
    add_patient('876543210987', 'Jane Smith', '456 Oak Rd, Mumbai', 42, '234567890123');
    add_patient('765432109876', 'Mike Johnson', '789 Pine Ave, Chennai', 28, '345678901234');
    add_patient('654321098765', 'Sarah Wilson', '101 Cedar Ln, Kolkata', 50, '456789012345');
    add_patient('543210987654', 'Tom Davis', '202 Birch Blvd, Bangalore', 65, '567890123456');
    add_patient('432109876543', 'Lisa Brown', '303 Maple Dr, Delhi', 45, '123456789012');
    add_patient('321098765432', 'Chris Miller', '404 Aspen Way, Mumbai', 30, '234567890123');
    add_patient('210987654321', 'Amanda White', '505 Redwood Ct, Chennai', 22, '345678901234');
    add_patient('109876543210', 'Kevin Chen', '606 Spruce Pl, Kolkata', 38, '456789012345');
    add_patient('098765432109', 'Rachel Park', '707 Fir Rd, Bangalore', 55, '567890123456');
END;
/

-- Insert Contracts
BEGIN
    add_contract('PharmaCo', 'Nova Main', TO_DATE('2025-01-01','YYYY-MM-DD'), 
                TO_DATE('2025-12-31','YYYY-MM-DD'), 'Annual supply agreement', 'Raj Kumar');
    add_contract('MedicinePlus', 'Nova Main', TO_DATE('2025-02-01','YYYY-MM-DD'), 
                TO_DATE('2026-01-31','YYYY-MM-DD'), 'Bi-annual supply contract', 'Priya Singh');
    add_contract('HealthDrugs', 'Nova West', TO_DATE('2025-01-15','YYYY-MM-DD'), 
                TO_DATE('2025-07-14','YYYY-MM-DD'), 'Six-month agreement', 'Amit Patel');
    add_contract('CurePharma', 'Nova East', TO_DATE('2025-03-01','YYYY-MM-DD'), 
                TO_DATE('2026-02-28','YYYY-MM-DD'), 'Annual contract with quarterly review', 'Neha Sharma');
    add_contract('LifeMeds', 'Nova North', TO_DATE('2025-04-01','YYYY-MM-DD'), 
                TO_DATE('2026-03-31','YYYY-MM-DD'), 'Premium supply agreement', 'Vijay Gupta');
END;
/

-- Insert Prescriptions and Prescribed Drugs
BEGIN
    -- Prescription 1
    add_prescription('123456789012', '987654321098', TO_DATE('2025-04-01','YYYY-MM-DD'));
    add_drugs_prescribed('PharmaCo', 'Aspirin', '123456789012', '987654321098', TO_DATE('2025-04-01','YYYY-MM-DD'), 20);
    add_drugs_prescribed('PharmaCo', 'Paracetamol', '123456789012', '987654321098', TO_DATE('2025-04-01','YYYY-MM-DD'), 15);
    
    -- Prescription 2
    add_prescription('234567890123', '876543210987', TO_DATE('2025-04-05','YYYY-MM-DD'));
    add_drugs_prescribed('HealthDrugs', 'Atorvastatin', '234567890123', '876543210987', TO_DATE('2025-04-05','YYYY-MM-DD'), 30);
    
    -- Prescription 3
    add_prescription('345678901234', '765432109876', TO_DATE('2025-04-10','YYYY-MM-DD'));
    add_drugs_prescribed('CurePharma', 'Sertraline', '345678901234', '765432109876', TO_DATE('2025-04-10','YYYY-MM-DD'), 60);
    
    -- Prescription 4
    add_prescription('456789012345', '654321098765', TO_DATE('2025-04-15','YYYY-MM-DD'));
    add_drugs_prescribed('MedicinePlus', 'Amoxicillin', '456789012345', '654321098765', TO_DATE('2025-04-15','YYYY-MM-DD'), 21);
    add_drugs_prescribed('MedicinePlus', 'Ciprofloxacin', '456789012345', '654321098765', TO_DATE('2025-04-15','YYYY-MM-DD'), 14);
END;
/

SET SERVEROUTPUT ON;

-- Test all report procedures
BEGIN
    DBMS_OUTPUT.PUT_LINE('===== Testing Report Procedures =====');
    DBMS_OUTPUT.PUT_LINE('');
    
    DBMS_OUTPUT.PUT_LINE('1. Prescription Report for Patient:');
    prescription_report('987654321098', DATE '2025-01-01', DATE '2025-12-31');
    DBMS_OUTPUT.PUT_LINE('');
    
    DBMS_OUTPUT.PUT_LINE('2. Prescription Details:');
    prescription_details('987654321098', DATE '2025-04-01');
    DBMS_OUTPUT.PUT_LINE('');
    
    DBMS_OUTPUT.PUT_LINE('3. Drugs by Company:');
    drugs_by_company('PharmaCo');
    DBMS_OUTPUT.PUT_LINE('');
    
    DBMS_OUTPUT.PUT_LINE('4. Pharmacy Stock:');
    pharmacy_stock('Nova Main');
    DBMS_OUTPUT.PUT_LINE('');
    
    DBMS_OUTPUT.PUT_LINE('5. Contract Details:');
    contact_details('Nova Main', 'PharmaCo');
    DBMS_OUTPUT.PUT_LINE('');
    
    DBMS_OUTPUT.PUT_LINE('6. Patients of Doctor:');
    patients_of_doctor('123456789012');
    DBMS_OUTPUT.PUT_LINE('');
END;
/



